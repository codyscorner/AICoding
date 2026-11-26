import csv
import io
import json
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import requests
from PIL import Image, ImageOps
from PyQt6.QtCore import QThread, pyqtSignal

PROMPT_SEPARATOR = "---- PROMPT START -----"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
OUTPUT_EXTS = IMAGE_EXTS | {".mp4", ".mov", ".avi", ".mkv", ".gif"}
PROMPT_LOG_NAME = "prompt_log.csv"

# Separator may carry an optional weight suffix, e.g. "---- PROMPT START x3 -----"
_SEP_RE = re.compile(
    r"^-+\s*PROMPT START(?:\s+x\s*(\d+(?:\.\d+)?))?\s*-+\s*$",
    re.MULTILINE,
)


# How the main character reaches the workflow:
#   reference    - uploaded as its own image into the workflow's 2nd Load Image
#   stitch_left  - joined side by side with the folder image into ONE image
#   stitch_right   (main character on the left / right), sent to the 1st Load Image
MAIN_MODES = ("reference", "stitch_left", "stitch_right")
STITCH_MAX_HEIGHT = 1536   # the workflow rescales to ~2 MP anyway; keeps uploads small


# Output shape: the aspect ratio (width, height) the new image is generated at.
# "auto" leaves the workflow alone (most workflows size the result from the input
# image, so a side-by-side stitch gives a wide result).
OUTPUT_SHAPES = {
    "auto":          None,
    "portrait_2_3":  (2, 3),
    "portrait_3_4":  (3, 4),
    "square":        (1, 1),
    "landscape_4_3": (4, 3),
    "landscape_3_2": (3, 2),
}
# Nodes whose width/height decide the size of the generated image
_LATENT_SIZE_NODES = {"EmptyFlux2LatentImage", "EmptyLatentImage", "EmptySD3LatentImage"}
_SIZE_AWARE_NODES = _LATENT_SIZE_NODES | {"Flux2Scheduler"}   # scheduler uses the size for its shift


def shape_dimensions(aspect: tuple[int, int], megapixels: float) -> tuple[int, int]:
    """(width, height) for `aspect` holding about `megapixels` MP, both snapped to
    multiples of 16 (the latent grid of Flux-style models). The width follows the
    pixel budget and the height follows the width, so the ratio stays as exact as
    the 16 px grid allows (a square really is square)."""
    aw, ah = aspect
    width = max(16, round((megapixels * 1_000_000 * aw / ah) ** 0.5 / 16) * 16)
    height = max(16, round(width * ah / aw / 16) * 16)
    return width, height


def _flat_rgb(path: Path) -> Image.Image:
    """Open an image upright (EXIF) and flat RGB - transparency goes onto white."""
    img = ImageOps.exif_transpose(Image.open(path))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def stitch_side_by_side(left: Path, right: Path, max_height: int = STITCH_MAX_HEIGHT) -> bytes:
    """PNG bytes of `left` and `right` joined into one image, both scaled to the
    same height (the taller one's, capped at max_height), aspect ratios kept."""
    a, b = _flat_rgb(left), _flat_rgb(right)
    height = min(max_height, max(a.height, b.height))
    scaled = [im.resize((max(1, round(im.width * height / im.height)), height), Image.LANCZOS)
              for im in (a, b)]
    canvas = Image.new("RGB", (scaled[0].width + scaled[1].width, height), "white")
    canvas.paste(scaled[0], (0, 0))
    canvas.paste(scaled[1], (scaled[0].width, 0))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


class PromptEntry(NamedTuple):
    text: str
    weight: float = 1.0


def parse_prompts(text: str) -> list[PromptEntry]:
    matches = list(_SEP_RE.finditer(text))
    entries = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        weight = float(m.group(1)) if m.group(1) else 1.0
        entries.append(PromptEntry(body, weight))
    return entries


def load_prompts(path: Path) -> list[PromptEntry]:
    return parse_prompts(path.read_text(encoding="utf-8"))


def log_prompt_used(output_dir: Path, image_name: str, prompt_index: int | str,
                     prompt_preview: str, weight: float | str = "", note: str = ""):
    log_path = output_dir / PROMPT_LOG_NAME
    is_new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "image", "prompt_index", "weight", "note", "prompt_preview"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            image_name,
            prompt_index,
            weight,
            note,
            prompt_preview.replace("\n", " ")[:120],
        ])


def append_daily_log(base_dir: Path, text: str):
    """Appends a line to logs/<today>.txt next to the EXE (base_dir must already
    be the frozen-EXE-aware directory — see main.py's BASE_DIR)."""
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.txt"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n")


PROMPT_MODES = ("random", "sequential", "evens_odds")


class ComfyRunError(Exception):
    """ComfyUI itself said it cannot make this image - a model/node it cannot
    find, a workflow it rejected, a failure while executing. The next image
    would hit the same wall, so the run stops instead of burning through the
    rest of the list (and the pod's per-second billing) producing nothing."""


def _short(text, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def describe_prompt_rejection(resp) -> str:
    """Turn a failed POST /prompt into the reason ComfyUI gave.

    A 400 carries {"error": {"message", "details"}, "node_errors": {id: {
    "class_type", "errors": [{"message", "details"}]}}} - e.g. "Value not in
    list: unet_name" when a model file is missing on the pod."""
    try:
        data = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {_short(resp.text) or resp.reason}"
    if not isinstance(data, dict):
        return f"HTTP {resp.status_code}: {_short(data)}"
    err = data.get("error")
    if isinstance(err, dict):
        head = err.get("message") or err.get("type") or "rejected"
        if err.get("details"):
            head += f" ({_short(err['details'])})"
    else:
        head = str(err) if err else f"HTTP {resp.status_code}"
    parts = []
    for node_id, info in (data.get("node_errors") or {}).items():
        for e in (info.get("errors") or []):
            msg = e.get("message", "")
            if e.get("details"):
                msg += f": {e['details']}"
            parts.append(f"node {node_id} ({info.get('class_type', '?')}): {_short(msg)}")
    return head + "".join(f"\n    {x}" for x in parts[:5])


def describe_execution_error(info: dict) -> str:
    """One line for an execution_error (websocket message or /history record)."""
    return (f"{info.get('exception_type', 'Error')} in node {info.get('node_id', '?')} "
            f"({info.get('node_type', '?')}): {_short(info.get('exception_message', ''))}")


def describe_history_error(entry: dict) -> str | None:
    """The failure recorded in a /history entry, or None if it did not fail."""
    status = entry.get("status") or {}
    if status.get("status_str") != "error":
        return None
    for kind, info in status.get("messages") or []:
        if kind == "execution_error" and isinstance(info, dict):
            return describe_execution_error(info)
    return "ComfyUI reported an execution error"


# Anything that is not a ComfyUI verdict (network blip, timeout) is retried
# on the next image, but not forever.
MAX_CONSECUTIVE_FAILURES = 3


class BatchStyleWorker(QThread):
    progress = pyqtSignal(int, int)   # current, total
    log      = pyqtSignal(str)
    all_done = pyqtSignal()
    error    = pyqtSignal(str)
    image_done = pyqtSignal(str, str)  # source image stem, saved output path - emitted per image
    step     = pyqtSignal(int, int)    # sampler step, of total - for the current image; (0, 0) = preparing

    def __init__(self, config: dict, prompts: list[PromptEntry], image_paths: list[Path],
                 fixed_prompt: str | None = None, prompt_mode: str = "random",
                 pinned: dict[str, str] | None = None, base_dir: Path | None = None):
        super().__init__()
        self._config        = config
        self._prompts       = prompts
        self._image_paths   = image_paths
        self._fixed_prompt  = fixed_prompt
        self._prompt_mode   = prompt_mode
        self._pinned        = pinned or {}
        self._base_dir      = base_dir
        self._cancelled     = False
        self._shape_warned = False
        self._main_path: Path | None = None
        self._main_stitch_left: bool | None = None   # None = not stitching
        self._client_id   = str(uuid.uuid4())
        runpod = config.get("mode", "local") == "runpod"
        self._url = (
            config.get("runpod_url", "").rstrip("/")
            if runpod
            else config.get("comfyui_url", "http://127.0.0.1:8000").rstrip("/")
        )
        self._output_dir   = Path(config.get("output_dir", ""))
        self._skip_existing = config.get("skip_existing", True)

    def cancel(self):
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def _log(self, msg: str):
        self.log.emit(msg)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = int(seconds)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    # ------------------------------------------------------------------ #
    # Main thread entry
    # ------------------------------------------------------------------ #

    def run(self):
        try:
            workflow_path = Path(self._config.get("workflow_path", ""))
            if not workflow_path.is_file():
                self.error.emit("Workflow file not found. Select a workflow JSON in the Paths section.")
                return
            if not self._prompts:
                self.error.emit("No prompts loaded. Select a prompts file.")
                return

            self._output_dir.mkdir(parents=True, exist_ok=True)
            base_workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            total = len(self._image_paths)
            start_time = time.time()
            self._log(f"Starting — {total} images, {len(self._prompts)} prompts")
            if self._base_dir:
                append_daily_log(
                    self._base_dir,
                    f"\n=== Run started {datetime.now().strftime('%H:%M:%S')} — "
                    f"{total} images, {len(self._prompts)} prompts ===",
                )

            main_uploaded = self._upload_main_character(base_workflow)
            shape = self._config.get("output_shape", "auto")
            if OUTPUT_SHAPES.get(shape):
                mp = next((float(n["inputs"].get("megapixels", 1.0)) for n in base_workflow.values()
                           if n.get("class_type") == "ImageScaleToTotalPixels"), 1.0)
                w_, h_ = shape_dimensions(OUTPUT_SHAPES[shape], mp)
                self._log(f"Output shape: {shape.replace('_', ' ')} ({w_}x{h_})")

            texts   = [e.text for e in self._prompts]
            weights = [e.weight for e in self._prompts]

            # Build ordered prompt sequence for non-random modes
            if self._prompt_mode == "sequential":
                _seq = list(texts)
            elif self._prompt_mode == "evens_odds":
                evens = texts[0::2]
                odds  = texts[1::2]
                _seq  = evens + odds
            else:
                _seq = None  # weighted random per image

            seq_pos = 0  # cursor for sequential / evens_odds
            failures = 0  # consecutive non-ComfyUI failures

            for i, img_path in enumerate(self._image_paths):
                if self._cancelled:
                    elapsed = self._format_elapsed(time.time() - start_time)
                    self._log(f"Cancelled. ({elapsed})")
                    if self._base_dir:
                        append_daily_log(self._base_dir, f"=== Cancelled ({elapsed}) ===")
                    self.all_done.emit()
                    return

                if self._skip_existing and self._output_exists(img_path.stem):
                    self._log(f"[{i+1}/{total}] Skipped (exists): {img_path.name}")
                    self.progress.emit(i + 1, total)
                    continue

                note = ""
                prompt_idx: int | str = ""
                weight_used: float | str = ""

                if img_path.stem in self._pinned:
                    prompt     = self._pinned[img_path.stem]
                    note       = "pinned"
                    prompt_idx = texts.index(prompt) + 1 if prompt in texts else "custom"
                    preview    = prompt.replace("\n", " ")[:255]
                    self._log(f"[{i+1}/{total}] {img_path.name}  →  📌 {preview}…")
                elif self._fixed_prompt is not None:
                    prompt  = self._fixed_prompt
                    preview = prompt.replace("\n", " ")[:255]
                    prompt_idx = texts.index(prompt) + 1 if prompt in texts else "custom"
                    self._log(f"[{i+1}/{total}] {img_path.name}  →  {preview}…")
                elif _seq is not None:
                    idx        = seq_pos % len(_seq)
                    prompt     = _seq[idx]
                    prompt_idx = texts.index(prompt) + 1 if prompt in texts else "custom"
                    preview    = prompt.replace("\n", " ")[:255]
                    self._log(f"[{i+1}/{total}] {img_path.name}  →  style #{prompt_idx}: {preview}…")
                    seq_pos += 1
                else:
                    idx         = random.choices(range(len(texts)), weights=weights, k=1)[0]
                    prompt      = texts[idx]
                    prompt_idx  = idx + 1
                    weight_used = weights[idx]
                    preview     = prompt.replace("\n", " ")[:255]
                    self._log(f"[{i+1}/{total}] {img_path.name}  →  style #{prompt_idx}: {preview}…")

                if self._base_dir:
                    append_daily_log(
                        self._base_dir,
                        f"{datetime.now().strftime('%H:%M:%S')}  {img_path.name}  ->  "
                        f"{prompt.replace(chr(10), ' ')}",
                    )

                self.step.emit(0, 0)
                try:
                    workflow = json.loads(json.dumps(base_workflow))
                    seed     = random.randint(1, 2**31)

                    if self._main_stitch_left is not None:
                        # main character + this folder image become ONE image
                        left, right = ((self._main_path, img_path) if self._main_stitch_left
                                       else (img_path, self._main_path))
                        uploaded = self._upload_image(
                            img_path, upload_name=f"{img_path.stem}_stitched.png",
                            data=stitch_side_by_side(left, right))
                    else:
                        uploaded = self._upload_image(img_path)
                    self._patch_image(workflow, uploaded, main_uploaded)
                    self._patch_prompt(workflow, prompt)
                    self._patch_seed(workflow, seed)
                    self._patch_output_shape(workflow)

                    prompt_id = self._queue_prompt(workflow)
                    self._poll_until_done(prompt_id)

                    if self._cancelled:
                        elapsed = self._format_elapsed(time.time() - start_time)
                        self._log(f"Cancelled. ({elapsed})")
                        if self._base_dir:
                            append_daily_log(self._base_dir, f"=== Cancelled ({elapsed}) ===")
                        self.all_done.emit()
                        return

                    saved = self._get_output(prompt_id, img_path)
                    self._log(f"  ✓ {saved.name}")
                    self.image_done.emit(img_path.stem, str(saved))
                    log_prompt_used(self._output_dir, saved.name, prompt_idx, prompt, weight_used, note)
                    failures = 0
                except ComfyRunError as exc:
                    self._log(f"  ✗ {exc}")
                    self._abort(f"{img_path.name}: {exc}", start_time)
                    return
                except Exception as exc:
                    self._log(f"  ✗ {exc}")
                    failures += 1
                    if failures >= MAX_CONSECUTIVE_FAILURES:
                        self._abort(
                            f"{failures} images in a row failed - last: {img_path.name}: {exc}",
                            start_time)
                        return

                self.progress.emit(i + 1, total)

            elapsed = self._format_elapsed(time.time() - start_time)
            self._log(f"Done! {total} images processed in {elapsed}.")
            if self._base_dir:
                append_daily_log(self._base_dir, f"=== Done: {total} images processed in {elapsed} ===")
            self.all_done.emit()

        except Exception as exc:
            self.error.emit(str(exc))

    def _upload_main_character(self, workflow: dict) -> str | None:
        """Prepare the main character for the run. Returns the server-side name
        of its uploaded image in "reference" mode; None when the feature is off
        or in a stitch mode (where it is joined to each folder image instead -
        self._main_stitch_left says on which side).

        The reference upload goes up under a "main_character_" name so it can
        never overwrite (the upload uses overwrite=true) a folder image that has
        the same file name."""
        self._main_stitch_left = None
        if not self._config.get("main_character_enabled", False):
            return None
        path = Path(self._config.get("main_character_path", "") or "")
        if not path.is_file():
            raise ComfyRunError(f"Main character image not found: {path}")
        self._main_path = path
        mode = self._config.get("main_character_mode", "reference")
        if mode not in MAIN_MODES:
            mode = "reference"

        if mode == "reference":
            if self.find_main_character_node(workflow) is None:
                raise ComfyRunError(
                    "The main character is set to go in as a separate reference, but this "
                    "workflow has only one Load Image node. Choose 'Stitched into one image' "
                    "for the main character, or use a workflow with a second Load Image "
                    "node (title it 'Main Character').")
            how = "separate reference"
            name = self._upload_image(path, upload_name=f"main_character_{path.name}")
        else:
            self._main_stitch_left = (mode == "stitch_left")
            how = f"stitched into each image, on the {'left' if self._main_stitch_left else 'right'}"
            name = None
        self._log(f"Main character: {path.name} ({how})")
        if self._base_dir:
            append_daily_log(self._base_dir, f"Main character: {path} ({how})")
        return name

    def _abort(self, msg: str, start_time: float):
        """Stop the whole run: log it, tell the window (which shows the error)."""
        elapsed = self._format_elapsed(time.time() - start_time)
        self._log(f"STOPPED - run aborted after {elapsed}")
        if self._base_dir:
            append_daily_log(self._base_dir, f"=== STOPPED ({elapsed}): {msg} ===")
        self.error.emit(msg)

    # ------------------------------------------------------------------ #
    # Workflow patching
    # ------------------------------------------------------------------ #

    @staticmethod
    def find_main_character_node(workflow: dict) -> str | None:
        """ID of the LoadImage that holds the fixed "main character" photo: the
        one titled "...main character...", else the second LoadImage in the file.
        None when the workflow has no second image slot."""
        loads = [(nid, n) for nid, n in workflow.items() if n.get("class_type") == "LoadImage"]
        for nid, n in loads:
            if "main character" in (n.get("_meta") or {}).get("title", "").lower():
                return nid
        return loads[1][0] if len(loads) > 1 else None

    def _patch_image(self, workflow: dict, filename: str, main_filename: str | None = None):
        """The folder image goes in the first LoadImage that is not the main
        character slot. The main character slot is only touched when a main
        character is set - otherwise the workflow keeps whatever it names."""
        main_id = self.find_main_character_node(workflow)
        for nid, node in workflow.items():
            if node.get("class_type") == "LoadImage" and nid != main_id:
                node["inputs"]["image"] = filename
                break
        if main_filename and main_id is not None:
            workflow[main_id]["inputs"]["image"] = main_filename

    def _patch_prompt(self, workflow: dict, prompt: str):
        # Prefer PrimitiveStringMultiline (Qwen / some custom workflows)
        for node in workflow.values():
            if node.get("class_type") == "PrimitiveStringMultiline":
                node["inputs"]["value"] = prompt
                return
        # Fall back to first non-negative CLIPTextEncode
        for node in workflow.values():
            if node.get("class_type") == "CLIPTextEncode":
                if "neg" not in node.get("_meta", {}).get("title", "").lower():
                    node["inputs"]["text"] = prompt
                    return

    def _patch_output_shape(self, workflow: dict) -> bool:
        """Force the generated image's aspect ratio (config "output_shape").

        The size is written straight into the latent / scheduler nodes, cutting
        the link to the "Get Image Size" node, so the input image (or a stitched
        pair) can have any shape and the result still comes out as asked. The
        pixel budget is the one the workflow already uses for its input scale
        (ImageScaleToTotalPixels), else 1 MP. Returns False when the workflow
        has nothing to resize."""
        aspect = OUTPUT_SHAPES.get(self._config.get("output_shape", "auto"))
        if aspect is None:
            return True
        megapixels = 1.0
        for node in workflow.values():
            if node.get("class_type") == "ImageScaleToTotalPixels":
                try:
                    megapixels = float(node["inputs"].get("megapixels", 1.0))
                except (TypeError, ValueError):
                    pass
                break
        width, height = shape_dimensions(aspect, megapixels)
        patched = 0
        for node in workflow.values():
            ct = node.get("class_type")
            if ct in _SIZE_AWARE_NODES:
                node["inputs"]["width"], node["inputs"]["height"] = width, height
                patched += ct in _LATENT_SIZE_NODES
        if not patched:
            if not self._shape_warned:
                self._log("  (output shape ignored - this workflow has no latent-size node to set)")
                self._shape_warned = True
            return False
        return True

    def _patch_seed(self, workflow: dict, seed: int):
        for node in workflow.values():
            inp = node.get("inputs", {})
            if node.get("class_type") == "KSampler":
                inp["seed"] = seed
            if "noise_seed" in inp:
                inp["noise_seed"] = seed
            if "seed" in inp and isinstance(inp["seed"], int):
                inp["seed"] = seed

    # ------------------------------------------------------------------ #
    # ComfyUI API helpers
    # ------------------------------------------------------------------ #

    def _upload_image(self, img_path: Path, upload_name: str | None = None,
                      data: bytes | None = None) -> str:
        """Upload img_path (or `data` in its place) to the server's input folder."""
        if data is None:
            data = img_path.read_bytes()
        resp = requests.post(
            f"{self._url}/upload/image",
            files={"image": (upload_name or img_path.name, data, "image/png")},
            data={"type": "input", "overwrite": "true"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["name"]

    def _queue_prompt(self, workflow: dict) -> str:
        resp = requests.post(
            f"{self._url}/prompt",
            json={"prompt": workflow, "client_id": self._client_id},
            timeout=30,
        )
        if resp.status_code == 400:
            raise ComfyRunError("ComfyUI rejected the workflow - " + describe_prompt_rejection(resp))
        resp.raise_for_status()
        return resp.json()["prompt_id"]

    def _poll_until_done(self, prompt_id: str):
        """Wait for the prompt to finish. Live sampler steps over ComfyUI's
        websocket (the same approach as the Video Creator and Chain Automator);
        plain HTTP polling when the socket cannot be used."""
        self.step.emit(0, 0)
        try:
            import websocket
        except ImportError:
            return self._poll_http(prompt_id)
        ws_url = self._url.replace("https://", "wss://").replace("http://", "ws://")
        try:
            ws = websocket.create_connection(f"{ws_url}/ws?clientId={self._client_id}", timeout=20)
            ws.settimeout(5)
        except Exception as exc:  # noqa: BLE001
            self._log(f"  (live step progress unavailable: {type(exc).__name__} - polling instead)")
            return self._poll_http(prompt_id)

        start = time.time()
        last_minute = 0
        try:
            while not self._cancelled:
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    # Quiet stretch (model load, VAE decode): confirm through the
                    # history so a missed finish message cannot hang the run.
                    try:
                        if self._history_finished(prompt_id):
                            return
                    except requests.RequestException:
                        pass
                    minute = int(time.time() - start) // 60
                    if minute > last_minute:
                        last_minute = minute
                        self._log(f"  Generating... ({minute}m)")
                    continue
                except Exception:  # noqa: BLE001
                    self._log("  Websocket dropped - polling instead")
                    return self._poll_http(prompt_id)

                if isinstance(msg, bytes):
                    continue                      # binary preview frames
                try:
                    payload = json.loads(msg)
                except ValueError:
                    continue
                mtype = payload.get("type")
                data = payload.get("data") or {}
                if data.get("prompt_id") not in (None, prompt_id):
                    continue                      # another job's message
                if mtype == "progress":
                    self.step.emit(int(data.get("value", 0)), int(data.get("max", 0)))
                elif mtype == "executing" and data.get("node") is None:
                    return                        # the prompt finished
                elif mtype == "execution_success" or mtype == "execution_interrupted":
                    return
                elif mtype == "execution_error":
                    raise ComfyRunError(
                        f"ComfyUI failed while generating - {describe_execution_error(data)}")
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def _history_finished(self, prompt_id: str) -> bool:
        """True once /history has the prompt; raises ComfyRunError if it failed."""
        h = requests.get(f"{self._url}/history/{prompt_id}", timeout=10).json()
        if prompt_id not in h:
            return False
        why = describe_history_error(h[prompt_id])
        if why:
            raise ComfyRunError(f"ComfyUI failed while generating - {why}")
        return True

    def _poll_http(self, prompt_id: str):
        elapsed = 0
        while not self._cancelled:
            time.sleep(3)
            elapsed += 3
            try:
                q = requests.get(f"{self._url}/queue", timeout=10).json()
                running = [item[1] for item in q.get("queue_running", [])]
                pending = [item[1] for item in q.get("queue_pending", [])]
                if prompt_id in running or prompt_id in pending:
                    if elapsed % 60 == 0:
                        self._log(f"  Generating... ({elapsed // 60}m)")
                    continue
                if self._history_finished(prompt_id):
                    return
            except requests.RequestException as exc:
                self._log(f"  Poll error: {exc}")
            if elapsed % 60 == 0:
                self._log(f"  Waiting... ({elapsed // 60}m)")

    def _get_output(self, prompt_id: str, src_img: Path) -> Path:
        h     = requests.get(f"{self._url}/history/{prompt_id}", timeout=15).json()
        entry = h.get(prompt_id, {})

        for node_out in entry.get("outputs", {}).values():
            for key in ("images", "gifs", "videos"):
                files = node_out.get(key, [])
                if files:
                    fi     = files[0]
                    params = {
                        "filename": fi["filename"],
                        "subfolder": fi.get("subfolder", ""),
                        "type": fi.get("type", "output"),
                    }
                    dl  = requests.get(f"{self._url}/view", params=params, timeout=120)
                    dl.raise_for_status()
                    ext  = Path(fi["filename"]).suffix or ".png"
                    dest = self._output_dir / f"{src_img.stem}{ext}"
                    dest.write_bytes(dl.content)
                    return dest

        raise ComfyRunError(
            "ComfyUI finished but produced no image - does the workflow end in a "
            "SaveImage node? (no output found in ComfyUI history)")

    def _output_exists(self, stem: str) -> bool:
        return any((self._output_dir / f"{stem}{ext}").exists() for ext in OUTPUT_EXTS)
