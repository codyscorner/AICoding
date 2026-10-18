"""AI Image Studio v3.3.0"""

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QComboBox, QSlider, QSpinBox,
    QGroupBox, QFileDialog, QProgressBar, QSizePolicy, QTabWidget,
    QScrollArea, QFrame, QMessageBox, QLineEdit, QStackedWidget,
    QGridLayout, QCheckBox, QListWidget, QListWidgetItem, QDialog,
    QSplitter, QProgressDialog, QStatusBar,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QDragEnterEvent, QDropEvent

import alerts
import model_sync
from config import ConfigManager, app_dir
from ui.pod_control import PodControl
from ui.settings_dialog import SettingsDialog
from ui.styles import (
    BG, BG_MED, BG_LT, ACCENT, ACCENT2, FG, FG_DIM, BORDER, SUCCESS, ERROR,
    COLORS, POD_QSS,
)

VERSION = "3.3.2"

# Next to the EXE, not Path(__file__): in a one-file build that is the temp
# extraction folder, so settings, history and workflows vanished on exit.
APP_DIR       = app_dir()
SETTINGS_FILE = APP_DIR / "settings.json"
HISTORY_FILE  = APP_DIR / "generation_history.json"
WORKFLOWS_DIR = APP_DIR / "Comfy_Workflows"
DROPPED_DIR   = APP_DIR / "dropped_images"
UPLOAD_DIR    = APP_DIR / "upload_temp"

# A cold pod loads Flux.2's ~35 GB of weights from the network volume on the
# first run, which alone can take several minutes.
GENERATION_TIMEOUT_S = 30 * 60

NO_SERVER_MSG = "No ComfyUI URL — press Start Pod, or set one in ⚙ Settings > Server."

for _d in (WORKFLOWS_DIR, DROPPED_DIR, UPLOAD_DIR):
    _d.mkdir(exist_ok=True)

# ------------------------------------------------------------------ #
# Size presets
# ------------------------------------------------------------------ #

SIZE_PRESETS = [
    ("512 × 512   — Square (small)",        512,   512),
    ("768 × 768   — Square (medium)",       768,   768),
    ("1024 × 1024 — Square (standard)",    1024,  1024),
    ("768 × 1024  — Portrait (3:4)",        768,  1024),
    ("1024 × 1344 — Portrait (3:4 large)", 1024,  1344),
    ("832 × 1248  — Portrait (2:3, Flux.2 character)", 832, 1248),
    ("1024 × 1536 — Portrait (2:3, full body)",       1024, 1536),
    ("1024 × 768  — Landscape (4:3)",      1024,   768),
    ("1344 × 768  — Landscape (7:4)",      1344,   768),
    ("1248 × 832  — Landscape (3:2, character sheet)", 1248, 832),
    ("1920 × 1080 — Full HD wallpaper",    1920,  1080),
    ("2560 × 1440 — 2K / QHD wallpaper",  2560,  1440),
    ("3840 × 2160 — 4K UHD wallpaper",    3840,  2160),
    ("2560 × 1080 — UltraWide FHD",       2560,  1080),
    ("3440 × 1440 — UltraWide QHD",       3440,  1440),
    ("3840 × 1600 — UltraWide 4K",        3840,  1600),
    ("5120 × 1440 — Super UltraWide",     5120,  1440),
]

ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]
RESOLUTIONS   = ["1K", "2K", "4K"]

# ------------------------------------------------------------------ #
# Theme  (colour constants live in ui/styles.py, shared with the pod UI)
# ------------------------------------------------------------------ #

STYLESHEET = f"""
    QMainWindow, QWidget {{
        background-color: {BG};
        color: {FG};
        font-family: "Segoe UI";
        font-size: 10pt;
    }}
    QTabWidget::pane {{
        border: 1px solid {BORDER};
        border-radius: 4px;
        background-color: {BG};
    }}
    QTabBar::tab {{
        background-color: {BG_LT};
        color: {FG_DIM};
        border: 1px solid {BORDER};
        border-bottom: none;
        border-radius: 4px 4px 0 0;
        padding: 8px 24px;
        font-size: 10pt;
        font-weight: bold;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {ACCENT};
        color: white;
        border-color: {ACCENT};
    }}
    QTabBar::tab:hover:!selected {{ background-color: {BG_MED}; color: {FG}; }}
    QGroupBox {{
        color: {ACCENT};
        font-weight: bold;
        font-size: 10pt;
        border: 1px solid {BORDER};
        border-radius: 4px;
        margin-top: 8px;
        padding-top: 4px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }}
    QLabel {{ color: {FG}; }}
    QTextEdit {{
        background-color: {BG_LT};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 6px;
        font-size: 10pt;
    }}
    QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit {{
        background-color: {BG_LT};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 5px 8px;
        font-size: 10pt;
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox {{
        background-color: {BG_LT};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 5px 10px;
    }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background-color: {BG_MED};
        color: {FG};
        selection-background-color: {ACCENT};
    }}
    QSlider::groove:horizontal {{
        background: {BG_LT};
        height: 6px;
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {ACCENT};
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
    QSpinBox {{
        background-color: {BG_LT};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QPushButton {{
        background-color: {ACCENT};
        color: white;
        font-weight: bold;
        border: none;
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 10pt;
    }}
    QPushButton:hover {{ background-color: {ACCENT2}; }}
    QPushButton:disabled {{ background-color: {BG_LT}; color: {FG_DIM}; }}
    QPushButton#secondary {{
        background-color: {BG_LT};
        color: {FG_DIM};
        border: 1px solid {BORDER};
    }}
    QPushButton#secondary:hover {{ background-color: {BG_MED}; color: {FG}; }}
    QPushButton#danger {{
        background-color: {BG_LT};
        color: {ERROR};
        border: 1px solid {BORDER};
    }}
    QPushButton#danger:hover {{ background-color: {ERROR}; color: white; }}
    QProgressBar {{
        background-color: {BG_LT};
        border: 1px solid {BORDER};
        border-radius: 4px;
        height: 20px;
        text-align: center;
        color: white;
        font-size: 8pt;
    }}
    QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 3px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: {BG_LT};
        width: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
""" + POD_QSS

# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #

# Created by MainWindow. The tabs hold its live dict (CONFIG.data) as
# self._settings, so save_settings() just writes that one dict out.
CONFIG: ConfigManager | None = None

def save_settings(s: dict | None = None):
    if CONFIG is not None:
        CONFIG.save()

# ------------------------------------------------------------------ #
# Generation history  (prompt recall)
# ------------------------------------------------------------------ #

_HISTORY_MAX = 500

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []

def add_history_entry(entry: dict):
    try:
        hist = load_history()
        hist.insert(0, entry)
        del hist[_HISTORY_MAX:]
        HISTORY_FILE.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    except Exception:
        pass

def find_history_entry(path: str) -> dict | None:
    target = str(Path(path))
    for e in load_history():
        if str(Path(e.get("path", ""))) == target:
            return e
    return None

# ------------------------------------------------------------------ #
# Workflow introspection helpers
# ------------------------------------------------------------------ #

def _find_node_by_class(workflow: dict, class_type: str) -> tuple[str, dict] | None:
    for k, v in workflow.items():
        if v.get("class_type") == class_type:
            return k, v
    return None

def _set_prompt(workflow: dict, prompt: str):
    """A PrimitiveStringMultiline holds the prompt when the workflow has one;
    otherwise the first CLIPTextEncode not titled as a negative."""
    for v in workflow.values():
        if v.get("class_type") == "PrimitiveStringMultiline":
            v["inputs"]["value"] = prompt
            return
    for v in workflow.values():
        if v.get("class_type") == "CLIPTextEncode":
            meta = v.get("_meta", {}).get("title", "").lower()
            if "neg" not in meta and isinstance(v["inputs"].get("text"), str):
                v["inputs"]["text"] = prompt
                return


# Nodes whose width/height set the output size, with the multiple they need.
# Flux.2 works in 16-px patches: EmptyFlux2LatentImage floors to it, so its
# Flux2Scheduler twin must be given the same snapped numbers or the noise
# schedule is computed for a slightly different image than the one sampled.
_SIZE_NODES = {"EmptySD3LatentImage": 1, "EmptyLatentImage": 1,
               "EmptyFlux2LatentImage": 16, "Flux2Scheduler": 16}
# Nodes with a "steps" widget: classic KSampler, or the scheduler that feeds
# SamplerCustomAdvanced in Flux.2-style graphs.
_STEPS_NODES = ("KSampler", "Flux2Scheduler", "BasicScheduler")


def _snap(value: int, step: int) -> int:
    return max(step, int(round(value / step)) * step)


def _has_size_node(workflow: dict) -> bool:
    """True when the output size comes from a latent node rather than from
    the first input image (Qwen edit, img2img)."""
    return any(v.get("class_type") in _SIZE_NODES for v in workflow.values())


def _patch_size_and_steps(workflow: dict, width: int | None, height: int | None, steps: int):
    for v in workflow.values():
        ct = v.get("class_type")
        inp = v.get("inputs", {})
        if width and height and ct in _SIZE_NODES and isinstance(inp.get("width"), int):
            inp["width"] = _snap(width, _SIZE_NODES[ct])
            inp["height"] = _snap(height, _SIZE_NODES[ct])
        if ct in _STEPS_NODES and isinstance(inp.get("steps"), int):
            inp["steps"] = steps


def _workflow_steps(path: str | None) -> int | None:
    """The step count a workflow file was saved with, if it has one."""
    try:
        wf = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    for v in wf.values():
        if v.get("class_type") in _STEPS_NODES and isinstance(v.get("inputs", {}).get("steps"), int):
            return v["inputs"]["steps"]
    return None


def _patch_seed(workflow: dict, seed: int):
    for v in workflow.values():
        inp = v.get("inputs", {})
        if "noise_seed" in inp and isinstance(inp["noise_seed"], int):
            inp["noise_seed"] = seed
        if "seed" in inp and isinstance(inp["seed"], int):
            inp["seed"] = seed


def _resolve_seed(seed: int) -> int:
    import random
    return random.randint(0, 2**31) if seed < 0 else seed


def _patch_workflow_t2i(workflow: dict, prompt: str, width: int, height: int,
                         seed: int, steps: int) -> dict:
    _set_prompt(workflow, prompt)
    _patch_size_and_steps(workflow, width, height, steps)
    _patch_seed(workflow, _resolve_seed(seed))
    return workflow


def _patch_workflow_edit(workflow: dict, prompt: str, seed: int, steps: int,
                         width: int | None = None, height: int | None = None) -> dict:
    """Scene Composer. Size only reaches workflows with a latent node
    (Flux.2); Qwen edit takes its size from the resized first image."""
    _set_prompt(workflow, prompt)
    _patch_size_and_steps(workflow, width, height, steps)
    _patch_seed(workflow, _resolve_seed(seed))
    return workflow


def _patch_workflow_i2i(workflow: dict, prompt: str, seed: int, steps: int,
                        denoise: float) -> dict:
    """Patch an img2img workflow: prompt (if given), seed, steps, and denoise strength."""
    if prompt:
        _set_prompt(workflow, prompt)
    _patch_size_and_steps(workflow, None, None, steps)
    _patch_seed(workflow, _resolve_seed(seed))
    for v in workflow.values():
        inp = v.get("inputs", {})
        if "denoise" in inp and isinstance(inp["denoise"], (int, float)):
            inp["denoise"] = round(denoise, 2)
    return workflow


# Inputs that may be left unconnected. When a reference slot is empty its
# LoadImage chain is cut out of the workflow; a node that loses one of these
# keeps working without it, any other node that loses an input goes too.
_OPTIONAL_INPUTS = {
    "ReferenceLatent": {"latent"},                                # Flux.2 / Kontext reference chain
    "TextEncodeQwenImageEditPlus": {"image1", "image2", "image3"},
}
_OUTPUT_NODES = ("SaveImage", "PreviewImage")


def _node_order(node_id: str) -> tuple:
    """Numeric order for ids like "78", "436" and "433:117" — as text "436"
    sorts before "78", which put reference Image 1 into the second slot."""
    return tuple(int(p) if p.isdigit() else 0 for p in str(node_id).split(":"))


def _load_image_nodes(workflow: dict) -> list[str]:
    ids = [k for k, v in workflow.items() if v.get("class_type") == "LoadImage"]
    return sorted(ids, key=_node_order)


def _prune_unused_images(workflow: dict, unused: list[str]) -> dict:
    """Remove the LoadImage nodes no reference image was given for, plus
    everything that only exists to process them."""
    removed = set(unused)
    changed = True
    while changed:
        changed = False
        for nid, node in workflow.items():
            if nid in removed:
                continue
            optional = _OPTIONAL_INPUTS.get(node.get("class_type"), set())
            inputs = node.get("inputs", {})
            for key, val in list(inputs.items()):
                if isinstance(val, list) and len(val) == 2 and str(val[0]) in removed:
                    if key in optional:
                        del inputs[key]
                    else:
                        removed.add(nid)
                        changed = True
                        break
    pruned = {k: v for k, v in workflow.items() if k not in removed}
    if not any(v.get("class_type") in _OUTPUT_NODES for v in pruned.values()):
        raise RuntimeError(
            f"This workflow needs all {len(_load_image_nodes(workflow))} of its images — "
            "add more reference images or pick a workflow that takes fewer.")
    return pruned

# ------------------------------------------------------------------ #
# Local ComfyUI workers
# ------------------------------------------------------------------ #

def _comfy_rejection(resp) -> str:
    """ComfyUI answers a bad workflow with HTTP 400 and a node_errors map
    naming the node and input (missing model file, unknown node...). That
    text is the whole diagnosis — a bare "400 Bad Request" says nothing."""
    try:
        body = resp.json()
    except ValueError:
        return f"ComfyUI rejected the workflow (HTTP {resp.status_code}): {resp.text[:400]}"
    lines = [f"ComfyUI rejected the workflow (HTTP {resp.status_code}):"]
    err = body.get("error") or {}
    if isinstance(err, dict) and err.get("message"):
        lines.append(f"  {err['message']}" + (f" — {err['details']}" if err.get("details") else ""))
    for nid, ne in (body.get("node_errors") or {}).items():
        cls = ne.get("class_type", "?")
        for e in ne.get("errors", []):
            lines.append(f"  node {nid} ({cls}): {e.get('message', '')} {e.get('details', '')}".rstrip())
    return "\n".join(lines)


class ComfyWorker(QThread):
    status   = pyqtSignal(str)
    progress = pyqtSignal(int)
    done     = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, comfy_url: str, workflow: dict, output_dir: Path,
                 filename_prefix: str = "ComfyUI"):
        super().__init__()
        url = comfy_url.rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self._url = url
        self._workflow = workflow
        self._output_dir = output_dir
        self._prefix = filename_prefix
        self._client_id = str(__import__("uuid").uuid4())

    def run(self):
        try:
            import requests, time

            self.status.emit("Queuing prompt...")
            self.progress.emit(10)

            resp = requests.post(
                f"{self._url}/prompt",
                json={"prompt": self._workflow, "client_id": self._client_id},
                timeout=30,
            )
            if resp.status_code >= 400:
                raise RuntimeError(_comfy_rejection(resp))
            prompt_id = resp.json()["prompt_id"]

            self.status.emit("Generating...")
            elapsed = 0
            while True:
                time.sleep(3)
                elapsed += 3
                if elapsed > GENERATION_TIMEOUT_S:
                    raise RuntimeError(f"Timed out after {GENERATION_TIMEOUT_S // 60} minutes")

                try:
                    q = requests.get(f"{self._url}/queue", timeout=10).json()
                    running = [item[1] for item in q.get("queue_running", [])]
                    pending = [item[1] for item in q.get("queue_pending", [])]

                    if prompt_id in running or prompt_id in pending:
                        self.status.emit(f"Generating... ({elapsed}s)")
                        self.progress.emit(min(10 + elapsed, 85))
                        continue

                    h = requests.get(f"{self._url}/history/{prompt_id}", timeout=10).json()
                    if prompt_id in h:
                        hist = h
                        break

                except Exception:
                    self.status.emit(f"Polling... ({elapsed}s)")
                    continue

            self.status.emit("Downloading result...")
            self.progress.emit(90)

            hist_data = hist[prompt_id]
            outputs = hist_data.get("outputs", {})

            img_info = None
            for node_out in outputs.values():
                imgs = node_out.get("images", [])
                if imgs:
                    img_info = imgs[0]
                    break

            if not img_info:
                raise RuntimeError(
                    f"No output image found. "
                    f"Status: {hist_data.get('status', {}).get('status_str', 'unknown')}"
                )

            params = {
                "filename": img_info["filename"],
                "subfolder": img_info.get("subfolder", ""),
                "type": img_info.get("type", "output"),
            }
            img_resp = requests.get(f"{self._url}/view", params=params, timeout=60)
            img_resp.raise_for_status()

            self._output_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = self._output_dir / f"{self._prefix}_{ts}.png"
            out_path.write_bytes(img_resp.content)

            self.progress.emit(100)
            self.done.emit(str(out_path))

        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")

    def _upload_image(self, img_path: str, requests, filename: str) -> str:
        with open(img_path, "rb") as f:
            resp = requests.post(
                f"{self._url}/upload/image",
                files={"image": (filename, f, "image/png")},
                data={"type": "input", "overwrite": "true"},
                timeout=60,
            )
        resp.raise_for_status()
        return resp.json()["name"]


class EditorWorker(ComfyWorker):
    def __init__(self, comfy_url: str, workflow: dict, output_dir: Path,
                 ref_images: list[str], target_size: tuple[int, int]):
        super().__init__(comfy_url, workflow, output_dir, "edited")
        self._ref_images = ref_images
        self._target_size = target_size

    def run(self):
        try:
            import requests, random, string
            from PIL import Image as PILImage

            for f in UPLOAD_DIR.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass

            # Reference image N goes to the Nth LoadImage in numeric id order;
            # slots left empty have their whole chain cut out, or ComfyUI
            # rejects the workflow over a placeholder file it cannot find.
            load_nodes = _load_image_nodes(self._workflow)
            refs = self._ref_images[:len(load_nodes)]
            if len(refs) < len(load_nodes):
                self._workflow = _prune_unused_images(self._workflow, load_nodes[len(refs):])

            target_w, target_h = self._target_size
            # Workflows that size the output from the first image (Qwen edit,
            # img2img) get it resized to the chosen size. Flux.2 sets the size
            # with its own latent node and scales references itself, so its
            # images go up untouched (a resize would only distort them).
            resize_first = not _has_size_node(self._workflow)

            for i, img_path in enumerate(refs):
                node_id = load_nodes[i]
                self.status.emit(f"Uploading image {i+1}...")
                self.progress.emit(5 + i * 8)

                rand = ''.join(random.choices(string.ascii_lowercase, k=8))
                upload_name = f"img_{rand}.png"
                upload_path = UPLOAD_DIR / upload_name

                img = PILImage.open(img_path).convert("RGB")
                if i == 0 and resize_first:
                    img = img.resize((target_w, target_h), PILImage.LANCZOS)
                px = img.load()
                r, g, b = px[0, 0]
                px[0, 0] = ((r + 1) % 256, g, b)
                img.save(str(upload_path))

                uploaded_name = self._upload_image(str(upload_path), requests, upload_name)
                self._workflow[node_id]["inputs"]["image"] = uploaded_name

            super().run()

        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")


# ------------------------------------------------------------------ #
# Image drop slot widget
# ------------------------------------------------------------------ #

class ImageSlot(QLabel):
    image_changed = pyqtSignal(str)

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._path: str | None = None
        self._label = label
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(160, 160)
        self.setAcceptDrops(True)
        self._set_empty()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_empty(self):
        self._path = None
        self.setPixmap(QPixmap())
        self.setText(f"+ {self._label}\n\nDrag & drop\nor click")
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {BG_LT};
                border: 2px dashed {BORDER};
                border-radius: 6px;
                color: {FG_DIM};
                font-size: 9pt;
            }}
        """)

    def set_image(self, path: str, copy: bool = True):
        if self._path and Path(self._path).exists():
            self._archive(self._path)

        if copy and Path(path).parent != DROPPED_DIR:
            safe_name = Path(path).name.replace(" ", "_")
            dest = DROPPED_DIR / safe_name
            if dest.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = DROPPED_DIR / f"{Path(safe_name).stem}_{ts}{Path(safe_name).suffix}"
            shutil.copy2(path, dest)
            path = str(dest)

        self._path = path
        pix = QPixmap(path).scaled(
            156, 156,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(pix)
        self.setText("")
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {BG_MED};
                border: 2px solid {ACCENT};
                border-radius: 6px;
            }}
        """)
        self.image_changed.emit(path)

    def clear_image(self):
        if self._path and Path(self._path).exists():
            self._archive(self._path)
        self._set_empty()
        self.image_changed.emit("")

    def _archive(self, path: str):
        archive_dir = DROPPED_DIR / "archive"
        archive_dir.mkdir(exist_ok=True)
        src = Path(path)
        if src.exists() and src.parent == DROPPED_DIR:
            dest = archive_dir / src.name
            if dest.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = archive_dir / f"{src.stem}_{ts}{src.suffix}"
            shutil.move(str(src), str(dest))

    @property
    def path(self) -> str | None:
        return self._path

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, f"Select {self._label}",
                str(Path.home()),
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
            )
            if path:
                self.set_image(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                self.set_image(path)


# ------------------------------------------------------------------ #
# Shared preview panel
# ------------------------------------------------------------------ #

class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_path: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(4, 4, 4, 4)

        self._preview = QLabel("Output will appear here")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            f"color: {FG_DIM}; background-color: {BG_MED}; border-radius: 4px;"
        )
        self._preview.setMinimumSize(200, 200)
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self._preview)
        layout.addWidget(preview_group, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._save_btn = QPushButton("💾  Save As...")
        self._save_btn.setObjectName("secondary")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_as)
        self._open_btn = QPushButton("📁  Open Folder")
        self._open_btn.setObjectName("secondary")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self._save_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def show_image(self, path: str):
        self._last_path = path
        self._save_btn.setEnabled(True)
        self._open_btn.setEnabled(True)
        pix = QPixmap(path)
        if not pix.isNull():
            self._update_pixmap(pix)

    def _update_pixmap(self, pix: QPixmap):
        scaled = pix.scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self._preview.setPixmap(scaled)

    def set_message(self, msg: str):
        self._preview.setPixmap(QPixmap())
        self._preview.setText(msg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_path:
            pix = QPixmap(self._last_path)
            if not pix.isNull():
                self._update_pixmap(pix)

    def _save_as(self):
        if not self._last_path:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Image", self._last_path,
            "Images (*.png *.jpg *.webp)"
        )
        if dest:
            shutil.copy2(self._last_path, dest)

    def _open_folder(self):
        if self._last_path:
            subprocess.Popen(f'explorer "{Path(self._last_path).parent}"')


# ------------------------------------------------------------------ #
# Connection widget  (Local ComfyUI  /  RunPod Serverless)
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
# Library thumbnail card
# ------------------------------------------------------------------ #

_CARD_W  = 174
_CARD_H  = 210
_THUMB_W = 158
_THUMB_H = 138
_LIB_COLS = 4


class ThumbnailCard(QFrame):
    selected_signal = pyqtSignal(str)
    double_clicked = pyqtSignal(str)

    def __init__(self, img_path: str, favorite: bool = False, parent=None):
        super().__init__(parent)
        self._path = img_path
        self._favorite = favorite
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()
        self._set_style(False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_W, _THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(f"background-color: {BG}; border-radius: 3px;")
        pix = QPixmap(self._path)
        if not pix.isNull():
            scaled = pix.scaled(_THUMB_W, _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._thumb.setPixmap(scaled)
        else:
            self._thumb.setText("?")
        layout.addWidget(self._thumb)

        self._name = Path(self._path).name
        if len(self._name) > 22:
            self._name = self._name[:19] + "..."
        self._name_lbl = QLabel()
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setStyleSheet(f"color: {FG}; font-size: 8pt; background: transparent; border: none;")
        layout.addWidget(self._name_lbl)
        self._update_name_label()

        try:
            mtime = Path(self._path).stat().st_mtime
            date_str = datetime.fromtimestamp(mtime).strftime("%m/%d  %H:%M")
        except Exception:
            date_str = ""
        date_lbl = QLabel(date_str)
        date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 7pt; background: transparent; border: none;")
        layout.addWidget(date_lbl)

    def _set_style(self, selected: bool):
        border = ACCENT if selected else BORDER
        bg = BG_MED if selected else BG_LT
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 6px;
            }}
        """)

    def set_selected(self, selected: bool):
        self._set_style(selected)

    def _update_name_label(self):
        if self._favorite:
            self._name_lbl.setText(f'<span style="color:#f5c04a;">★</span> {self._name}')
        else:
            self._name_lbl.setText(self._name)

    def set_favorite(self, favorite: bool):
        self._favorite = favorite
        self._update_name_label()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected_signal.emit(self._path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._path)
        super().mouseDoubleClickEvent(event)

    @property
    def path(self) -> str:
        return self._path


# ------------------------------------------------------------------ #
# A/B compare dialog
# ------------------------------------------------------------------ #

class CompareDialog(QDialog):
    def __init__(self, path_a: str, path_b: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare  A ⇆ B")
        self.resize(1280, 760)
        self.setStyleSheet(STYLESHEET)
        self._pix_a = QPixmap(path_a)
        self._pix_b = QPixmap(path_b)

        layout = QHBoxLayout(self)
        layout.setSpacing(12)
        self._img_labels: list[tuple[QLabel, QPixmap]] = []

        for tag, path, pix in (("A", path_a, self._pix_a), ("B", path_b, self._pix_b)):
            col = QVBoxLayout()
            col.setSpacing(6)

            img_lbl = QLabel()
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setMinimumSize(300, 300)
            img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            img_lbl.setStyleSheet(f"background-color: {BG_MED}; border-radius: 4px;")
            self._img_labels.append((img_lbl, pix))
            col.addWidget(img_lbl, stretch=1)

            p = Path(path)
            cap = QLabel(f"<b style='color:{ACCENT};'>{tag}</b>   {p.name}")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setStyleSheet(f"color:{FG}; font-size:9pt;")
            col.addWidget(cap)

            try:
                stat = p.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                dims = f"{pix.width()} × {pix.height()}" if not pix.isNull() else "?"
                detail = QLabel(f"{dims}   ·   {stat.st_size / 1024:.0f} KB   ·   {mtime}")
            except Exception:
                detail = QLabel("")
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail.setStyleSheet(f"color:{FG_DIM}; font-size:8pt;")
            col.addWidget(detail)

            layout.addLayout(col, stretch=1)

    def _update_pixmaps(self):
        for lbl, pix in self._img_labels:
            if not pix.isNull():
                lbl.setPixmap(pix.scaled(
                    lbl.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))

    def showEvent(self, event):
        super().showEvent(event)
        self._update_pixmaps()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmaps()


# ------------------------------------------------------------------ #
# Full-size image viewer dialog
# ------------------------------------------------------------------ #

class ImageViewerDialog(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        p = Path(path)
        self.setWindowTitle(p.name)
        self.setStyleSheet(STYLESHEET)
        self._pix = QPixmap(path)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setMinimumSize(300, 300)
        self._img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_lbl.setStyleSheet(f"background-color: {BG_MED}; border-radius: 4px;")
        layout.addWidget(self._img_lbl, stretch=1)

        try:
            stat = p.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            dims = f"{self._pix.width()} × {self._pix.height()}" if not self._pix.isNull() else "?"
            detail = QLabel(f"{p.name}   ·   {dims}   ·   {stat.st_size / 1024:.0f} KB   ·   {mtime}")
        except Exception:
            detail = QLabel(p.name)
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setStyleSheet(f"color:{FG_DIM}; font-size:9pt;")
        layout.addWidget(detail)

        # Size the window to the image (capped to a sane max) instead of a fixed default
        screen = QApplication.primaryScreen().availableGeometry()
        max_w, max_h = int(screen.width() * 0.9), int(screen.height() * 0.9)
        if not self._pix.isNull():
            w = min(max(self._pix.width() + 60, 500), max_w)
            h = min(max(self._pix.height() + 100, 400), max_h)
        else:
            w, h = 900, 700
        self.resize(w, h)

    def _update_pixmap(self):
        if not self._pix.isNull():
            self._img_lbl.setPixmap(self._pix.scaled(
                self._img_lbl.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def showEvent(self, event):
        super().showEvent(event)
        self._update_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)


# ------------------------------------------------------------------ #
# Tab 1 — Text to Image
# ------------------------------------------------------------------ #

class TextToImageTab(QWidget):
    def __init__(self, settings: dict, host: "MainWindow", parent=None):
        super().__init__(parent)
        self._settings = settings
        self._host = host
        self._worker: QThread | None = None
        self._queue: list[dict] = []
        self._queue_running = False
        self._queue_total = 0
        self._queue_done = 0
        self._queue_failed = 0
        self._active_job: dict | None = None
        self._build_ui()
        self._reload_workflows()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setSpacing(10)
        left.setContentsMargins(4, 4, 4, 4)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(280)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")


        # Workflow
        wf_group = QGroupBox("Workflow")
        wf_row = QHBoxLayout(wf_group)
        self._wf_combo = QComboBox()
        wf_reload = QPushButton("↻ Reload")
        wf_reload.setObjectName("secondary")
        wf_reload.setFixedHeight(34)
        wf_reload.setToolTip("Reload workflows")
        wf_reload.clicked.connect(self._reload_workflows)
        wf_row.addWidget(self._wf_combo, stretch=1)
        self._wf_combo.activated.connect(self._on_workflow_picked)
        wf_row.addWidget(wf_reload)
        left.addWidget(wf_group)

        # Prompt
        prompt_group = QGroupBox("Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        self._prompt = QTextEdit()
        self._prompt.setPlaceholderText("Describe the image you want to generate...")
        self._prompt.setPlainText(self._settings.get("t2i_prompt", ""))
        self._prompt.setFixedHeight(120)
        self._prompt.textChanged.connect(self._save_state)
        prompt_layout.addWidget(self._prompt)
        left.addWidget(prompt_group)

        # Size
        size_group = QGroupBox("Output Size")
        size_layout = QVBoxLayout(size_group)
        self._size_combo = QComboBox()
        for label, w, h in SIZE_PRESETS:
            self._size_combo.addItem(label, (w, h))
        saved_size = tuple(self._settings.get("t2i_size", [1024, 1024]))
        for i, (_, w, h) in enumerate(SIZE_PRESETS):
            if (w, h) == saved_size:
                self._size_combo.setCurrentIndex(i)
                break
        self._size_combo.currentIndexChanged.connect(self._save_state)
        size_layout.addWidget(self._size_combo)
        left.addWidget(size_group)

        # Steps + Seed
        params_row = QHBoxLayout()

        steps_group = QGroupBox("Steps")
        steps_inner = QHBoxLayout(steps_group)
        self._steps = QSlider(Qt.Orientation.Horizontal)
        self._steps.setRange(1, 60)
        self._steps.setValue(self._settings.get("t2i_steps", 20))
        self._steps_lbl = QLabel(str(self._steps.value()))
        self._steps_lbl.setFixedWidth(28)
        self._steps_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._steps_lbl.setStyleSheet(f"color:{ACCENT}; font-weight:bold;")
        self._steps.valueChanged.connect(lambda v: (self._steps_lbl.setText(str(v)), self._save_state()))
        steps_inner.addWidget(self._steps)
        steps_inner.addWidget(self._steps_lbl)
        params_row.addWidget(steps_group, stretch=2)

        seed_group = QGroupBox("Seed  (-1 = random)")
        seed_inner = QHBoxLayout(seed_group)
        self._seed = QSpinBox()
        self._seed.setRange(-1, 2147483647)
        self._seed.setValue(-1)
        rand_btn = QPushButton("🎲 Random")
        rand_btn.setObjectName("secondary")
        rand_btn.setFixedHeight(30)
        rand_btn.clicked.connect(lambda: self._seed.setValue(-1))
        seed_inner.addWidget(self._seed)
        seed_inner.addWidget(rand_btn)
        params_row.addWidget(seed_group, stretch=1)
        left.addLayout(params_row)

        # Output folder
        out_group = QGroupBox("Output Folder")
        out_row = QHBoxLayout(out_group)
        self._out_edit = QTextEdit(self._settings.get("t2i_output_dir",
                                   str(Path.home() / "AI_Images")))
        self._out_edit.setFixedHeight(36)
        self._out_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        out_browse = QPushButton("Browse")
        out_browse.setObjectName("secondary")
        out_browse.setFixedHeight(36)
        out_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(out_browse)
        left.addWidget(out_group)

        # Batch queue
        queue_group = QGroupBox("Batch Queue")
        queue_layout = QVBoxLayout(queue_group)
        queue_layout.setSpacing(6)
        self._queue_list = QListWidget()
        self._queue_list.setFixedHeight(96)
        self._queue_list.setStyleSheet(
            f"QListWidget {{ background-color: {BG_LT}; border: 1px solid {BORDER};"
            f" border-radius: 4px; font-size: 8pt; color: {FG}; }}"
            f"QListWidget::item:selected {{ background-color: {ACCENT}; color: white; }}"
        )
        queue_layout.addWidget(self._queue_list)
        qbtn_row = QHBoxLayout()
        qbtn_row.setSpacing(6)
        add_q_btn = QPushButton("➕ Add to Queue")
        add_q_btn.setObjectName("secondary")
        add_q_btn.clicked.connect(self._add_to_queue)
        self._run_q_btn = QPushButton("▶ Run Queue")
        self._run_q_btn.setObjectName("secondary")
        self._run_q_btn.clicked.connect(self._run_queue)
        rm_q_btn = QPushButton("✕ Remove")
        rm_q_btn.setObjectName("secondary")
        rm_q_btn.setFixedHeight(30)
        rm_q_btn.setToolTip("Remove selected job")
        rm_q_btn.clicked.connect(self._remove_queue_item)
        clr_q_btn = QPushButton("🗑 Clear")
        clr_q_btn.setObjectName("secondary")
        clr_q_btn.setFixedHeight(30)
        clr_q_btn.setToolTip("Clear queue")
        clr_q_btn.clicked.connect(self._clear_queue)
        qbtn_row.addWidget(add_q_btn, stretch=1)
        qbtn_row.addWidget(self._run_q_btn, stretch=1)
        qbtn_row.addWidget(rm_q_btn)
        qbtn_row.addWidget(clr_q_btn)
        queue_layout.addLayout(qbtn_row)
        left.addWidget(queue_group)

        left.addStretch()

        self._gen_btn = QPushButton("✨  Generate")
        self._gen_btn.setFixedHeight(50)
        self._gen_btn.setStyleSheet(f"font-size:13pt; background-color:{ACCENT}; border-radius:6px;")
        self._gen_btn.clicked.connect(self._generate)
        left.addWidget(self._gen_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        left.addWidget(self._progress)

        self._status = QLabel("Select a workflow and enter a prompt")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color:{FG_DIM}; font-size:9pt;")
        self._status.setWordWrap(True)
        left.addWidget(self._status)

        root.addWidget(left_scroll, stretch=1)

        self._preview_panel = PreviewPanel()
        root.addWidget(self._preview_panel, stretch=2)

    def _on_workflow_picked(self, _index: int):
        """Picking a workflow loads its own step count (28 for Flux.2, 8 for
        Turbo, 4 for Qwen Lightning): the slider always overrides the file,
        so a value left over from another workflow would run silently wrong."""
        steps = _workflow_steps(self._wf_combo.currentData())
        if steps:
            self._steps.setValue(steps)
        self._save_state()

    def _reload_workflows(self):
        self._wf_combo.clear()
        workflows = sorted(WORKFLOWS_DIR.glob("t2i_*.json"))
        for wf in workflows:
            self._wf_combo.addItem(wf.stem.replace("_", " ").replace("t2i ", ""), str(wf))
        if not workflows:
            self._wf_combo.addItem("No workflows found — add t2i_*.json to Comfy_Workflows/", "")
        saved_wf = self._settings.get("t2i_workflow", "")
        for i in range(self._wf_combo.count()):
            if self._wf_combo.itemData(i) == saved_wf:
                self._wf_combo.setCurrentIndex(i)
                break

    def _save_state(self):
        if not hasattr(self, '_prompt'):
            return
        self._settings["t2i_prompt"] = self._prompt.toPlainText()
        self._settings["t2i_steps"] = self._steps.value()
        self._settings["t2i_workflow"] = self._wf_combo.currentData() or ""
        self._settings["t2i_size"] = list(self._size_combo.currentData() or (1024, 1024))
        self._settings["t2i_output_dir"] = self._out_edit.toPlainText().strip()
        save_settings(self._settings)

    def _browse_output(self):
        f = QFileDialog.getExistingDirectory(self, "Select output folder",
                                              self._out_edit.toPlainText().strip())
        if f:
            self._out_edit.setPlainText(f)
            self._settings["t2i_output_dir"] = f
            save_settings(self._settings)

    def _collect_job(self) -> dict | None:
        """Validate the current form and return a job dict, or None (with status set)."""
        workflow_path = self._wf_combo.currentData()
        prompt = self._prompt.toPlainText().strip()
        out = self._out_edit.toPlainText().strip()

        if not workflow_path or not Path(workflow_path).exists():
            self._status.setText("Select a valid workflow.")
            return None
        if not prompt:
            self._status.setText("Enter a prompt.")
            return None
        if not out:
            self._status.setText("Select an output folder.")
            return None

        w, h = self._size_combo.currentData()
        return {
            "workflow_path": workflow_path,
            "prompt": prompt,
            "size": [w, h],
            "steps": self._steps.value(),
            "seed": self._seed.value(),
            "output_dir": out,
        }

    def _start_job(self, job: dict) -> bool:
        """Kick off one generation job. Returns False if it could not start."""
        import random

        with open(job["workflow_path"], "r", encoding="utf-8") as f:
            workflow = json.load(f)

        seed = job["seed"]
        if seed < 0:
            seed = random.randint(0, 2**31)

        w, h = job["size"]
        workflow = _patch_workflow_t2i(workflow, job["prompt"], w, h,
                                        seed, job["steps"])

        out = Path(job["output_dir"])
        url = self._host.server_url()
        if not url:
            self._status.setText(NO_SERVER_MSG)
            return False
        self._worker = ComfyWorker(url, workflow, out, "t2i")

        self._active_job = dict(job, seed=seed)
        self._gen_btn.setEnabled(False)
        self._run_q_btn.setEnabled(False)
        self._progress.setValue(0)
        self._preview_panel.set_message("Generating...")

        self._worker.status.connect(self._status.setText)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._host.run_started(self._worker)
        self._worker.start()
        return True

    def is_busy(self) -> bool:
        return self._queue_running or bool(self._worker and self._worker.isRunning())

    def _generate(self):
        if self.is_busy():
            return
        job = self._collect_job()
        if not job:
            return
        self._save_state()
        self._host.before_run([job["workflow_path"]], lambda: self._start_job(job))

    # ---- Batch queue ---------------------------------------------- #

    def _add_to_queue(self):
        job = self._collect_job()
        if not job:
            return
        self._queue.append(job)
        self._refresh_queue_list()
        self._status.setText(f"Queued job {len(self._queue)} — "
                             f"{len(self._queue)} waiting")

    def _refresh_queue_list(self):
        self._queue_list.clear()
        for i, job in enumerate(self._queue, 1):
            w, h = job["size"]
            text = job["prompt"].replace("\n", " ")
            if len(text) > 46:
                text = text[:43] + "..."
            self._queue_list.addItem(f"{i}.  {text}   [{w}×{h}, {job['steps']}st]")
        n = len(self._queue)
        self._run_q_btn.setText(f"▶ Run Queue ({n})" if n else "▶ Run Queue")

    def _remove_queue_item(self):
        row = self._queue_list.currentRow()
        if 0 <= row < len(self._queue):
            self._queue.pop(row)
            self._refresh_queue_list()

    def _clear_queue(self):
        self._queue.clear()
        self._refresh_queue_list()

    def _run_queue(self):
        if self.is_busy():
            return
        if not self._queue:
            self._status.setText("Queue is empty — add jobs first.")
            return
        # Every workflow the queue uses is checked once up front, so the
        # model check never interrupts the queue halfway through.
        workflows = list(dict.fromkeys(j["workflow_path"] for j in self._queue))
        self._host.before_run(workflows, self._begin_queue)

    def _begin_queue(self):
        if not self._queue:
            return
        self._queue_running = True
        self._queue_total = len(self._queue)
        self._queue_done = 0
        self._queue_failed = 0
        self._start_next_queued()

    def _start_next_queued(self):
        if not self._queue:
            self._finish_queue()
            return
        if self._host.over_limit():
            # The pod hit its spend limit mid-queue: stop starting jobs so
            # PodControl can stop the pod; what's left stays queued.
            self._finish_queue(stopped="spend limit reached — remaining jobs left in the queue")
            return
        job = self._queue.pop(0)
        self._refresh_queue_list()
        self._status.setText(f"Queue: job {self._queue_done + self._queue_failed + 1} "
                             f"of {self._queue_total}...")
        if not self._start_job(job):
            self._queue_failed += 1
            self._start_next_queued()

    def _finish_queue(self, stopped: str = ""):
        self._queue_running = False
        self._gen_btn.setEnabled(True)
        self._run_q_btn.setEnabled(True)
        msg = f"Queue {'stopped' if stopped else 'complete'} — {self._queue_done} done"
        if self._queue_failed:
            msg += f", {self._queue_failed} failed"
        if stopped:
            msg += f" ({stopped})"
        self._status.setText(msg)
        self._host.run_ended()

    # ---- Completion ------------------------------------------------ #

    def _record_history(self, path: str):
        job = self._active_job or {}
        add_history_entry({
            "path": str(path),
            "tab": "t2i",
            "prompt": job.get("prompt", ""),
            "workflow": job.get("workflow_path", ""),
            "size": job.get("size", []),
            "steps": job.get("steps", 0),
            "seed": job.get("seed", -1),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    def _on_done(self, path: str):
        self._record_history(path)
        self._preview_panel.show_image(path)
        if self._queue_running:
            self._queue_done += 1
            self._start_next_queued()
        else:
            self._gen_btn.setEnabled(True)
            self._run_q_btn.setEnabled(True)
            self._status.setText(f"Done! {Path(path).name}")
            self._host.run_ended()

    def _on_error(self, msg: str):
        self._progress.setValue(0)
        if self._queue_running:
            self._queue_failed += 1
            self._preview_panel.set_message(f"Job failed:\n{msg[:300]}")
            self._start_next_queued()
        else:
            self._gen_btn.setEnabled(True)
            self._run_q_btn.setEnabled(True)
            self._status.setText("Error — see preview panel")
            self._preview_panel.set_message(f"Error:\n{msg[:400]}")
            self._host.run_ended()

    # ---- Prompt recall --------------------------------------------- #

    def apply_history(self, entry: dict):
        self._prompt.setPlainText(entry.get("prompt", ""))
        steps = entry.get("steps")
        if isinstance(steps, int) and steps > 0:
            self._steps.setValue(steps)
        seed = entry.get("seed")
        if isinstance(seed, int):
            self._seed.setValue(seed)
        size = entry.get("size") or []
        if len(size) == 2:
            for i in range(self._size_combo.count()):
                if self._size_combo.itemData(i) == tuple(size):
                    self._size_combo.setCurrentIndex(i)
                    break
        wf = entry.get("workflow", "")
        for i in range(self._wf_combo.count()):
            if self._wf_combo.itemData(i) == wf:
                self._wf_combo.setCurrentIndex(i)
                break
        self._save_state()


# ------------------------------------------------------------------ #
# Tab 2 — Scene Composer
# ------------------------------------------------------------------ #

class SceneComposerTab(QWidget):
    def __init__(self, settings: dict, host: "MainWindow", parent=None):
        super().__init__(parent)
        self._settings = settings
        self._host = host
        self._worker: QThread | None = None
        self._build_ui()
        self._reload_workflows()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setSpacing(10)
        left.setContentsMargins(4, 4, 4, 4)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(280)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")


        # Workflow
        wf_group = QGroupBox("Workflow")
        wf_row = QHBoxLayout(wf_group)
        self._wf_combo = QComboBox()
        wf_reload = QPushButton("↻ Reload")
        wf_reload.setObjectName("secondary")
        wf_reload.setFixedHeight(34)
        wf_reload.setToolTip("Reload workflows")
        wf_reload.clicked.connect(self._reload_workflows)
        wf_row.addWidget(self._wf_combo, stretch=1)
        self._wf_combo.activated.connect(self._on_workflow_picked)
        wf_row.addWidget(wf_reload)
        left.addWidget(wf_group)

        # Output size
        size_group = QGroupBox("Output Size")
        size_layout = QVBoxLayout(size_group)
        self._size_combo = QComboBox()
        for label, w, h in SIZE_PRESETS:
            self._size_combo.addItem(label, (w, h))
        saved_size = tuple(self._settings.get("edit_size", [1024, 1024]))
        for i, (_, w, h) in enumerate(SIZE_PRESETS):
            if (w, h) == saved_size:
                self._size_combo.setCurrentIndex(i)
                break
        self._size_combo.currentIndexChanged.connect(self._save_state)
        size_layout.addWidget(self._size_combo)
        left.addWidget(size_group)

        # Image slots — 2×2 grid so each slot stays 160px wide
        refs_group = QGroupBox("Reference Images  (drag & drop or click)")
        refs_layout = QVBoxLayout(refs_group)
        refs_layout.setContentsMargins(6, 10, 6, 10)
        slot_grid = QGridLayout()
        slot_grid.setSpacing(8)
        self._slots: list[ImageSlot] = []
        saved_images = self._settings.get("edit_images", [None, None, None, None])
        for i, lbl in enumerate(["Image 1", "Image 2", "Image 3", "Image 4"]):
            slot = ImageSlot(lbl)
            slot.image_changed.connect(self._save_state)
            self._slots.append(slot)
            slot_grid.addWidget(slot, i // 2, i % 2)
            saved = saved_images[i] if i < len(saved_images) else None
            if saved and Path(saved).exists():
                slot.set_image(saved, copy=False)
        refs_layout.addLayout(slot_grid)
        left.addWidget(refs_group)

        clear_row = QHBoxLayout()
        clear_row.addStretch()
        clear_lbl = QLabel('<a href="#" style="color:#ff6b6b; font-size:8pt; text-decoration:none;">✕ clear all</a>')
        clear_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        clear_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_lbl.linkActivated.connect(lambda _: self._clear_slots())
        clear_row.addWidget(clear_lbl)
        left.addLayout(clear_row)

        # Prompt
        instr_group = QGroupBox("Prompt / Instruction")
        instr_layout = QVBoxLayout(instr_group)
        self._instruction = QTextEdit()
        self._instruction.setPlaceholderText(
            "Describe the scene, e.g.:\n"
            "\"Place these two people on a beach at sunset\""
        )
        self._instruction.setPlainText(self._settings.get("edit_prompt", ""))
        self._instruction.setFixedHeight(100)
        self._instruction.textChanged.connect(self._save_state)
        instr_layout.addWidget(self._instruction)
        left.addWidget(instr_group)

        # Steps + Seed
        params_row = QHBoxLayout()

        steps_group = QGroupBox("Steps")
        steps_inner = QHBoxLayout(steps_group)
        self._steps = QSlider(Qt.Orientation.Horizontal)
        self._steps.setRange(1, 60)
        self._steps.setValue(self._settings.get("edit_steps", 6))
        self._steps_lbl = QLabel(str(self._steps.value()))
        self._steps_lbl.setFixedWidth(28)
        self._steps_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._steps_lbl.setStyleSheet(f"color:{ACCENT}; font-weight:bold;")
        self._steps.valueChanged.connect(lambda v: (self._steps_lbl.setText(str(v)), self._save_state()))
        steps_inner.addWidget(self._steps)
        steps_inner.addWidget(self._steps_lbl)
        params_row.addWidget(steps_group, stretch=2)

        seed_group = QGroupBox("Seed  (-1 = random)")
        seed_inner = QHBoxLayout(seed_group)
        self._seed = QSpinBox()
        self._seed.setRange(-1, 2147483647)
        self._seed.setValue(-1)
        rand_btn = QPushButton("🎲 Random")
        rand_btn.setObjectName("secondary")
        rand_btn.setFixedHeight(30)
        rand_btn.clicked.connect(lambda: self._seed.setValue(-1))
        seed_inner.addWidget(self._seed)
        seed_inner.addWidget(rand_btn)
        params_row.addWidget(seed_group, stretch=1)
        left.addLayout(params_row)

        # Output folder
        out_group = QGroupBox("Output Folder")
        out_row = QHBoxLayout(out_group)
        self._out_edit = QTextEdit(self._settings.get("edit_output_dir",
                                   str(Path.home() / "AI_Images")))
        self._out_edit.setFixedHeight(36)
        self._out_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        out_browse = QPushButton("Browse")
        out_browse.setObjectName("secondary")
        out_browse.setFixedHeight(36)
        out_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(out_browse)
        left.addWidget(out_group)

        left.addStretch()

        self._compose_btn = QPushButton("🎨  Compose Scene")
        self._compose_btn.setFixedHeight(50)
        self._compose_btn.setStyleSheet(f"font-size:13pt; background-color:{ACCENT}; border-radius:6px;")
        self._compose_btn.clicked.connect(self._compose)
        left.addWidget(self._compose_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        left.addWidget(self._progress)

        self._status = QLabel("Load reference images and describe your scene")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color:{FG_DIM}; font-size:9pt;")
        self._status.setWordWrap(True)
        left.addWidget(self._status)

        root.addWidget(left_scroll, stretch=1)

        self._preview_panel = PreviewPanel()
        root.addWidget(self._preview_panel, stretch=2)

    def _on_workflow_picked(self, _index: int):
        """Picking a workflow loads its own step count (28 for Flux.2, 8 for
        Turbo, 4 for Qwen Lightning): the slider always overrides the file,
        so a value left over from another workflow would run silently wrong."""
        steps = _workflow_steps(self._wf_combo.currentData())
        if steps:
            self._steps.setValue(steps)
        self._save_state()

    def _reload_workflows(self):
        self._wf_combo.clear()
        workflows = sorted(WORKFLOWS_DIR.glob("edit_*.json"))
        for wf in workflows:
            self._wf_combo.addItem(wf.stem.replace("_", " ").replace("edit ", ""), str(wf))
        if not workflows:
            self._wf_combo.addItem("No workflows found — add edit_*.json to Comfy_Workflows/", "")
        saved_wf = self._settings.get("edit_workflow", "")
        for i in range(self._wf_combo.count()):
            if self._wf_combo.itemData(i) == saved_wf:
                self._wf_combo.setCurrentIndex(i)
                break

    def _save_state(self):
        if not hasattr(self, '_instruction'):
            return
        self._settings["edit_prompt"] = self._instruction.toPlainText()
        self._settings["edit_steps"] = self._steps.value()
        self._settings["edit_workflow"] = self._wf_combo.currentData() or ""
        self._settings["edit_images"] = [s.path for s in self._slots]
        self._settings["edit_size"] = list(self._size_combo.currentData() or (1024, 1024))
        self._settings["edit_output_dir"] = self._out_edit.toPlainText().strip()
        save_settings(self._settings)

    def _browse_output(self):
        f = QFileDialog.getExistingDirectory(self, "Select output folder",
                                              self._out_edit.toPlainText().strip())
        if f:
            self._out_edit.setPlainText(f)
            self._settings["edit_output_dir"] = f
            save_settings(self._settings)

    def _clear_slots(self):
        for slot in self._slots:
            slot.clear_image()

    def is_busy(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def _compose(self):
        if self.is_busy():
            return
        workflow_path = self._wf_combo.currentData()
        instruction = self._instruction.toPlainText().strip()
        out = self._out_edit.toPlainText().strip()
        ref_images = [s.path for s in self._slots if s.path]

        if not workflow_path or not Path(workflow_path).exists():
            self._status.setText("Select a valid workflow.")
            return
        if not ref_images:
            self._status.setText("Add at least one reference image.")
            return
        if not instruction:
            self._status.setText("Enter a prompt or instruction.")
            return
        if not out:
            self._status.setText("Select an output folder.")
            return
        self._save_state()
        self._host.before_run(
            [workflow_path],
            lambda: self._launch(workflow_path, instruction, out, ref_images))

    def _launch(self, workflow_path: str, instruction: str, out: str, ref_images: list[str]):
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        import random
        seed = self._seed.value()
        if seed < 0:
            seed = random.randint(0, 2**31)

        w, h = self._size_combo.currentData()
        workflow = _patch_workflow_edit(workflow, instruction, seed, self._steps.value(), w, h)

        self._active_job = {
            "prompt": instruction,
            "workflow_path": workflow_path,
            "size": [w, h],
            "steps": self._steps.value(),
            "seed": seed,
        }

        url = self._host.server_url()
        if not url:
            self._status.setText(NO_SERVER_MSG)
            return
        self._compose_btn.setEnabled(False)
        self._progress.setValue(0)
        self._preview_panel.set_message("Sending to ComfyUI...")
        self._worker = EditorWorker(url, workflow, Path(out), ref_images, (w, h))

        self._worker.status.connect(self._status.setText)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._host.run_started(self._worker)
        self._worker.start()

    def _on_done(self, path: str):
        self._compose_btn.setEnabled(True)
        self._status.setText(f"Done! {Path(path).name}")
        self._preview_panel.show_image(path)
        job = getattr(self, "_active_job", None) or {}
        add_history_entry({
            "path": str(path),
            "tab": "edit",
            "prompt": job.get("prompt", ""),
            "workflow": job.get("workflow_path", ""),
            "size": job.get("size", []),
            "steps": job.get("steps", 0),
            "seed": job.get("seed", -1),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        self._host.run_ended()

    def _on_error(self, msg: str):
        self._compose_btn.setEnabled(True)
        self._progress.setValue(0)
        self._status.setText("Error — see preview panel")
        self._preview_panel.set_message(f"Error:\n{msg[:400]}")
        self._host.run_ended()

    def apply_history(self, entry: dict):
        self._instruction.setPlainText(entry.get("prompt", ""))
        steps = entry.get("steps")
        if isinstance(steps, int) and steps > 0:
            self._steps.setValue(steps)
        seed = entry.get("seed")
        if isinstance(seed, int):
            self._seed.setValue(seed)
        size = entry.get("size") or []
        if len(size) == 2:
            for i in range(self._size_combo.count()):
                if self._size_combo.itemData(i) == tuple(size):
                    self._size_combo.setCurrentIndex(i)
                    break
        wf = entry.get("workflow", "")
        for i in range(self._wf_combo.count()):
            if self._wf_combo.itemData(i) == wf:
                self._wf_combo.setCurrentIndex(i)
                break
        self._save_state()


# ------------------------------------------------------------------ #
# Tab 3 — Img2img Variations
# ------------------------------------------------------------------ #

class ImageVariationsTab(QWidget):
    def __init__(self, settings: dict, host: "MainWindow", parent=None):
        super().__init__(parent)
        self._settings = settings
        self._host = host
        self._worker: QThread | None = None
        self._active_job: dict | None = None
        self._build_ui()
        self._reload_workflows()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setSpacing(10)
        left.setContentsMargins(4, 4, 4, 4)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(280)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")


        # Workflow
        wf_group = QGroupBox("Workflow")
        wf_row = QHBoxLayout(wf_group)
        self._wf_combo = QComboBox()
        wf_reload = QPushButton("↻ Reload")
        wf_reload.setObjectName("secondary")
        wf_reload.setFixedHeight(34)
        wf_reload.setToolTip("Reload workflows")
        wf_reload.clicked.connect(self._reload_workflows)
        wf_row.addWidget(self._wf_combo, stretch=1)
        self._wf_combo.activated.connect(self._on_workflow_picked)
        wf_row.addWidget(wf_reload)
        left.addWidget(wf_group)

        # Source image slot
        src_group = QGroupBox("Source Image  (drag & drop or click)")
        src_layout = QHBoxLayout(src_group)
        src_layout.setContentsMargins(6, 10, 6, 10)
        self._src_slot = ImageSlot("Source Image")
        self._src_slot.image_changed.connect(self._save_state)
        src_layout.addStretch()
        src_layout.addWidget(self._src_slot)
        src_layout.addStretch()
        left.addWidget(src_group)

        saved_src = self._settings.get("i2i_source", "")
        if saved_src and Path(saved_src).exists():
            self._src_slot.set_image(saved_src, copy=False)

        # Prompt (optional)
        prompt_group = QGroupBox("Prompt  (optional)")
        prompt_layout = QVBoxLayout(prompt_group)
        self._prompt = QTextEdit()
        self._prompt.setPlaceholderText(
            "Optional — describe the changes you want.\n"
            "Leave blank to keep the workflow's own prompt."
        )
        self._prompt.setPlainText(self._settings.get("i2i_prompt", ""))
        self._prompt.setFixedHeight(90)
        self._prompt.textChanged.connect(self._save_state)
        prompt_layout.addWidget(self._prompt)
        left.addWidget(prompt_group)

        # Output size
        size_group = QGroupBox("Output Size")
        size_layout = QVBoxLayout(size_group)
        self._size_combo = QComboBox()
        for label, w, h in SIZE_PRESETS:
            self._size_combo.addItem(label, (w, h))
        saved_size = tuple(self._settings.get("i2i_size", [1024, 1024]))
        for i, (_, w, h) in enumerate(SIZE_PRESETS):
            if (w, h) == saved_size:
                self._size_combo.setCurrentIndex(i)
                break
        self._size_combo.currentIndexChanged.connect(self._save_state)
        size_layout.addWidget(self._size_combo)
        left.addWidget(size_group)

        # Strength (denoise)
        strength_group = QGroupBox("Variation Strength  (denoise)")
        strength_inner = QHBoxLayout(strength_group)
        self._strength = QSlider(Qt.Orientation.Horizontal)
        self._strength.setRange(5, 100)
        self._strength.setValue(self._settings.get("i2i_strength", 60))
        self._strength_lbl = QLabel(f"{self._strength.value() / 100:.2f}")
        self._strength_lbl.setFixedWidth(38)
        self._strength_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._strength_lbl.setStyleSheet(f"color:{ACCENT}; font-weight:bold;")
        self._strength.valueChanged.connect(
            lambda v: (self._strength_lbl.setText(f"{v / 100:.2f}"), self._save_state()))
        strength_inner.addWidget(self._strength)
        strength_inner.addWidget(self._strength_lbl)
        hint = QLabel("Low = subtle variation  ·  High = mostly new image")
        hint.setStyleSheet(f"color:{FG_DIM}; font-size:8pt;")
        left.addWidget(strength_group)
        left.addWidget(hint)

        # Steps + Seed
        params_row = QHBoxLayout()

        steps_group = QGroupBox("Steps")
        steps_inner = QHBoxLayout(steps_group)
        self._steps = QSlider(Qt.Orientation.Horizontal)
        self._steps.setRange(1, 60)
        self._steps.setValue(self._settings.get("i2i_steps", 20))
        self._steps_lbl = QLabel(str(self._steps.value()))
        self._steps_lbl.setFixedWidth(28)
        self._steps_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._steps_lbl.setStyleSheet(f"color:{ACCENT}; font-weight:bold;")
        self._steps.valueChanged.connect(lambda v: (self._steps_lbl.setText(str(v)), self._save_state()))
        steps_inner.addWidget(self._steps)
        steps_inner.addWidget(self._steps_lbl)
        params_row.addWidget(steps_group, stretch=2)

        seed_group = QGroupBox("Seed  (-1 = random)")
        seed_inner = QHBoxLayout(seed_group)
        self._seed = QSpinBox()
        self._seed.setRange(-1, 2147483647)
        self._seed.setValue(-1)
        rand_btn = QPushButton("🎲 Random")
        rand_btn.setObjectName("secondary")
        rand_btn.setFixedHeight(30)
        rand_btn.clicked.connect(lambda: self._seed.setValue(-1))
        seed_inner.addWidget(self._seed)
        seed_inner.addWidget(rand_btn)
        params_row.addWidget(seed_group, stretch=1)
        left.addLayout(params_row)

        # Output folder
        out_group = QGroupBox("Output Folder")
        out_row = QHBoxLayout(out_group)
        self._out_edit = QTextEdit(self._settings.get("i2i_output_dir",
                                   str(Path.home() / "AI_Images")))
        self._out_edit.setFixedHeight(36)
        self._out_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        out_browse = QPushButton("Browse")
        out_browse.setObjectName("secondary")
        out_browse.setFixedHeight(36)
        out_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(out_browse)
        left.addWidget(out_group)

        left.addStretch()

        self._gen_btn = QPushButton("🔄  Generate Variation")
        self._gen_btn.setFixedHeight(50)
        self._gen_btn.setStyleSheet(f"font-size:13pt; background-color:{ACCENT}; border-radius:6px;")
        self._gen_btn.clicked.connect(self._generate)
        left.addWidget(self._gen_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        left.addWidget(self._progress)

        self._status = QLabel("Load a source image and set the variation strength")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color:{FG_DIM}; font-size:9pt;")
        self._status.setWordWrap(True)
        left.addWidget(self._status)

        root.addWidget(left_scroll, stretch=1)

        self._preview_panel = PreviewPanel()
        root.addWidget(self._preview_panel, stretch=2)

    def _on_workflow_picked(self, _index: int):
        """Picking a workflow loads its own step count (28 for Flux.2, 8 for
        Turbo, 4 for Qwen Lightning): the slider always overrides the file,
        so a value left over from another workflow would run silently wrong."""
        steps = _workflow_steps(self._wf_combo.currentData())
        if steps:
            self._steps.setValue(steps)
        self._save_state()

    def _reload_workflows(self):
        self._wf_combo.clear()
        workflows = sorted(WORKFLOWS_DIR.glob("i2i_*.json"))
        for wf in workflows:
            self._wf_combo.addItem(wf.stem.replace("_", " ").replace("i2i ", ""), str(wf))
        if not workflows:
            self._wf_combo.addItem("No workflows found — add i2i_*.json to Comfy_Workflows/", "")
        saved_wf = self._settings.get("i2i_workflow", "")
        for i in range(self._wf_combo.count()):
            if self._wf_combo.itemData(i) == saved_wf:
                self._wf_combo.setCurrentIndex(i)
                break

    def _save_state(self):
        if not hasattr(self, '_out_edit'):
            return
        self._settings["i2i_prompt"] = self._prompt.toPlainText()
        self._settings["i2i_steps"] = self._steps.value()
        self._settings["i2i_strength"] = self._strength.value()
        self._settings["i2i_workflow"] = self._wf_combo.currentData() or ""
        self._settings["i2i_size"] = list(self._size_combo.currentData() or (1024, 1024))
        self._settings["i2i_source"] = self._src_slot.path or ""
        self._settings["i2i_output_dir"] = self._out_edit.toPlainText().strip()
        save_settings(self._settings)

    def _browse_output(self):
        f = QFileDialog.getExistingDirectory(self, "Select output folder",
                                              self._out_edit.toPlainText().strip())
        if f:
            self._out_edit.setPlainText(f)
            self._settings["i2i_output_dir"] = f
            save_settings(self._settings)

    def set_source_image(self, path: str):
        """Called from the Library's Variations button."""
        if path and Path(path).exists():
            self._src_slot.set_image(path, copy=False)
            self._status.setText(f"Source: {Path(path).name}")

    def is_busy(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def _generate(self):
        if self.is_busy():
            return

        workflow_path = self._wf_combo.currentData()
        prompt = self._prompt.toPlainText().strip()
        out = self._out_edit.toPlainText().strip()
        src = self._src_slot.path

        if not workflow_path or not Path(workflow_path).exists():
            self._status.setText("Select a valid workflow (i2i_*.json).")
            return
        if not src or not Path(src).exists():
            self._status.setText("Load a source image.")
            return
        if not out:
            self._status.setText("Select an output folder.")
            return
        self._save_state()
        self._host.before_run([workflow_path], lambda: self._launch(workflow_path, prompt, out, src))

    def _launch(self, workflow_path: str, prompt: str, out: str, src: str):
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        import random
        seed = self._seed.value()
        if seed < 0:
            seed = random.randint(0, 2**31)

        denoise = self._strength.value() / 100
        workflow = _patch_workflow_i2i(workflow, prompt, seed,
                                       self._steps.value(), denoise)

        w, h = self._size_combo.currentData()

        self._active_job = {
            "prompt": prompt,
            "workflow_path": workflow_path,
            "size": [w, h],
            "steps": self._steps.value(),
            "seed": seed,
            "strength": denoise,
            "source": src,
        }

        url = self._host.server_url()
        if not url:
            self._status.setText(NO_SERVER_MSG)
            return
        self._gen_btn.setEnabled(False)
        self._progress.setValue(0)
        self._preview_panel.set_message("Generating variation...")
        self._worker = EditorWorker(url, workflow, Path(out), [src], (w, h))

        self._worker.status.connect(self._status.setText)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._host.run_started(self._worker)
        self._worker.start()

    def _on_done(self, path: str):
        self._gen_btn.setEnabled(True)
        self._status.setText(f"Done! {Path(path).name}")
        self._preview_panel.show_image(path)
        job = self._active_job or {}
        add_history_entry({
            "path": str(path),
            "tab": "i2i",
            "prompt": job.get("prompt", ""),
            "workflow": job.get("workflow_path", ""),
            "size": job.get("size", []),
            "steps": job.get("steps", 0),
            "seed": job.get("seed", -1),
            "strength": job.get("strength", 0),
            "source": job.get("source", ""),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        self._host.run_ended()

    def _on_error(self, msg: str):
        self._gen_btn.setEnabled(True)
        self._progress.setValue(0)
        self._status.setText("Error — see preview panel")
        self._preview_panel.set_message(f"Error:\n{msg[:400]}")
        self._host.run_ended()

    def apply_history(self, entry: dict):
        self._prompt.setPlainText(entry.get("prompt", ""))
        steps = entry.get("steps")
        if isinstance(steps, int) and steps > 0:
            self._steps.setValue(steps)
        seed = entry.get("seed")
        if isinstance(seed, int):
            self._seed.setValue(seed)
        strength = entry.get("strength")
        if isinstance(strength, (int, float)) and strength > 0:
            self._strength.setValue(int(strength * 100))
        size = entry.get("size") or []
        if len(size) == 2:
            for i in range(self._size_combo.count()):
                if self._size_combo.itemData(i) == tuple(size):
                    self._size_combo.setCurrentIndex(i)
                    break
        wf = entry.get("workflow", "")
        for i in range(self._wf_combo.count()):
            if self._wf_combo.itemData(i) == wf:
                self._wf_combo.setCurrentIndex(i)
                break
        src = entry.get("source", "")
        if src and Path(src).exists():
            self._src_slot.set_image(src, copy=False)
        self._save_state()


# ------------------------------------------------------------------ #
# Tab 4 — Library
# ------------------------------------------------------------------ #

class LibraryTab(QWidget):
    recall_requested = pyqtSignal(dict)
    variations_requested = pyqtSignal(str)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._cards: list[ThumbnailCard] = []
        self._selected_card: ThumbnailCard | None = None
        self._all_paths: list[str] = []
        self._selected_entry: dict | None = None
        self._compare_a: str | None = None
        self._build_ui()

    def _favorites(self) -> list[str]:
        favs = self._settings.get("lib_favorites", [])
        return favs if isinstance(favs, list) else []

    def _is_fav(self, path: str) -> bool:
        return str(path) in self._favorites()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setObjectName("secondary")
        refresh_btn.clicked.connect(self.refresh)
        filter_lbl = QLabel("Filter:")
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filename...")
        self._filter_edit.setFixedWidth(200)
        self._filter_edit.textChanged.connect(self._apply_filter)
        clear_filter_btn = QPushButton("✕ Clear")
        clear_filter_btn.setObjectName("secondary")
        clear_filter_btn.setFixedHeight(28)
        clear_filter_btn.setToolTip("Clear filter")
        clear_filter_btn.clicked.connect(lambda: self._filter_edit.clear())
        self._fav_only_chk = QCheckBox("★ Favorites only")
        self._fav_only_chk.setStyleSheet(f"color:{FG}; font-size:9pt;")
        self._fav_only_chk.stateChanged.connect(self._apply_filter)
        self._count_lbl = QLabel("0 images")
        self._count_lbl.setStyleSheet(f"color:{FG_DIM}; font-size:9pt;")
        toolbar.addWidget(refresh_btn)
        toolbar.addSpacing(12)
        toolbar.addWidget(filter_lbl)
        toolbar.addWidget(self._filter_edit)
        toolbar.addWidget(clear_filter_btn)
        toolbar.addSpacing(12)
        toolbar.addWidget(self._fav_only_chk)
        toolbar.addStretch()
        toolbar.addWidget(self._count_lbl)
        root.addLayout(toolbar)

        # Split: grid left | preview right (draggable, like the other apps)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # Left — scrollable thumbnail grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet(f"background-color: {BG};")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(8)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._grid_widget)
        split.addWidget(self._scroll)

        # Right — preview + info + actions
        right_widget = QWidget()
        right_widget.setMinimumWidth(370)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._lib_preview = PreviewPanel()
        self._lib_preview.set_message("Select an image")
        right_layout.addWidget(self._lib_preview, stretch=1)

        info_group = QGroupBox("Info")
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(3)
        self._meta_name = QLabel("—")
        self._meta_name.setWordWrap(True)
        self._meta_name.setStyleSheet(f"font-size:9pt; color:{FG};")
        self._meta_date = QLabel("—")
        self._meta_date.setStyleSheet(f"font-size:8pt; color:{FG_DIM};")
        self._meta_size = QLabel("—")
        self._meta_size.setStyleSheet(f"font-size:8pt; color:{FG_DIM};")
        self._meta_prompt = QLabel("—")
        self._meta_prompt.setWordWrap(True)
        self._meta_prompt.setMaximumHeight(76)
        self._meta_prompt.setStyleSheet(f"font-size:8pt; color:{FG_DIM}; font-style:italic;")
        info_layout.addWidget(self._meta_name)
        info_layout.addWidget(self._meta_date)
        info_layout.addWidget(self._meta_size)
        info_layout.addWidget(self._meta_prompt)
        right_layout.addWidget(info_group)

        fav_row = QHBoxLayout()
        self._lib_fav_btn = QPushButton("☆  Favorite")
        self._lib_fav_btn.setObjectName("secondary")
        self._lib_fav_btn.setEnabled(False)
        self._lib_fav_btn.clicked.connect(self._toggle_favorite)
        self._lib_compare_btn = QPushButton("⇆  Set A")
        self._lib_compare_btn.setObjectName("secondary")
        self._lib_compare_btn.setEnabled(False)
        self._lib_compare_btn.setToolTip(
            "Select an image and click to set it as A;\n"
            "then select another image and click again to compare."
        )
        self._lib_compare_btn.clicked.connect(self._compare_clicked)
        fav_row.addWidget(self._lib_fav_btn)
        fav_row.addWidget(self._lib_compare_btn)
        right_layout.addLayout(fav_row)

        recall_row = QHBoxLayout()
        self._lib_recall_btn = QPushButton("↩  Recall Prompt")
        self._lib_recall_btn.setObjectName("secondary")
        self._lib_recall_btn.setEnabled(False)
        self._lib_recall_btn.setToolTip("Restore this image's prompt and settings to the tab that generated it")
        self._lib_recall_btn.clicked.connect(self._recall_prompt)
        self._lib_vary_btn = QPushButton("🔄  Variations")
        self._lib_vary_btn.setObjectName("secondary")
        self._lib_vary_btn.setEnabled(False)
        self._lib_vary_btn.setToolTip("Send this image to the Variations tab")
        self._lib_vary_btn.clicked.connect(self._send_to_variations)
        recall_row.addWidget(self._lib_recall_btn)
        recall_row.addWidget(self._lib_vary_btn)
        right_layout.addLayout(recall_row)

        action_row = QHBoxLayout()
        self._lib_open_btn = QPushButton("📁  Open Folder")
        self._lib_open_btn.setObjectName("secondary")
        self._lib_open_btn.setEnabled(False)
        self._lib_open_btn.clicked.connect(self._open_folder)
        self._lib_delete_btn = QPushButton("🗑  Delete")
        self._lib_delete_btn.setObjectName("danger")
        self._lib_delete_btn.setEnabled(False)
        self._lib_delete_btn.clicked.connect(self._delete_selected)
        action_row.addWidget(self._lib_open_btn)
        action_row.addWidget(self._lib_delete_btn)
        right_layout.addLayout(action_row)

        split.addWidget(right_widget)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 500])
        root.addWidget(split, stretch=1)

    def refresh(self):
        dirs = []
        for key in ("t2i_output_dir", "edit_output_dir", "i2i_output_dir"):
            d = self._settings.get(key, "")
            if d and Path(d).exists():
                dirs.append(Path(d))

        imgs: list[Path] = []
        for d in dirs:
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                imgs.extend(d.glob(ext))

        # Deduplicate and sort newest first
        seen: set[str] = set()
        unique: list[Path] = []
        for p in imgs:
            if str(p) not in seen:
                seen.add(str(p))
                unique.append(p)
        unique.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        self._all_paths = [str(p) for p in unique[:200]]
        self._apply_filter()

    def _apply_filter(self):
        query = self._filter_edit.text().lower()
        fav_only = self._fav_only_chk.isChecked()
        filtered = [p for p in self._all_paths
                    if (not query or query in Path(p).name.lower())
                    and (not fav_only or self._is_fav(p))]
        self._rebuild_grid(filtered)

    def _rebuild_grid(self, paths: list[str]):
        for card in self._cards:
            self._grid_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._selected_card = None

        for i, path in enumerate(paths):
            card = ThumbnailCard(path, favorite=self._is_fav(path))
            card.selected_signal.connect(self._on_card_clicked)
            card.double_clicked.connect(self._open_viewer)
            self._cards.append(card)
            row, col = divmod(i, _LIB_COLS)
            self._grid_layout.addWidget(card, row, col)

        self._count_lbl.setText(f"{len(paths)} image{'s' if len(paths) != 1 else ''}")

    def _open_viewer(self, path: str):
        ImageViewerDialog(path, self).exec()

    def _on_card_clicked(self, path: str):
        if self._selected_card:
            self._selected_card.set_selected(False)

        for card in self._cards:
            if card.path == path:
                card.set_selected(True)
                self._selected_card = card
                break

        self._lib_preview.show_image(path)

        p = Path(path)
        self._meta_name.setText(p.name)
        try:
            stat = p.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d  %H:%M:%S")
            size_kb = stat.st_size / 1024
            self._meta_date.setText(f"Modified: {mtime}")
            self._meta_size.setText(f"Size: {size_kb:.1f} KB   ({p.suffix.upper().lstrip('.')})")
        except Exception:
            pass

        # History lookup — prompt display + recall availability
        self._selected_entry = find_history_entry(path)
        if self._selected_entry and self._selected_entry.get("prompt"):
            prompt = self._selected_entry["prompt"].replace("\n", " ")
            if len(prompt) > 220:
                prompt = prompt[:217] + "..."
            self._meta_prompt.setText(f"“{prompt}”")
        elif self._selected_entry:
            self._meta_prompt.setText("(generated — no prompt recorded)")
        else:
            self._meta_prompt.setText("(no generation history for this image)")
        self._lib_recall_btn.setEnabled(self._selected_entry is not None)

        self._lib_fav_btn.setEnabled(True)
        self._lib_fav_btn.setText("★  Unfavorite" if self._is_fav(path) else "☆  Favorite")
        self._lib_compare_btn.setEnabled(True)
        self._update_compare_button()
        self._lib_vary_btn.setEnabled(True)
        self._lib_open_btn.setEnabled(True)
        self._lib_delete_btn.setEnabled(True)

    # ---- Favorites -------------------------------------------------- #

    def _toggle_favorite(self):
        if not self._selected_card:
            return
        path = str(self._selected_card.path)
        favs = self._favorites()
        if path in favs:
            favs.remove(path)
        else:
            favs.append(path)
        self._settings["lib_favorites"] = favs
        save_settings(self._settings)
        self._selected_card.set_favorite(path in favs)
        self._lib_fav_btn.setText("★  Unfavorite" if path in favs else "☆  Favorite")
        if self._fav_only_chk.isChecked():
            self._apply_filter()

    # ---- A/B compare ------------------------------------------------- #

    def _update_compare_button(self):
        if self._compare_a:
            self._lib_compare_btn.setText("⇆  Compare with A")
        else:
            self._lib_compare_btn.setText("⇆  Set A")

    def _compare_clicked(self):
        if not self._selected_card:
            return
        path = self._selected_card.path
        if not self._compare_a:
            self._compare_a = path
            self._update_compare_button()
            self._count_lbl.setText(f"A = {Path(path).name}")
            return
        if path == self._compare_a:
            # Clicking again on A cancels the pending compare
            self._compare_a = None
            self._update_compare_button()
            return
        dlg = CompareDialog(self._compare_a, path, self)
        self._compare_a = None
        self._update_compare_button()
        dlg.exec()

    # ---- Prompt recall / variations ---------------------------------- #

    def _recall_prompt(self):
        if self._selected_entry:
            self.recall_requested.emit(self._selected_entry)

    def _send_to_variations(self):
        if self._selected_card:
            self.variations_requested.emit(self._selected_card.path)

    def _open_folder(self):
        if self._selected_card:
            subprocess.Popen(f'explorer "{Path(self._selected_card.path).parent}"')

    def _delete_selected(self):
        if not self._selected_card:
            return
        path = self._selected_card.path
        reply = QMessageBox.question(
            self, "Delete Image",
            f"Permanently delete:\n{Path(path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                Path(path).unlink()
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete file:\n{e}")

    def showEvent(self, event):
        super().showEvent(event)
        if not self._all_paths:
            self.refresh()


# ------------------------------------------------------------------ #
# Main window
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    """Owns the one ComfyUI connection, the RunPod pod (PodControl, copied
    from the ComfyUI Video Creator) and the model check & sync.

    It is also the "RunHost" the generating tabs talk to. A tab only asks
    server_url(), hands its run to before_run() (spend limit + the pod has the
    workflow's models) and reports run_started() / run_ended(), which keep
    the idle-stop countdown and the alert sound right.
    """

    def __init__(self):
        super().__init__()
        global CONFIG
        CONFIG = ConfigManager(SETTINGS_FILE)
        self._config = CONFIG
        self._settings = CONFIG.data          # the tabs read/write this dict directly
        self._live_workers: set[QThread] = set()

        # Model check & sync: (workflow, server) pairs whose models were
        # confirmed on the pod this session, so a run checks once, not every time.
        self._models_ok: set[tuple[str, str]] = set()
        self._pending = None  # (proceed, on_drop, key) while a model check/sync runs
        self._model_check: model_sync.ModelCheckWorker | None = None
        self._transfer: model_sync.TransferWorker | None = None
        self._transfer_dlg: QProgressDialog | None = None
        self._xfer_mark: tuple[str, float, int] = ("", 0.0, 0)   # (label, t0, bytes) for the rate readout
        self._pod_only_declined: set[str] = set()                # "run on the pod" answers, this session

        self.setWindowTitle(f"AI Image Studio  v{VERSION}")
        self.setMinimumSize(800, 600)
        self.resize(1400, 900)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("AI Image Studio")
        title.setStyleSheet(f"font-size:18pt; font-weight:bold; color:{ACCENT};")
        header.addWidget(title)
        header.addStretch()
        self._mode_lbl = QLabel("")
        self._mode_lbl.setObjectName("mode_badge")
        header.addWidget(self._mode_lbl)
        header.addSpacing(8)
        # RunPod pod control: spend readout + Start/Stop Pod. It owns
        # everything pod-related; this window only answers "is a run going?".
        self._pod = PodControl(self._config, self._generation_running, self)
        self._pod.server_changed.connect(self._on_server_changed)
        self._pod.log.connect(self._log)
        header.addWidget(self._pod)
        header.addSpacing(8)
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setObjectName("secondary_btn")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        self._tabs = QTabWidget()
        self._t2i_tab     = TextToImageTab(self._settings, self)
        self._compose_tab = SceneComposerTab(self._settings, self)
        self._i2i_tab     = ImageVariationsTab(self._settings, self)
        self._library_tab = LibraryTab(self._settings)
        self._tabs.addTab(self._t2i_tab,     "✨  Text to Image")
        self._tabs.addTab(self._compose_tab, "🎨  Scene Composer")
        self._tabs.addTab(self._i2i_tab,     "🔄  Variations")
        self._tabs.addTab(self._library_tab, "🖼  Library")
        root.addWidget(self._tabs)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._server_lbl = QLabel("")
        self._status.addPermanentWidget(self._server_lbl)

        self._library_tab.recall_requested.connect(self._on_recall)
        self._library_tab.variations_requested.connect(self._on_variations)

        self._on_server_changed()
        # After the window is actually on screen, so the pod prompt has a
        # parent to centre on rather than appearing behind it.
        QTimer.singleShot(200, self._pod.check_on_launch)

    # ---- Tabs ------------------------------------------------------ #

    def _generating_tabs(self):
        return (self._t2i_tab, self._compose_tab, self._i2i_tab)

    def _on_recall(self, entry: dict):
        tab_key = entry.get("tab", "t2i")
        target = {
            "t2i":  self._t2i_tab,
            "edit": self._compose_tab,
            "i2i":  self._i2i_tab,
        }.get(tab_key, self._t2i_tab)
        target.apply_history(entry)
        self._tabs.setCurrentWidget(target)

    def _on_variations(self, path: str):
        self._i2i_tab.set_source_image(path)
        self._tabs.setCurrentWidget(self._i2i_tab)

    def _open_settings(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._on_server_changed()

    # ---- RunHost: what the generating tabs call ------------------- #

    def server_url(self) -> str:
        return self._config.server_url()

    def over_limit(self) -> bool:
        return self._pod.over_limit()

    def before_run(self, workflows: list[str], proceed: Callable[[], None],
                   on_drop: Callable[[], None] | None = None):
        """Run `proceed` once the pod is under its spend limit and every
        workflow's models are confirmed on it (one check per workflow, in
        turn). Local mode and confirmed workflows go straight through."""
        on_drop = on_drop or (lambda: None)
        if self._model_check is not None or self._transfer is not None:
            self._status.showMessage("A model check is still running — try again when it finishes.", 6000)
            return
        if self._spend_limit_blocked():
            on_drop()
            return
        remaining = list(workflows)

        def step():
            if not remaining:
                proceed()
                return
            self._ensure_models(remaining.pop(0), step, on_drop)

        step()

    def run_started(self, worker: QThread):
        """A tab started a worker: hold it until its thread really ends (a
        tab replaces self._worker between queue jobs) and stop counting idle."""
        self._live_workers.add(worker)
        worker.finished.connect(self._on_run_thread_finished)
        self._pod.cancel_idle_timer()

    def run_ended(self):
        """A run (one image, or a whole queue) finished or failed."""
        self._alert()

    # ---- Pod bookkeeping ------------------------------------------ #

    def _generation_running(self) -> bool:
        """PodControl asks this: a running generation or model transfer means
        a spend-limit stop waits and the idle countdown never arms."""
        return (any(t.is_busy() for t in self._generating_tabs())
                or any(w.isRunning() for w in self._live_workers)
                or self._transfer is not None)

    def _on_run_thread_finished(self):
        """A worker thread has really ended (done/error fire while it is
        still winding down). A deferred spend-limit stop lands here, or the
        idle countdown arms — unless another run (the next queued job) has
        already started."""
        worker = self.sender()
        self._live_workers.discard(worker)
        if self._generation_running():
            return
        self._pod.run_finished()
        self._pod.start_idle_timer()

    def _on_server_changed(self):
        """A pod came up (or went away), or Settings changed the server."""
        self._models_ok.clear()  # a different pod's volume may differ
        runpod = self._config.is_runpod()
        url = self.server_url()
        dot = SUCCESS if url else ERROR
        what = "RunPod" if runpod else "Local ComfyUI"
        # Solid light text; the coloured dot carries the state.
        self._mode_lbl.setText(f"<span style='color:{dot}'>●</span> {what}")
        self._server_lbl.setText(f"ComfyUI:  {url or '(not set)'}")

    def _alert(self):
        """The one alert sound (Settings > RunPod), shared with the pod
        chain's "pod found" / "gave up" alerts."""
        if self._config.get("alert_sound_enabled", True):
            alerts.play(self._config.get("alert_sound_path", ""))

    def _spend_limit_blocked(self) -> bool:
        """True (after telling the user) when the pod has hit its spend limit."""
        if not self._pod.over_limit():
            return False
        limit = float(self._config.get("runpod_spend_limit", 0) or 0)
        QMessageBox.warning(
            self, "Spend limit reached",
            f"This pod has hit the ${limit:.2f} session limit, so no new runs are "
            "being started. It will stop once the current run finishes.\n\n"
            "Raise the limit in Settings > RunPod to keep going.")
        return True

    def _log(self, msg: str):
        """Pod and model-sync progress: status bar now, activity.log for later
        (a transfer that misbehaves overnight should leave evidence)."""
        self._status.showMessage(msg, 15000)
        try:
            with open(APP_DIR / "activity.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        except OSError:
            pass

    # ---- Model check & sync (RunPod) — copied from Style Randomizer ---- #

    def _ensure_models(self, wf_path: str, proceed, on_drop):
        """Run `proceed` once the workflow's model files are confirmed on the
        pod (copied there / back here if they were not). Local mode, the check
        switched off, or an already-confirmed (workflow, server) pair go
        straight through. `on_drop` runs when the user backs out."""
        cfg = self._config.get_all()
        if not (self._config.is_runpod() and model_sync.check_enabled(cfg)):
            proceed()
            return
        key = (str(wf_path), self.server_url())
        if key in self._models_ok:
            proceed()
            return
        try:
            refs = model_sync.models_in_workflow(json.loads(Path(wf_path).read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            self._log(f"Model check: couldn't read {Path(wf_path).name} ({e}) - the run will report it")
            proceed()
            return
        if not refs:
            self._models_ok.add(key)
            proceed()
            return
        self._pending = (proceed, on_drop, key)
        self._pod.cancel_idle_timer()
        self._log(f"Model check: comparing {len(refs)} model file(s) for {Path(wf_path).name} "
                  "between the local models folder and the pod volume…")
        self._model_check = model_sync.ModelCheckWorker(cfg, list(refs))
        self._model_check.done.connect(self._on_model_plan)
        self._model_check.finished.connect(self._model_check_finished)
        self._model_check.start()

    def _model_check_finished(self):
        self._model_check = None

    def _model_release(self):
        proceed, _drop, key = self._pending
        self._pending = None
        self._models_ok.add(key)
        proceed()

    def _model_release_unchecked(self):
        """Run without the models confirmed: do not remember it, so the next
        run asks again."""
        proceed, _drop, _key = self._pending
        self._pending = None
        proceed()

    def _model_drop(self, why: str):
        _proceed, on_drop, _key = self._pending
        self._pending = None
        self._log(f"Run not started - {why}")
        on_drop()

    def _on_model_plan(self, plan: model_sync.SyncPlan):
        if plan.error:
            ans = QMessageBox.question(
                self, "Couldn't check the pod's models",
                f"The pod volume could not be listed:\n\n{plan.error}\n\n"
                "Start the run anyway? A model the pod lacks will fail on the server.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            self._log(f"Model check failed: {plan.error}")
            if ans == QMessageBox.StandardButton.Yes:
                self._model_release_unchecked()
            else:
                self._model_drop("model check failed (see Settings > Models)")
            return
        for ref, actual in plan.case_mismatch.items():
            self._log(f"Model check: {ref.rel} is spelled {actual} on disk — the Linux pod is case-sensitive")
        for ref, (lsize, rsize) in plan.size_mismatch.items():
            self._log(f"Model check: {ref.rel} differs in size (local {model_sync.fmt_size(lsize)}, pod {model_sync.fmt_size(rsize)}) — not touched")

        # Models the pod has but this PC doesn't. The pod run is fine without
        # them, so say exactly that and offer the download for local use —
        # a 35 GB text encoder must never start pulling down unannounced.
        offered = [j for j in plan.optional_downloads if j.ref.rel not in self._pod_only_declined]
        if offered:
            total = sum(j.size for j in offered)
            names = "\n".join(f"    • {j.ref.kind}: {j.ref.rel}  ({model_sync.fmt_size(j.size)})" for j in offered)
            self._log(f"Model check: {len(offered)} model(s) are on the pod but not on this PC ({model_sync.fmt_size(total)})")
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Model missing locally")
            box.setText(f"{len(offered)} model file(s) exist on the pod but not on this PC "
                        f"({model_sync.fmt_size(total)}):")
            box.setInformativeText(
                names + "\n\n"
                "This run goes to the pod, which already has them, so it can start right away.\n"
                "You only need the download if you also want to run this workflow on local ComfyUI.\n\n"
                f"Download to {plan.local_root}? The download runs first, then the run starts.\n"
                "(Settings > Models can download these automatically without asking.)")
            dl = box.addButton("Download, then run", QMessageBox.ButtonRole.AcceptRole)
            pod = box.addButton("Run on the pod without downloading", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(pod)
            box.exec()
            if box.clickedButton() is dl:
                plan.downloads.extend(offered)
                self._log(f"Model check: downloading {len(offered)} pod-only model(s) to this PC first")
            elif box.clickedButton() is pod:
                for j in offered:
                    self._pod_only_declined.add(j.ref.rel)
                self._log("Model check: running on the pod without the local copies (not asked again this session)")
            else:
                self._model_drop("cancelled at the missing-locally prompt")
                return

        if plan.clean and not plan.downloads:
            self._log("Model check: every model file the run needs is on the pod")
            self._model_release()
            return

        lines = []
        if plan.uploads:
            lines.append(f"Upload to the pod ({model_sync.fmt_size(sum(j.size for j in plan.uploads))}):")
            lines += [f"    ↑ {j.label}  ({model_sync.fmt_size(j.size)})" for j in plan.uploads]
        if plan.downloads:
            lines.append(f"Download to {plan.local_root} ({model_sync.fmt_size(sum(j.size for j in plan.downloads))}):")
            lines += [f"    ↓ {j.label}  ({model_sync.fmt_size(j.size)})" for j in plan.downloads]
        if plan.nowhere:
            lines.append("Not found on the pod OR locally — the run will fail on the server unless the pod has them outside the volume:")
            lines += [f"    ✗ {r.kind}: {r.rel}" for r in plan.nowhere]
        body = "\n".join(lines)
        for ln in lines:
            self._log("Model check: " + ln.strip())

        if plan.jobs:
            if plan.uploads or plan.nowhere:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("Sync models with the pod?")
                box.setText(f"{len(plan.jobs)} model file(s) to copy "
                            f"({model_sync.fmt_size(plan.total_bytes)} to move).")
                box.setInformativeText(body + "\n\nCopy them now? The run starts automatically once every file is verified.")
                yes = box.addButton("Sync, then run", QMessageBox.ButtonRole.AcceptRole)
                anyway = box.addButton("Run without syncing", QMessageBox.ButtonRole.DestructiveRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.setDefaultButton(yes)
                box.exec()
                if box.clickedButton() is yes:
                    self._start_transfer(plan)
                elif box.clickedButton() is anyway:
                    self._model_release_unchecked()
                else:
                    self._model_drop("model sync cancelled")
                return
            self._start_transfer(plan)        # downloads the user just said yes to
            return

        ans = QMessageBox.question(
            self, "Models not found",
            body + "\n\nStart the run anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans == QMessageBox.StandardButton.Yes:
            self._model_release_unchecked()
        else:
            self._model_drop("model files missing on both sides")

    def _start_transfer(self, plan: model_sync.SyncPlan):
        ups, downs = len([j for j in plan.jobs if j.direction == "upload"]), len([j for j in plan.jobs if j.direction == "download"])
        size = model_sync.fmt_size(plan.total_bytes)
        title = (f"Downloading {downs} model file(s) to this PC — {size} total" if not ups else
                 f"Uploading {ups} model file(s) to the pod — {size} total" if not downs else
                 f"Syncing models — {ups} up, {downs} down — {size} total")
        self._xfer_mark = ("", time.time(), 0)
        self._transfer_dlg = QProgressDialog("Starting…", "Cancel", 0, 1000, self)
        self._transfer_dlg.setWindowTitle(title)
        self._transfer_dlg.setMinimumWidth(560)
        self._transfer_dlg.setMinimumDuration(0)
        self._transfer_dlg.setAutoClose(False)
        self._transfer_dlg.setAutoReset(False)
        self._transfer_dlg.canceled.connect(self._cancel_transfer)
        self._transfer = model_sync.TransferWorker(self._config.get_all(), plan.jobs)
        self._transfer.log.connect(self._log)
        self._transfer.progress.connect(self._on_transfer_progress)
        self._transfer.finished_ok.connect(self._on_transfer_done)
        self._transfer.finished.connect(self._transfer_finished)
        self._transfer.start()

    def _cancel_transfer(self):
        if self._transfer is not None:
            self._transfer.cancel()
            if self._transfer_dlg is not None:
                self._transfer_dlg.setLabelText("Cancelling after the current file…")

    def _on_transfer_progress(self, done: int, total: int, label: str, files_done: int, files_total: int):
        if self._transfer_dlg is None:
            return
        now = time.time()
        mark_label, t0, b0 = self._xfer_mark
        if label != mark_label:                 # new file (or a retry): rate restarts
            self._xfer_mark = (label, now, done)
            t0, b0 = now, done
        elapsed = now - t0
        rate = (done - b0) / elapsed if elapsed > 0.5 else 0.0
        eta = model_sync.fmt_eta((total - done) / rate) if rate > 0 else "—"
        self._transfer_dlg.setValue(int(done * 1000 / total) if total else 0)
        self._transfer_dlg.setLabelText(
            f"{label}\n"
            f"{model_sync.fmt_size(done)} of {model_sync.fmt_size(total)}"
            + (f"   ·   {model_sync.fmt_rate(rate)}   ·   about {eta} left" if rate > 0 else "")
            + f"\nfile {min(files_done + 1, files_total)} of {files_total}   ·   Cancel stops the transfer now")

    def _on_transfer_done(self, errors: list):
        if self._transfer_dlg is not None:
            self._transfer_dlg.close()
            self._transfer_dlg = None
        if errors:
            text = "\n".join(f"• {name}: {err}" for name, err in errors[:12])
            QMessageBox.critical(self, "Model sync failed",
                                 f"{len(errors)} file(s) did not transfer:\n\n{text}\n\nThe run was not started.")
            self._model_drop("model sync failed")
            return
        self._log("Model sync: every file verified - starting the run")
        self._model_release()

    def _transfer_finished(self):
        self._transfer = None

    # ---- Quit ------------------------------------------------------ #

    def closeEvent(self, event):
        # Ask about any pod this session is connected to - one adopted from the
        # launch chooser too, not only one this app started. Asked first, so
        # Cancel leaves everything running.
        stop_pod = False
        if self._pod.pod_id and self._config.get("runpod_auto_stop_on_exit", True):
            ans = QMessageBox.question(
                self, "Stop the pod?",
                f"RunPod pod {self._pod.pod_id} is still running.\n\n"
                "Yes — stop the pod, then quit. GPU billing ends.\n"
                "No — quit and leave the pod running. It keeps billing until you "
                "stop it in the RunPod console. Can reconnect if still running on "
                "next app launch.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            stop_pod = ans == QMessageBox.StandardButton.Yes
            if not stop_pod:
                self._pod.leave_running()
        if self._transfer is not None:
            self._transfer.cancel()
            self._transfer.wait(5000)
        if stop_pod:
            self._pod.shutdown()
        save_settings()
        event.accept()


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import traceback
    log_file = APP_DIR / "error_log.txt"
    try:
        # Own taskbar identity so Windows doesn't group us under python.exe.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AIImageStudio.App.1")
        except Exception:
            pass
        app = QApplication(sys.argv)
        app.setApplicationName("AI Image Studio")
        # The icon is bundled read-only data (PyInstaller's unpack folder when
        # frozen); APP_DIR is the EXE folder and may hold a stale copy.
        from PyQt6.QtGui import QIcon
        _icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app_icon.ico"
        _icon = QIcon(str(_icon_path)) if _icon_path.exists() else QIcon()
        app.setWindowIcon(_icon)
        window = MainWindow()
        window.setWindowIcon(_icon)
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        with open(log_file, "w") as f:
            f.write(traceback.format_exc())
        raise
