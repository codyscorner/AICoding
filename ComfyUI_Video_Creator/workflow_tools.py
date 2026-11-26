"""Inspect and patch ComfyUI API-format workflow JSON.

Everything the app needs to know about a workflow before running it:
which node takes the starting image (or a whole folder, or a video),
which text fields are prompts, where the seed lives, which node writes
the video, and how many sampler steps to expect for the progress bar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_NODE_TYPES = {"LoadImage": "image"}
LIST_LOADER_TYPES = {
    "LoadImageListFromDir //Inspire": "directory",
    "LoadImagesFromDir //Inspire": "directory",
}
VIDEO_NODE_TYPES = {"LoadVideo": "file", "VHS_LoadVideo": "video"}
VIDEO_OUTPUT_TYPES = {"VHS_VideoCombine", "SaveVideo"}
IMAGE_OUTPUT_TYPES = {"SaveImage", "SaveAnimatedWEBP", "SaveAnimatedPNG"}

# Post-sampling nodes that produce no step-level progress events — each
# counts as one extra unit on the progress bar so it doesn't sit at 100%
# while the VAE decode / encode / save stretch is still running.
STATUS_NODE_LABELS = {
    "VAEDecode": "Decoding video (VAE)...",
    "VAEDecodeAudio": "Decoding audio (VAE)...",
    "CreateVideo": "Encoding video...",
    "SaveVideo": "Saving video...",
    "VHS_VideoCombine": "Saving video...",
}

HISTORY_SUFFIX = ".prompt_history.json"
FAVORITES_SUFFIX = ".prompt_favorites.json"
# Sidecar files this app writes next to a workflow. They are JSON but not
# workflows, so the scanner and the workflow dropdown must never list them.
SIDECAR_SUFFIXES = (HISTORY_SUFFIX, FAVORITES_SUFFIX)

LORA_EXTS = {".safetensors", ".pt", ".pt2", ".bin", ".pth", ".ckpt", ".pkl", ".sft"}
_LORA_KEY_RE = re.compile(r"^lora(_name|_\d+)$")


class WorkflowError(Exception):
    pass


@dataclass
class PromptField:
    node_id: str
    key: str
    label: str
    negative: bool = False
    text: str = ""


@dataclass
class ValueField:
    node_id: str
    key: str
    label: str
    kind: str          # "int" | "float"
    value: float


@dataclass
class LoraSlot:
    """One selectable LoRA in the workflow: a name input plus its strength
    input(s). `LoraLoaderModelOnly` has lora_name/strength_model, rgthree's
    stack has lora_01..lora_NN with strength_NN, MiniMax H3 Turbo has
    lora_name/strength."""
    node_id: str
    name_key: str
    label: str
    name: str
    strengths: dict[str, float] = field(default_factory=dict)   # strength key -> value
    allow_none: bool = False

    def strength_label(self, key: str) -> str:
        return {"strength_model": "Model", "strength_clip": "CLIP"}.get(key, "")


@dataclass
class StepsField:
    """A sampler/scheduler node's `steps` input. WAN 2.2 hi/lo pairs are two
    KSamplerAdvanced nodes sharing one step count and splitting it with
    start_at_step / end_at_step — those boundaries are rescaled when the
    count changes so the split point stays proportional."""
    node_id: str
    label: str
    value: int
    start: int | None = None
    end: int | None = None


@dataclass
class TurboToggle:
    """A MiniMax H3 Turbo LoRA + Turbo Sampler pair detected in the graph,
    alongside the standard (non-turbo) model link / KSamplerSelect node they
    can be swapped for. Detected structurally so it works regardless of
    whether the workflow file currently has turbo wired in or bypassed —
    see `_detect_turbo_toggle`."""
    lora_id: str
    sampler_id: str
    standard_sampler_id: str
    base_model_link: list                       # the turbo LoRA's own `model` input, i.e. the bypass target
    lora_consumers: list[tuple[str, str]]        # (node_id, input_key) whose `model` input toggles
    sampler_consumers: list[tuple[str, str]]     # (node_id, input_key) whose `sampler` input toggles
    currently_on: bool


@dataclass
class Analysis:
    image_nodes: list[tuple[str, str]] = field(default_factory=list)          # (id, title)
    list_loaders: list[tuple[str, str]] = field(default_factory=list)         # (id, title)
    video_nodes: list[tuple[str, str, str]] = field(default_factory=list)     # (id, title, input key)
    prompts: list[PromptField] = field(default_factory=list)
    loras: list[LoraSlot] = field(default_factory=list)
    steps_fields: list[StepsField] = field(default_factory=list)
    mp_fields: list[ValueField] = field(default_factory=list)      # numeric `megapixels` inputs
    seed_fields: list[tuple[str, str]] = field(default_factory=list)          # (id, key)
    length_field: ValueField | None = None
    output_nodes: list[str] = field(default_factory=list)
    image_output_nodes: list[str] = field(default_factory=list)
    sampler_steps: list[int] = field(default_factory=list)
    post_phases: int = 0
    minimax_mode: str | None = None     # "T2VA" | "I2VA" | "FL2VA" | "L2VA" | "Ref2VA"
    aspect_ratio: str = "16:9"          # best-effort, read from a ResolutionSelector node
    turbo: TurboToggle | None = None

    @property
    def accepts_image(self) -> bool:
        return bool(self.image_nodes or self.list_loaders)

    @property
    def accepts_video(self) -> bool:
        return bool(self.video_nodes)

    def describe(self) -> str:
        parts = []
        if self.image_nodes:
            parts.append("image input: " + ", ".join(t or i for i, t in self.image_nodes))
        if self.list_loaders:
            parts.append("folder loader (the single image is staged into a run folder)")
        if self.video_nodes:
            parts.append("video input: " + ", ".join(t or i for i, t, _ in self.video_nodes))
        if not parts:
            parts.append("no image or video input node found")
        outs = len(self.output_nodes)
        if outs:
            parts.append(f"{outs} video output node" + ("s" if outs != 1 else ""))
        else:
            parts.append("no video output node (SaveVideo / VHS_VideoCombine)")
        return " · ".join(parts)


# --------------------------------------------------------------------- #
# Loading / listing
# --------------------------------------------------------------------- #

def is_api_format(data) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    nodes = [v for v in data.values() if isinstance(v, dict)]
    return bool(nodes) and all("class_type" in v for v in nodes)


def load_workflow(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise WorkflowError(f"{path.name}: not valid JSON ({e})") from e
    except OSError as e:
        raise WorkflowError(f"{path.name}: cannot read file ({e})") from e
    if isinstance(data, dict) and "nodes" in data and "links" in data:
        raise WorkflowError(
            f"{path.name} is a UI-format workflow (the kind ComfyUI saves with Ctrl+S). "
            "The API needs the API export: in ComfyUI use Workflow > Export (API) and pick that file."
        )
    if not is_api_format(data):
        raise WorkflowError(
            f"{path.name}: not a ComfyUI API-format workflow (expected a JSON object of node-id -> node)."
        )
    return data


INVALID_NAME_CHARS = r'<>:"/\|?*'
_RESERVED_NAMES = {"con", "prn", "aux", "nul",
                   *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def check_workflow_name(name: str) -> str:
    """Return an error message for a proposed workflow file name, or "" if it's fine."""
    stem = name.strip()
    if stem.lower().endswith(".json"):
        stem = stem[:-5].strip()
    if not stem:
        return "Enter a name."
    bad = sorted({c for c in stem if c in INVALID_NAME_CHARS or ord(c) < 32})
    if bad:
        return "A file name cannot contain " + " ".join(bad)
    if stem.endswith(".") or stem.endswith(" "):
        return "A file name cannot end with a dot or a space."
    if stem.split(".")[0].lower() in _RESERVED_NAMES:
        return f'"{stem}" is a name Windows reserves.'
    if stem.lower().endswith(tuple(sfx[:-5] for sfx in SIDECAR_SUFFIXES)):
        return "That name collides with the prompt-history / favorites file naming."
    return ""


def workflow_stem(name: str) -> str:
    """The file stem for a name typed by the user (a typed .json is not doubled up)."""
    stem = name.strip()
    if stem.lower().endswith(".json"):
        stem = stem[:-5].strip()
    return stem


def unique_workflow_path(folder: Path, stem: str) -> Path:
    """`folder/stem.json`, or `stem (2).json`, `stem (3).json`… if that is taken."""
    candidate = folder / f"{stem}.json"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}).json"
        n += 1
    return candidate


def list_workflow_folders(workflow_dir: Path) -> list[str]:
    """Relative POSIX paths of the workflow folder and every subfolder ("" = root)."""
    if not workflow_dir or not workflow_dir.is_dir():
        return []
    out = [""]
    for p in sorted(workflow_dir.rglob("*"), key=lambda p: str(p).lower()):
        if not p.is_dir():
            continue
        rel = p.relative_to(workflow_dir)
        if any(part.lower() == "thumbnails" for part in rel.parts):
            continue
        out.append(rel.as_posix())
    return out


def list_workflows(workflow_dir: Path) -> list[str]:
    """Relative POSIX paths of every candidate workflow JSON under the folder."""
    if not workflow_dir or not workflow_dir.is_dir():
        return []
    out = []
    for p in sorted(workflow_dir.rglob("*.json"), key=lambda p: str(p).lower()):
        if p.name.lower().endswith(SIDECAR_SUFFIXES):
            continue
        if any(part.lower() == "thumbnails" for part in p.relative_to(workflow_dir).parts):
            continue
        out.append(p.relative_to(workflow_dir).as_posix())
    return out


# --------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------- #

def _title(node: dict) -> str:
    return (node.get("_meta") or {}).get("title") or ""


def _sort_key(nid: str):
    # "105:104" style ids from subgraphs sort after plain ints
    try:
        return (0, int(nid), "")
    except ValueError:
        return (1, 0, nid)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def analyze(workflow: dict) -> Analysis:
    a = Analysis()
    positives: list[PromptField] = []
    negatives: list[PromptField] = []
    duration: ValueField | None = None
    length_int: ValueField | None = None

    for nid in sorted(workflow.keys(), key=_sort_key):
        node = workflow[nid]
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        title = _title(node)
        inp = node.get("inputs", {}) or {}

        if ct in IMAGE_NODE_TYPES:
            a.image_nodes.append((nid, title))
        elif ct in LIST_LOADER_TYPES:
            a.list_loaders.append((nid, title))
        elif ct in VIDEO_NODE_TYPES:
            a.video_nodes.append((nid, title, VIDEO_NODE_TYPES[ct]))

        if ct in VIDEO_OUTPUT_TYPES:
            a.output_nodes.append(nid)
        elif ct in IMAGE_OUTPUT_TYPES:
            a.image_output_nodes.append(nid)

        # Prompts ------------------------------------------------------
        if ct == "CLIPTextEncode" and isinstance(inp.get("text"), str):
            neg = "neg" in title.lower()
            label = title or ("Negative Prompt" if neg else "Positive Prompt")
            (negatives if neg else positives).append(PromptField(nid, "text", label, neg, inp["text"]))
        elif ct.startswith("MiniMaxH3") and isinstance(inp.get("prompt"), str):
            positives.append(PromptField(nid, "prompt", title or "MiniMax H3 Prompt", False, inp["prompt"]))
        elif ct == "PrimitiveStringMultiline" and isinstance(inp.get("value"), str):
            neg = "neg" in title.lower()
            (negatives if neg else positives).append(PromptField(nid, "value", title or "Text", neg, inp["value"]))

        # MiniMax H3 mode, for the optional AI prompt rewriter ----------
        if ct == "MiniMaxH3ReferenceToVideo":
            a.minimax_mode = "Ref2VA"
        elif ct == "MiniMaxH3ImageToVideo":
            has_first = inp.get("first_frame") is not None
            has_last = inp.get("last_frame") is not None
            if has_first and has_last:
                a.minimax_mode = "FL2VA"
            elif has_first:
                a.minimax_mode = "I2VA"
            elif has_last:
                a.minimax_mode = "L2VA"
            else:
                a.minimax_mode = "T2VA"

        # Aspect ratio, best-effort (feeds the rewriter's resolution field)
        if ct == "ResolutionSelector" and isinstance(inp.get("aspect_ratio"), str):
            m = re.match(r"\s*(\d+:\d+)", inp["aspect_ratio"])
            if m:
                a.aspect_ratio = m.group(1)

        # LoRAs --------------------------------------------------------
        if "lora" in ct.lower():
            for key, val in inp.items():
                if not (isinstance(val, str) and _LORA_KEY_RE.match(key)):
                    continue
                if key == "lora_name":
                    cand = ["strength_model", "strength_clip", "strength"]
                    slot_label = title or ct
                else:
                    cand = [key.replace("lora_", "strength_")]
                    slot_label = f"{title or 'LoRA Stack'} #{key.split('_')[1]}"
                strengths = {
                    k: float(inp[k]) for k in cand
                    if isinstance(inp.get(k), (int, float)) and not isinstance(inp.get(k), bool)
                }
                a.loras.append(LoraSlot(nid, key, slot_label, val, strengths, allow_none=(key != "lora_name")))

        # Seeds --------------------------------------------------------
        for key in ("noise_seed", "seed"):
            if _is_int(inp.get(key)):
                a.seed_fields.append((nid, key))

        # Length / duration -------------------------------------------
        if ct == "PrimitiveFloat" and "duration" in title.lower() and isinstance(inp.get("value"), (int, float)):
            if duration is None:
                duration = ValueField(nid, "value", "Duration (seconds)", "float", float(inp["value"]))
        elif ct in ("WanImageToVideo", "EmptyMiniMaxH3LatentAV", "MiniMaxH3ImageToVideo",
                    "MiniMaxH3ReferenceToVideo", "EmptyHunyuanLatentVideo") and _is_int(inp.get("length")):
            if length_int is None:
                length_int = ValueField(nid, "length", "Length (frames)", "int", int(inp["length"]))

        # Megapixels (ImageScaleToTotalPixels, ResolutionSelector, ...) --
        mp = inp.get("megapixels")
        if isinstance(mp, (int, float)) and not isinstance(mp, bool):
            fld = ValueField(nid, "megapixels", title or ct, "float", float(mp))
            # The scale node is what actually sizes the frames — list it first
            # so the control shows its value (a ResolutionSelector may differ).
            if ct == "ImageScaleToTotalPixels":
                a.mp_fields.insert(0, fld)
            else:
                a.mp_fields.append(fld)

        # Sampler steps -----------------------------------------------
        if "sampler" in ct.lower() or ct == "BasicScheduler":
            steps = inp.get("steps")
            if _is_int(steps) and steps > 0:
                start, end = inp.get("start_at_step"), inp.get("end_at_step")
                a.steps_fields.append(StepsField(
                    nid, title or ct, steps,
                    start if _is_int(start) else None, end if _is_int(end) else None))
                if _is_int(start) and _is_int(end):
                    steps = max(0, min(end, steps) - max(start, 0))
                if steps:
                    a.sampler_steps.append(steps)
        if ct in STATUS_NODE_LABELS:
            a.post_phases += 1

    a.prompts = positives + negatives
    a.length_field = duration or length_int
    a.turbo = _detect_turbo_toggle(workflow)
    return a


def _detect_turbo_toggle(workflow: dict) -> TurboToggle | None:
    """Finds a MiniMax H3 Turbo LoRA + Turbo Sampler pair and the standard
    (non-turbo) alternatives they can be swapped for, by structure rather
    than by current wiring — so this works whether the file currently has
    turbo on or bypassed. Returns None unless every piece needed to safely
    toggle both directions is present."""
    lora_id = sampler_id = standard_sampler_id = None
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        if ct == "MiniMaxH3TurboLoRA":
            lora_id = nid
        elif ct == "MiniMaxH3TurboSampler":
            sampler_id = nid
        elif ct == "KSamplerSelect":
            standard_sampler_id = nid
    if lora_id is None or sampler_id is None or standard_sampler_id is None:
        return None
    base_model_link = workflow[lora_id].get("inputs", {}).get("model")
    if not (isinstance(base_model_link, list) and len(base_model_link) == 2):
        return None

    lora_consumers: list[tuple[str, str]] = []
    sampler_consumers: list[tuple[str, str]] = []
    lora_on = sampler_on = False
    for nid, node in workflow.items():
        if nid == lora_id or not isinstance(node, dict):
            continue
        for key, val in node.get("inputs", {}).items():
            if not (isinstance(val, list) and len(val) == 2):
                continue
            if val == [lora_id, 0]:
                lora_consumers.append((nid, key))
                lora_on = True
            elif val == base_model_link:
                lora_consumers.append((nid, key))
            elif val == [sampler_id, 0]:
                sampler_consumers.append((nid, key))
                sampler_on = True
            elif val == [standard_sampler_id, 0]:
                sampler_consumers.append((nid, key))
    if not lora_consumers or not sampler_consumers:
        return None
    return TurboToggle(
        lora_id=lora_id, sampler_id=sampler_id, standard_sampler_id=standard_sampler_id,
        base_model_link=base_model_link, lora_consumers=lora_consumers,
        sampler_consumers=sampler_consumers, currently_on=(lora_on and sampler_on),
    )


def apply_turbo_toggle(workflow: dict, turbo: TurboToggle, enabled: bool) -> None:
    model_target = [turbo.lora_id, 0] if enabled else list(turbo.base_model_link)
    sampler_target = [turbo.sampler_id, 0] if enabled else [turbo.standard_sampler_id, 0]
    for nid, key in turbo.lora_consumers:
        workflow[nid]["inputs"][key] = list(model_target)
    for nid, key in turbo.sampler_consumers:
        workflow[nid]["inputs"][key] = list(sampler_target)


# --------------------------------------------------------------------- #
# Patching
# --------------------------------------------------------------------- #

def apply_inputs(workflow: dict, edits: dict[tuple[str, str], object]) -> None:
    """Set node inputs by (node id, input key). Used for prompt text and
    LoRA name/strength edits alike."""
    for (nid, key), value in edits.items():
        node = workflow.get(nid)
        if isinstance(node, dict):
            node.setdefault("inputs", {})[key] = value


apply_prompts = apply_inputs


def list_loras(loras_dir: Path, sep: str = "\\") -> list[str]:
    """LoRA file names the way ComfyUI lists them: paths relative to the
    models/loras folder. ComfyUI joins subfolders with the server OS
    separator (backslash on Windows, slash on a RunPod Linux pod)."""
    if not loras_dir or not loras_dir.is_dir():
        return []
    out = []
    for p in loras_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in LORA_EXTS and not p.name.startswith("."):
            out.append(sep.join(p.relative_to(loras_dir).parts))
    return sorted(out, key=str.lower)


def apply_seed(workflow: dict, seed: int) -> int:
    n = 0
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inp = node.get("inputs", {}) or {}
        for key in ("noise_seed", "seed"):
            if _is_int(inp.get(key)):
                inp[key] = seed
                n += 1
    return n


def apply_value(workflow: dict, fld: ValueField, value: float) -> None:
    node = workflow.get(fld.node_id)
    if isinstance(node, dict):
        node.setdefault("inputs", {})[fld.key] = int(value) if fld.kind == "int" else float(value)


def apply_steps(workflow: dict, fields: list[StepsField], new_steps: int) -> int:
    """Set every sampler's step count, rescaling KSamplerAdvanced start/end
    boundaries proportionally (a boundary at or past the old count means
    "to the end" and follows the new count). Returns nodes changed."""
    new_steps = max(1, int(new_steps))
    n = 0
    for fld in fields:
        node = workflow.get(fld.node_id)
        if not isinstance(node, dict):
            continue
        inp = node.setdefault("inputs", {})
        old = fld.value if fld.value > 0 else new_steps
        inp["steps"] = new_steps
        if fld.start is not None:
            inp["start_at_step"] = min(new_steps, round(fld.start * new_steps / old)) if fld.start < old else new_steps
        if fld.end is not None:
            inp["end_at_step"] = round(fld.end * new_steps / old) if fld.end < old else max(new_steps, fld.end)
        n += 1
    return n


def apply_megapixels(workflow: dict, fields: list[ValueField], value: float) -> int:
    n = 0
    for fld in fields:
        if isinstance(workflow.get(fld.node_id), dict):
            apply_value(workflow, fld, round(float(value), 3))
            n += 1
    return n


def set_output_prefix(workflow: dict, prefix: str) -> None:
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") in VIDEO_OUTPUT_TYPES | IMAGE_OUTPUT_TYPES:
            if "filename_prefix" in (node.get("inputs") or {}):
                node["inputs"]["filename_prefix"] = prefix


def blank_workflow(workflow: dict) -> tuple[int, int]:
    """Clear a template for the "New blank workflow" button: every prompt
    (positive and negative) is emptied and every LoRA is switched off. Nodes
    are never removed, so the graph stays valid — a stack slot goes to "None",
    a single loader (whose name can't be "None") keeps its file at strength 0.
    The MiniMax Turbo LoRA is left alone; the Turbo toggle owns it.
    Returns (prompts cleared, LoRAs cleared)."""
    a = analyze(workflow)
    edits: dict[tuple[str, str], object] = {(pf.node_id, pf.key): "" for pf in a.prompts}
    loras = 0
    for slot in a.loras:
        if workflow.get(slot.node_id, {}).get("class_type") == "MiniMaxH3TurboLoRA":
            continue
        if slot.allow_none:
            edits[(slot.node_id, slot.name_key)] = "None"
        for key in slot.strengths:
            edits[(slot.node_id, key)] = 0.0
        loras += 1
    apply_inputs(workflow, edits)
    return len(a.prompts), loras


def save_workflow(path: Path, workflow: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, indent=2, ensure_ascii=False)
