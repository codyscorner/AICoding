"""Background thread that runs ONE workflow against ONE source (an image, a
video, or nothing but the prompt for text-to-video) on the configured
ComfyUI server and downloads the result."""

from __future__ import annotations

import logging
import random
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from comfy_client import ComfyClient
from media_tools import concat_videos, extract_last_frame, probe, resolve_ffmpeg
from remote_cleanup import OutputCleaner, enabled as cleanup_enabled
from workflow_folders import library_dir_for, workflow_rel_of
from workflow_tools import (
    ValueField, analyze, apply_inputs, apply_megapixels, apply_output_format, apply_seed,
    apply_steps, apply_turbo_toggle, apply_value, list_workflows, load_workflow, match_format_value, output_formats,
    set_output_prefix,
)

logger = logging.getLogger("video_creator")
logger.setLevel(logging.DEBUG)

RUN_LOG_NAME = "video_creator_run.log"
RUN_DELIM = "=== New run started ==="


@dataclass
class RunRequest:
    workflow_path: Path
    workflow_label: str
    source_path: Path | None                      # None on the Text → Video tab
    source_kind: str                              # "image" | "video" | "text"
    prompts: dict[tuple[str, str], str] = field(default_factory=dict)
    lora_edits: dict[tuple[str, str], object] = field(default_factory=dict)
    seed: int | None = None                       # None = random
    length_field: ValueField | None = None
    length_value: float | None = None
    steps: int | None = None                      # None = leave the workflow as is
    megapixels: float | None = None
    video_input_mode: str = "auto"                # auto | last_frame | upload_video
    extend_stitch: bool = False
    history_index: int | None = None              # this run's own prompt-history entry
    turbo_enabled: bool | None = None              # None = leave the workflow's turbo wiring as-is
    output_dir_override: Path | None = None        # Library → Reuse Settings: save back into that video's own folder
    prompt_preview: str = ""                       # positive prompt text — queue view only
    settings_summary: str = ""                     # "Seed: random | Steps: 6 | ..." — queue view only
    thumb_path: Path | None = None                 # the frame this run starts from — queue view only
    output_name: str = ""                          # Text → Video: what to name the file, since there is no source

    @property
    def tab_label(self) -> str:
        return TAB_LABELS.get(self.source_kind, self.source_kind)

    @property
    def source_name(self) -> str:
        """What the queue view and logs call the source: the file name, or
        the output name a text-to-video run will be saved under."""
        if self.source_path is not None:
            return self.source_path.name
        return f"(prompt only → {_safe(self.output_name) if self.output_name.strip() else TEXT_STEM})"

    def fingerprint(self) -> tuple:
        """Everything that decides what comes out the other end. Two requests
        with the same fingerprint generate the same video (bar a random seed),
        so queueing both just spends the GPU time twice."""
        return (
            str(self.workflow_path).lower(),
            str(self.source_path or "").lower(),
            self.source_kind,
            tuple(sorted((k, v) for k, v in self.prompts.items())),
            tuple(sorted((k, repr(v)) for k, v in self.lora_edits.items())),
            self.seed,
            self.length_value,
            self.steps,
            self.megapixels,
            self.video_input_mode,
            self.extend_stitch,
            self.turbo_enabled,
            str(self.output_dir_override or ""),
            self.output_name.strip().lower(),
        )

    def describe(self) -> str:
        """One line for logs and the duplicate warning."""
        bits = [self.tab_label, self.workflow_label, self.source_name]
        if self.settings_summary:
            bits.append(self.settings_summary)
        return "  |  ".join(bits)


class RunWorker(QThread):
    log = pyqtSignal(str)
    plan = pyqtSignal(int, int)          # total sampler steps, post-sampler phases
    step = pyqtSignal(int, int)          # value, max (one sampler pass)
    phase = pyqtSignal(str)              # a post-sampler phase started
    finished_ok = pyqtSignal(list, dict) # list[str] of local output paths, timing (see run_timing)
    failed = pyqtSignal(str)

    def __init__(self, config: dict, req: RunRequest):
        super().__init__()
        self._cfg = config
        self._req = req
        self._cancelled = False
        self._prompt_id = ""
        self._runpod = config.get("mode", "local") == "runpod"
        url = config.get("runpod_url", "") if self._runpod else config.get("comfyui_url", "")
        self._client = ComfyClient((url or "").strip(), log=self._log)
        self._base_dir = Path(config.get("_base_dir", str(Path(__file__).parent)))
        self._temp_dir = self._base_dir / "temp"
        self._run_id = time.strftime("%Y%m%d_%H%M%S")
        self._ffmpeg = resolve_ffmpeg(config.get("ffmpeg_path", ""), self._base_dir)

        log_path = self._base_dir / RUN_LOG_NAME
        _trim_log(log_path, keep=50)
        fh = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
        logger.handlers.clear()
        logger.addHandler(fh)

    # ------------------------------------------------------------------ #

    def cancel(self):
        self._cancelled = True
        # Stop it on the server too — otherwise the prompt keeps running
        # (and keeps billing on RunPod) after the UI says cancelled.
        threading.Thread(target=self._client.interrupt, args=(self._prompt_id,), daemon=True).start()

    def _log(self, msg: str):
        self.log.emit(msg)
        logger.info(msg)

    def _check_cancel(self):
        if self._cancelled:
            raise _Cancelled()

    # ------------------------------------------------------------------ #

    def run(self):
        req = self._req
        try:
            logger.info(RUN_DELIM)
            t0 = time.time()
            if not self._client.url:
                raise RuntimeError("No server URL configured for the selected mode — open Settings.")
            self._temp_dir.mkdir(exist_ok=True)
            self._log(f"Server: {self._client.url} ({'RunPod' if self._runpod else 'Local'})")
            self._log(f"Workflow: {req.workflow_label}")
            if req.source_path is not None:
                self._log(f"Source {req.source_kind}: {req.source_path.name}")
            else:
                self._log("Source: none — text to video, the prompt is the whole input")

            workflow = load_workflow(req.workflow_path)
            info = analyze(workflow)

            # Text / seed / length edits
            if req.prompts:
                apply_inputs(workflow, req.prompts)
            if req.lora_edits:
                apply_inputs(workflow, req.lora_edits)
            for slot in analyze(workflow).loras:
                if slot.name and slot.name != "None":
                    strengths = ", ".join(f"{v:g}" for v in slot.strengths.values()) or "-"
                    self._log(f"LoRA {slot.label}: {slot.name} ({strengths})")
            seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
            n_seed = apply_seed(workflow, seed)
            if n_seed:
                self._log(f"Seed: {seed} ({n_seed} field{'s' if n_seed != 1 else ''})")
            if req.length_field is not None and req.length_value is not None:
                apply_value(workflow, req.length_field, req.length_value)
                self._log(f"{req.length_field.label}: {req.length_value:g}")
            if req.steps is not None and info.steps_fields:
                n_steps = apply_steps(workflow, info.steps_fields, req.steps)
                self._log(f"Steps: {req.steps} ({n_steps} sampler node{'s' if n_steps != 1 else ''})")
            if req.turbo_enabled is not None and info.turbo is not None:
                apply_turbo_toggle(workflow, info.turbo, req.turbo_enabled)
                self._log(f"Turbo LoRA + Sampler: {'on' if req.turbo_enabled else 'off'}")
            src = probe(self._ffmpeg, req.source_path) if req.source_kind == "video" and req.source_path else None
            if src is not None and src.width:
                self._log(
                    f"Source: {src.width}x{src.height} {src.fps:g}fps {src.vcodec or 'unknown codec'}"
                    f"{'' if src.has_audio else ' (no audio)'}"
                )
            mp_value = req.megapixels
            if req.source_kind == "video" and req.extend_stitch and info.mp_fields:
                # The new clip gets appended to this video, so generate it at the
                # source's own frame size instead of the megapixels box's value.
                if src is not None and src.width and src.height:
                    matched = round(src.width * src.height / (1024 * 1024), 3)
                    if mp_value is None or abs(matched - mp_value) > 0.005:
                        was = f"{mp_value:g}" if mp_value is not None else "the workflow's value"
                        self._log(
                            f"Appending — matching the source's {src.width}x{src.height}: "
                            f"megapixels {matched:g} (was {was})"
                        )
                    mp_value = matched
            if mp_value is not None and info.mp_fields:
                n_mp = apply_megapixels(workflow, info.mp_fields, mp_value)
                self._log(f"Megapixels: {mp_value:g} ({n_mp} node{'s' if n_mp != 1 else ''})")
            if src is not None:
                self._check_output_format(workflow, src, req)
            # Re-read the patched graph so the progress plan matches what runs
            info = analyze(workflow)

            # Feed the source into the graph
            if req.source_kind == "image":
                if not info.accepts_image:
                    raise RuntimeError(
                        "This workflow has no image input (LoadImage or Load Image List From Dir). "
                        "Pick an image-to-video workflow for this tab."
                    )
                self._feed_image(workflow, info, req.source_path)
            elif req.source_kind == "video":
                self._feed_video(workflow, info, req.source_path)
            else:
                # Text → Video: nothing to upload. A workflow with an image or
                # video loader would run against whatever file name is baked
                # into that node — usually one the server doesn't have — and
                # wouldn't be text-to-video anyway, so it's refused up front.
                if info.accepts_image or info.accepts_video:
                    raise RuntimeError(
                        "This workflow takes an image or video input, so it isn't text-to-video. "
                        "Pick a workflow with no LoadImage / LoadVideo node for this tab (the "
                        "Image → Video and Video → Extend tabs run the ones that need a source)."
                    )
                if not info.prompts:
                    raise RuntimeError(
                        "This workflow exposes no prompt text — with no image either, there is "
                        "nothing to generate from.")
            self._check_cancel()

            # Route outputs into a run-specific folder on the server so the
            # history lookup can't confuse them with older files.
            stem = self._output_stem(req)
            set_output_prefix(workflow, f"VideoCreator/{self._run_id}/{stem}")

            self.plan.emit(sum(info.sampler_steps), info.post_phases)
            steps = StepTimer(sampler_nodes(workflow))
            self._log("Queuing workflow...")
            t_render = time.time()
            self._prompt_id = self._client.queue(workflow)
            self._log(f"Queued ({self._prompt_id[:8]}...) — waiting for ComfyUI")

            self._client.wait(
                self._prompt_id, workflow,
                on_step=lambda v, m, node="": (steps.on_step(v, m, node), self.step.emit(v, m)),
                on_phase=self._on_phase,
                cancelled=lambda: self._cancelled,
            )
            self._check_cancel()
            render_seconds = time.time() - t_render

            if self._runpod:
                time.sleep(3)  # let the proxy catch up with the written file
            outputs = self._download_outputs(info, req)
            self._check_cancel()

            results = [str(p) for p in outputs]
            if req.source_kind == "video" and req.extend_stitch and outputs:
                stitched = self._stitch_extension(req.source_path, outputs[0], req)
                results.append(str(stitched))

            timing = run_timing(time.time() - t0, render_seconds, steps.result())
            done = f"Done in {_fmt(timing['run_seconds'])} (render {_fmt(timing['render_seconds'])}"
            if "step_seconds" in timing:
                done += f", {timing['sampler_steps']} steps @ {timing['step_seconds']:.2f} s/step"
            self._log(done + ")")
            self.finished_ok.emit(results, timing)
        except _Cancelled:
            self._log("Cancelled.")
            self.failed.emit("Cancelled")
        except Exception as e:  # noqa: BLE001
            logger.exception("Run failed")
            self.failed.emit(str(e))

    # ------------------------------------------------------------------ #
    # Input handling
    # ------------------------------------------------------------------ #

    def _feed_image(self, workflow: dict, info, image_path: Path):
        if info.image_nodes:
            nid, title = info.image_nodes[0]
            self._log(f"Uploading image {image_path.name}...")
            name = self._client.upload(image_path, subfolder="VideoCreator")
            workflow[nid]["inputs"]["image"] = name
            self._log(f"Image → node {nid} ({title or 'Load Image'}) as {name}")
            if len(info.image_nodes) > 1:
                others = ", ".join(i for i, _ in info.image_nodes[1:])
                self._log(f"Note: other LoadImage nodes ({others}) keep the image saved in the workflow")
            return

        # Folder-loader workflow (batch style): stage the single image in a
        # fresh run folder and point the loader's directory at it.
        nid, title = info.list_loaders[0]
        if self._runpod:
            sub = f"VideoCreator/{self._run_id}"
            self._log(f"Uploading image {image_path.name} to {sub}/ ...")
            self._client.upload(image_path, subfolder=sub)
            input_root = (self._cfg.get("runpod_input_dir", "") or "/workspace/runpod-slim/ComfyUI/input").rstrip("/")
            directory = f"{input_root}/{sub}"
        else:
            root = (self._cfg.get("staging_dir_local", "") or "").strip()
            stage = Path(root) if root else self._temp_dir / "staging"
            stage = stage / "VideoCreator" / self._run_id
            stage.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path, stage / image_path.name)
            directory = str(stage)
            self._log(f"Staged image in {directory}")
        workflow[nid]["inputs"]["directory"] = directory
        for key in ("image_load_cap", "start_index"):
            if key in workflow[nid]["inputs"]:
                workflow[nid]["inputs"][key] = 0
        self._log(f"Folder → node {nid} ({title or 'Load Image List From Dir'})")

    def _feed_video(self, workflow: dict, info, video_path: Path):
        mode = self._req.video_input_mode
        if mode == "auto":
            if info.video_nodes:
                mode = "upload_video"
            elif info.accepts_image:
                mode = "last_frame"
            else:
                raise RuntimeError(
                    "This workflow has neither a video input (LoadVideo / VHS_LoadVideo) nor an "
                    "image input (LoadImage). Pick a workflow that can take the selected video or its last frame."
                )

        if mode == "upload_video":
            if not info.video_nodes:
                raise RuntimeError(
                    "Input mode is 'Upload video' but this workflow has no LoadVideo / VHS_LoadVideo node. "
                    "Switch the input mode to 'Last frame → image' or pick a video-input workflow."
                )
            nid, title, key = info.video_nodes[0]
            self._log(f"Uploading video {video_path.name} ({video_path.stat().st_size // 1024} KB)...")
            name = self._client.upload(video_path, subfolder="VideoCreator")
            workflow[nid]["inputs"][key] = name
            self._log(f"Video → node {nid} ({title or 'Load Video'}) as {name}")
            return

        # last_frame
        if not info.accepts_image:
            raise RuntimeError(
                "Input mode is 'Last frame → image' but this workflow has no LoadImage / folder loader node."
            )
        frame = self._temp_dir / f"{_safe(video_path.stem)}_lastframe_{self._run_id}.png"
        self._log(f"Extracting last frame of {video_path.name}...")
        extract_last_frame(self._ffmpeg, video_path, frame)
        self._feed_image(workflow, info, frame)

    def _check_output_format(self, workflow: dict, src, req: RunRequest) -> None:
        """The extension should be written in the same codec as the video it
        extends. Retune the graph about to run when the clip gets appended,
        otherwise just say what the mismatch is."""
        if not src.vcodec:
            return
        for fmt in output_formats(workflow):
            if not fmt.codec or fmt.codec == src.vcodec:
                continue
            node = workflow.get(fmt.node_id, {})
            allowed = self._client.list_options(node.get("class_type", ""), fmt.key)
            target = match_format_value(fmt.value, src.vcodec, allowed)
            if req.extend_stitch and target:
                apply_output_format(workflow, fmt, target)
                self._log(
                    f"Output format: {fmt.value} -> {target} to match the source video ({src.vcodec})"
                )
            elif req.extend_stitch:
                self._log(
                    f"WARNING: this workflow saves {fmt.codec} ({fmt.value}) but the source video is "
                    f"{src.vcodec}, and the server offers no {src.vcodec} option for {fmt.label} — "
                    f"the appended file will be re-encoded."
                )
            else:
                self._log(
                    f"Note: this workflow saves {fmt.codec} ({fmt.value}); the source video is {src.vcodec}."
                )
        if src.fps:
            for nid, node in workflow.items():
                if not isinstance(node, dict) or node.get("class_type") not in ("VHS_VideoCombine",):
                    continue
                rate = (node.get("inputs") or {}).get("frame_rate")
                if isinstance(rate, (int, float)) and abs(float(rate) - src.fps) > 0.01:
                    self._log(
                        f"Note: this workflow saves at {float(rate):g} fps, the source video is "
                        f"{src.fps:g} fps — the appended clip gets resampled to {src.fps:g}."
                    )

    def _on_phase(self, label: str):
        self._log(label)
        self.phase.emit(label)

    # ------------------------------------------------------------------ #
    # Outputs
    # ------------------------------------------------------------------ #

    def _download_outputs(self, info, req: RunRequest) -> list[Path]:
        history = self._client.history(self._prompt_id)
        files = self._client.collect_outputs(history, info.output_nodes)
        if not files:
            raise RuntimeError(
                "ComfyUI finished but reported no output file. Make sure the workflow ends in a "
                "SaveVideo or VHS_VideoCombine node (Preview nodes don't write files)."
            )
        out_dir = req.output_dir_override or Path(
            (self._cfg.get("output_dir", "") or "").strip() or (self._base_dir / "output"))
        if req.output_dir_override is None and self._cfg.get("output_per_workflow", True):
            # Each workflow keeps its videos in its own Library folder
            out_dir = library_dir_for(out_dir, workflow_rel_of(req.workflow_path, self._cfg.get("workflow_dir", "")))
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = self._output_stem(req)
        label = _safe(req.workflow_label)
        results: list[Path] = []
        cleaner = OutputCleaner(self._cfg, self._log) if self._runpod and cleanup_enabled(self._cfg) else None
        for idx, f in enumerate(files, 1):
            ext = Path(f["filename"]).suffix or ".mp4"
            suffix = f"_{idx}" if len(files) > 1 else ""
            mark = f"_{EXT_MARK}" if req.source_kind == "video" else ""
            dest = out_dir / _fit_name(out_dir, stem, f"_{label}{mark}_{self._run_id}{suffix}{ext}")
            self._log(f"Downloading {f['filename']} → {dest.name}")
            self._client.download(f, dest)
            results.append(dest)
            self._log(f"Saved {dest.name} ({dest.stat().st_size // 1024} KB)")
            if cleaner:
                cleaner.delete_if_downloaded(f, dest)
        return results

    def _output_stem(self, req: RunRequest) -> str:
        """What a result file is named after. Video sources shed the workflow
        and stamp a previous run appended, so a chain of extensions keeps one
        stable base name instead of growing past what Windows allows. A
        text-to-video run has no source, so it takes the name typed on the
        tab, or a plain marker when that's blank."""
        if req.source_path is None:
            return _safe(req.output_name) if req.output_name.strip() else TEXT_STEM
        if req.source_kind != "video":
            return _safe(req.source_path.stem)
        return _base_stem(req.source_path.stem, _workflow_labels(self._cfg.get("workflow_dir", "")))

    def _stitch_extension(self, source: Path, clip: Path, req: RunRequest) -> Path:
        out_dir = clip.parent
        dest = out_dir / _fit_name(out_dir, self._output_stem(req), f"_extended_{self._run_id}.mp4")
        self._log(f"Appending new clip to {source.name} → {dest.name}")
        concat_videos(self._ffmpeg, [source, clip], dest)
        self._log(f"Extended video saved ({dest.stat().st_size // 1024} KB)")
        return dest


class _Cancelled(Exception):
    pass


_STAMP_RE = re.compile(r"_\d{8}_\d{6}$")

# Longest full path we will write. Windows refuses at 260.
MAX_PATH = 250

# Marks a clip produced from a video source, i.e. an extension.
EXT_MARK = "EXT"

# Base name of a text-to-video clip when no output name was typed.
TEXT_STEM = "T2V"

TAB_LABELS = {"image": "Image → Video", "video": "Video → Extend", "text": "Text → Video"}


def _workflow_labels(workflow_dir: str) -> list[str]:
    """Every label the app puts in an output name: a workflow's subfolder when
    it lives in one, otherwise its file stem."""
    try:
        rels = list_workflows(Path((workflow_dir or "").strip()))
    except Exception:  # noqa: BLE001
        return []
    labels = set()
    for rel in rels:
        parts = Path(rel).parts
        labels.add(parts[0] if len(parts) > 1 else Path(rel).stem)
    # longest first so "Video_Kiss_A" never matches inside "Video_Kiss_A_Long"
    return sorted(labels, key=len, reverse=True)


def _base_stem(stem: str, labels: list[str], passes: int = 4) -> str:
    """Strip what earlier runs appended, so extending an extension doesn't
    grow the name every pass: both `<base>_<workflow>_<stamp>` and
    `<base>_extended_<stamp>` come back as `<base>`."""
    out = _safe(stem)
    for _ in range(passes):
        trimmed = _STAMP_RE.sub("", out)
        if trimmed == out:
            break
        ours = False
        mark = "_" + EXT_MARK.lower()
        if trimmed.lower().endswith(mark) and len(trimmed) > len(mark):
            trimmed = trimmed[: -len(mark)]
            ours = True
        low = trimmed.lower()
        for tail in ["extended"] + labels:
            t = "_" + _safe(tail).lower()
            if low.endswith(t) and len(trimmed) > len(t):
                trimmed = trimmed[: -len(t)]
                ours = True
                break
        if not ours:
            # A stamp with nothing of ours in front of it belongs to the file
            # itself (a camera name like IMG_20260101_120000) — keep it.
            break
        out = trimmed
    return out or "video"


def _fit_name(out_dir: Path, stem: str, tail: str) -> str:
    """`stem + tail`, with the stem shortened if the whole path would be too
    long for Windows. The tail (workflow, stamp, extension) is never cut."""
    room = MAX_PATH - len(str(out_dir)) - 1 - len(tail)
    if len(stem) > max(room, 8):
        stem = stem[: max(room, 8)].rstrip("_")
    return stem + tail


def _safe(name: str) -> str:
    keep = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name.strip())
    # Collapse runs of dots. ComfyUI's /view endpoint rejects ANY filename
    # containing ".." with a 400 before it even looks for the file — its
    # directory-traversal guard — so a source called "Married... with Children"
    # generates fine on the server and is then impossible to download.
    # Single dots are fine; only consecutive ones are refused.
    keep = re.sub(r"\.{2,}", ".", keep)
    # Leading/trailing dots go too: Windows silently drops a trailing dot when
    # saving, which would leave the local name disagreeing with the one the pod
    # reported, and a leading dot makes a hidden file.
    keep = keep.strip("_.")
    return keep or "video"


def run_timing(run_seconds: float, render_seconds: float, steps: dict | None = None) -> dict:
    """What a finished run reports about how long it took, in the shape
    the history entry stores: ``run_seconds`` is the whole run from Create
    to the file on disk (upload, queue wait, render, download, stitch);
    ``render_seconds`` is the ComfyUI part alone, queued to finished; the
    sampler keys from ``StepTimer.result()`` ride along when there are any."""
    timing = {"run_seconds": round(run_seconds, 1), "render_seconds": round(render_seconds, 1)}
    timing.update(steps or {})
    return timing


def sampler_nodes(workflow: dict) -> set[str]:
    """Ids of the nodes whose progress events are denoising steps: any
    sampler class (KSampler, KSamplerAdvanced, SamplerCustomAdvanced, the
    WAN wrappers...). Progress from anything else — tiled VAE decode,
    an API node polling its job — is not a step and must not be timed."""
    return {nid for nid, node in workflow.items()
            if isinstance(node, dict) and "sampler" in str(node.get("class_type", "")).lower()}


class StepTimer:
    """Times the sampler from ComfyUI's per-step progress events.

    A step is the gap between two consecutive progress events from the
    same sampler node with the value up by one. The first event of a pass
    has no gap to measure (the time before it holds the model load), so
    an N-step pass yields N-1 gaps; the step COUNT is still N (the highest
    value each sampler reported, summed over samplers, so a WAN hi/lo
    split counts both halves). Events from nodes outside ``nodes`` are
    ignored; an event with no node id (older servers) is taken as-is."""

    def __init__(self, nodes: set[str], clock=time.time):
        self._nodes = nodes
        self._clock = clock
        self._last: tuple[str, int, float] | None = None
        self._gaps: list[float] = []
        self._steps: dict[str, int] = {}

    def on_step(self, value: int, _vmax: int, node: str = "") -> None:
        if node and node not in self._nodes:
            self._last = None
            return
        now = self._clock()
        if self._last is not None and self._last[0] == node and value == self._last[1] + 1:
            self._gaps.append(now - self._last[2])
        self._last = (node, value, now)
        self._steps[node] = max(self._steps.get(node, 0), value)

    def result(self) -> dict:
        """``sampler_steps`` (count), ``step_seconds`` (average per step)
        and ``sampler_seconds`` (steps x average — the estimated time the
        run spent denoising); {} when nothing was timed."""
        if not self._gaps:
            return {}
        avg = sum(self._gaps) / len(self._gaps)
        total = sum(self._steps.values())
        return {"sampler_steps": total, "step_seconds": round(avg, 2),
                "sampler_seconds": round(avg * total, 1)}


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}m {s:02d}s"


def _trim_log(log_path: Path, keep: int):
    if not log_path.exists():
        return
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return
    runs = [p for p in text.split(RUN_DELIM)[1:] if p.strip()]
    if len(runs) >= keep:
        trimmed = RUN_DELIM.join([""] + runs[-(keep - 1):])
        try:
            log_path.write_text(trimmed.lstrip("\n"), encoding="utf-8")
        except OSError:
            pass
