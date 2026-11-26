from datetime import datetime
from pathlib import Path
import json
import re
import subprocess
import os
import zlib

from PIL import Image, ImageOps

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QLineEdit,
    QProgressBar, QListWidget, QListWidgetItem, QGroupBox,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QSpinBox,
    QDialog, QMessageBox, QAbstractItemView, QFileDialog, QCheckBox, QComboBox,
    QProgressDialog, QTextEdit, QDialogButtonBox
)

from PyQt6.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QImage, QColor

from config import ConfigManager
from batch_worker import BatchChainWorker, validate_batch_chain_dir
from lora_sync import (
    CFG_LORA_CHECK, collect_chain_loras, check_local_loras, s3_configured,
    RemoteLoraCheckWorker, LoraUploadWorker, LoraUploadJob,
)
from ui.styles import STYLESHEET, COLORS
from ui.video_player import VideoPlayerDialog
from ui.settings_dialog import SettingsDialog
from ui.segment_editor import SegmentEditorDialog
from ui.generate_tab import GenerateTab
from ui.prompt_writer_tab import PromptWriterTab
from ui.video_settings_dialog import VideoSettingsDialog
from ui.widgets import ThumbnailGrid, THUMB_SIZE
from ui.pod_control import PodControl
import alerts

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
MAX_SEGMENTS = 10

# Batch-run timestamp the worker appends to stitched filenames
# (photo_20260709_141530.mp4) — strip it to recover the source image stem.
RUN_STAMP_RE = re.compile(r"_\d{8}_\d{6}$")


# ------------------------------------------------------------------ #
# Background loaders
# ------------------------------------------------------------------ #

class ImageLoaderThread(QThread):
    """Loads image thumbnails from a persistent `thumbnails` cache folder
    inside the image directory (like the Library does for videos). On each
    run it syncs the cache: generates thumbs for new/changed images, removes
    thumbs whose source image is gone."""
    image_ready = pyqtSignal(QImage, str, str)
    progress = pyqtSignal(int, int)
    finished_loading = pyqtSignal(int)

    def __init__(self, input_dir: Path, sort_key=None, sort_reverse: bool = False):
        super().__init__()
        self._input_dir = input_dir
        self._sort_key = sort_key or (lambda p: p.name.lower())
        self._sort_reverse = sort_reverse
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _thumb_name(self, img_path: Path) -> str:
        # Relative-path hash keeps same-named images in subfolders distinct
        rel = str(img_path.relative_to(self._input_dir))
        return f"{img_path.stem}_{zlib.crc32(rel.lower().encode()):08x}.jpg"

    def run(self):
        thumb_dir = self._input_dir / "thumbnails"
        try:
            thumb_dir.mkdir(exist_ok=True)
        except OSError:
            thumb_dir = None

        images = sorted(
            (p for p in self._input_dir.rglob("*")
             if p.suffix.lower() in IMAGE_EXTS
             and (thumb_dir is None or thumb_dir not in p.parents)),
            key=self._sort_key,
            reverse=self._sort_reverse,
        )

        # Sync cache: drop thumbnails whose source image no longer exists
        if thumb_dir is not None:
            valid = {self._thumb_name(p) for p in images}
            for t in thumb_dir.glob("*.jpg"):
                if t.name not in valid:
                    try:
                        t.unlink()
                    except OSError:
                        pass

        total = len(images)
        loaded = 0
        for img_path in images:
            if self._cancelled:
                return
            img = QImage()
            thumb_path = thumb_dir / self._thumb_name(img_path) if thumb_dir else None
            if (thumb_path and thumb_path.exists()
                    and thumb_path.stat().st_mtime >= img_path.stat().st_mtime):
                img = QImage(str(thumb_path))
            if img.isNull():
                try:
                    pil_img = Image.open(img_path)
                    pil_img = ImageOps.exif_transpose(pil_img)
                    pil_img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                    pil_img = pil_img.convert("RGB")
                    if thumb_path:
                        try:
                            pil_img.save(thumb_path, "JPEG", quality=88)
                        except OSError:
                            pass
                    data = pil_img.convert("RGBA").tobytes("raw", "RGBA")
                    img = QImage(data, pil_img.width, pil_img.height,
                                 QImage.Format.Format_RGBA8888).copy()
                except Exception:
                    img = QImage(str(img_path))
                    if not img.isNull():
                        img = img.scaled(THUMB_SIZE, THUMB_SIZE,
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            if img.isNull():
                continue
            rel = img_path.relative_to(self._input_dir)
            label = str(rel) if rel.parent != Path(".") else img_path.name
            self.image_ready.emit(img, str(rel), label)
            loaded += 1
            self.progress.emit(loaded, total)
        self.finished_loading.emit(loaded)


class VideoLoaderThread(QThread):
    """Loads video thumbnails from cache; generates missing ones via FFmpeg."""
    video_ready = pyqtSignal(QImage, str, str)  # image, full_path, label
    progress = pyqtSignal(int, int)              # current, total (thumbnail generation)
    thumbnails_needed = pyqtSignal(int)          # fires with count before generation starts
    finished_loading = pyqtSignal(int)

    def __init__(self, video_dir: Path, ffmpeg: str, sort_key=None, sort_reverse: bool = False):
        super().__init__()
        self._video_dir = video_dir
        self._ffmpeg = ffmpeg
        self._sort_key = sort_key or (lambda p: p.name.lower())
        self._sort_reverse = sort_reverse
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        thumb_dir = self._video_dir / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)

        videos = sorted(
            (p for p in self._video_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS),
            key=self._sort_key,
            reverse=self._sort_reverse,
        )

        # Phase 1: generate any missing thumbnails
        missing = [
            (v, thumb_dir / (v.stem + ".jpg"))
            for v in videos
            if not (thumb_dir / (v.stem + ".jpg")).exists()
        ]
        if missing:
            self.thumbnails_needed.emit(len(missing))
            for i, (vid_path, thumb_path) in enumerate(missing, 1):
                if self._cancelled:
                    return
                self._extract_frame(vid_path, thumb_path)
                self.progress.emit(i, len(missing))

        # Phase 2: load all into grid
        loaded = 0
        for vid_path in videos:
            if self._cancelled:
                return
            thumb_path = thumb_dir / (vid_path.stem + ".jpg")
            img = QImage(str(thumb_path))
            if img.isNull():
                # Thumbnail generation failed (usually a broken ffmpeg path)
                # — show the video anyway with a flat placeholder tile.
                # Skipping it here made whole folders look empty with no
                # hint that anything was wrong.
                img = QImage(THUMB_SIZE, THUMB_SIZE, QImage.Format.Format_RGB32)
                img.fill(QColor("#2a2a3e"))
            else:
                img = img.scaled(THUMB_SIZE, THUMB_SIZE,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self.video_ready.emit(img, str(vid_path), vid_path.name)
            loaded += 1
        self.finished_loading.emit(loaded)

    def _extract_frame(self, vid_path: Path, thumb_path: Path):
        try:
            subprocess.run(
                [self._ffmpeg, "-y", "-i", str(vid_path),
                 "-vframes", "1", "-q:v", "3", str(thumb_path)],
                capture_output=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass


# ------------------------------------------------------------------ #
# Segment dot
# ------------------------------------------------------------------ #

class SegmentDot(QLabel):
    double_clicked = pyqtSignal(int)

    def __init__(self, number: int):
        super().__init__(f" {number} ")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(34, 34)
        self.setToolTip("Double-click to edit workflow")
        self._number = number
        self.set_pending()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self._number)

    def _apply(self, bg: str, fg: str):
        self.setStyleSheet(
            f"background-color:{bg}; color:{fg}; border-radius:17px;"
            f" font-weight:bold; font-size:10pt;"
        )

    def set_pending(self): self._apply(COLORS['seg_pending'], COLORS['fg_dim'])
    def set_active(self):  self._apply(COLORS['seg_active'], '#000000')
    def set_done(self):    self._apply(COLORS['seg_done'], '#000000')


# ------------------------------------------------------------------ #
# Video converter
# ------------------------------------------------------------------ #

CONVERT_PRESETS = [
    {
        "label": "AVI — Xvid (widest photo frame compatibility)",
        "ext": ".avi",
        "args": ["-vcodec", "libxvid", "-q:v", "4", "-acodec", "mp3", "-q:a", "4"],
    },
    {
        "label": "MP4 — H.264 Baseline (universal device compatibility)",
        "ext": ".mp4",
        "args": [
            "-vcodec", "libx264", "-profile:v", "baseline", "-level", "3.1",
            "-pix_fmt", "yuv420p", "-acodec", "aac", "-b:a", "128k",
        ],
    },
    {
        "label": "MOV — H.264 (QuickTime / Apple devices)",
        "ext": ".mov",
        "args": ["-vcodec", "libx264", "-pix_fmt", "yuv420p", "-acodec", "aac", "-b:a", "128k"],
    },
]


class ConvertDialog(QDialog):
    """Format picker shown before conversion starts."""

    def __init__(self, file_count: int, out_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Convert Video")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        count_lbl = QLabel(
            f"Convert {file_count} video{'s' if file_count != 1 else ''} to:"
        )
        count_lbl.setStyleSheet(f"color:{COLORS['fg_primary']}; font-size:10pt;")
        layout.addWidget(count_lbl)

        self._format_combo = QComboBox()
        self._format_combo.setFixedHeight(36)
        for p in CONVERT_PRESETS:
            self._format_combo.addItem(p["label"])
        layout.addWidget(self._format_combo)

        out_row = QHBoxLayout()
        out_lbl = QLabel("Output folder:")
        out_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._out_edit = QLineEdit(out_dir)
        self._out_edit.setFixedHeight(34)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(34)
        browse_btn.clicked.connect(self._browse)
        out_row.addWidget(out_lbl)
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        note = QLabel("Converted files are saved alongside the originals unless you change the folder.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{COLORS['fg_dim']}; font-size:9pt;")
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Convert")
        ok_btn.setFixedHeight(34)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"""
            QDialog {{ background-color: {COLORS['bg_dark']}; }}
            QLabel {{ color: {COLORS['fg_primary']}; }}
            QLineEdit, QComboBox {{
                background-color: {COLORS['bg_light']};
                color: {COLORS['fg_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 10pt;
            }}
            QPushButton {{
                background-color: {COLORS['bg_light']};
                color: {COLORS['fg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px 16px;
                font-size: 10pt;
            }}
            QPushButton:hover {{ background-color: {COLORS['accent']}; color: white; }}
        """)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Output Folder", self._out_edit.text())
        if folder:
            self._out_edit.setText(folder)

    def selected_preset(self) -> dict:
        return CONVERT_PRESETS[self._format_combo.currentIndex()]

    def output_dir(self) -> str:
        return self._out_edit.text().strip()


class VideoConverterThread(QThread):
    """Runs ffmpeg conversions sequentially in a background thread."""
    progress = pyqtSignal(int, int, str)   # current, total, current_filename
    finished = pyqtSignal(int, list)        # success_count, error_list
    log = pyqtSignal(str)

    def __init__(self, paths: list[str], preset: dict, out_dir: str, ffmpeg: str):
        super().__init__()
        self._paths = paths
        self._preset = preset
        self._out_dir = Path(out_dir)
        self._ffmpeg = ffmpeg
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._paths)
        success = 0
        errors = []
        self._out_dir.mkdir(parents=True, exist_ok=True)

        for i, src in enumerate(self._paths):
            if self._cancelled:
                break
            src_path = Path(src)
            stem = src_path.stem
            ext = self._preset["ext"]

            # Auto-number if output already exists
            dest = self._out_dir / f"{stem}{ext}"
            counter = 1
            while dest.exists():
                dest = self._out_dir / f"{stem}_{counter}{ext}"
                counter += 1

            self.progress.emit(i + 1, total, src_path.name)
            cmd = [
                self._ffmpeg, "-y", "-i", str(src_path),
                *self._preset["args"],
                str(dest),
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                if result.returncode != 0:
                    errors.append(f"{src_path.name}: ffmpeg error (code {result.returncode})")
                    self.log.emit(f"[convert] FAILED {src_path.name}: {result.stderr[-300:].strip()}")
                else:
                    success += 1
                    self.log.emit(f"[convert] OK → {dest.name}")
            except Exception as e:
                errors.append(f"{src_path.name}: {e}")
                self.log.emit(f"[convert] ERROR {src_path.name}: {e}")

        self.finished.emit(success, errors)


# ------------------------------------------------------------------ #
# Main window
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    _VID_SORT_OPTIONS = [
        ("Newest First",   lambda p: p.stat().st_mtime, True),
        ("Oldest First",   lambda p: p.stat().st_mtime, False),
        ("Name A → Z",     lambda p: p.name.lower(),    False),
        ("Name Z → A",     lambda p: p.name.lower(),    True),
        ("Largest First",  lambda p: p.stat().st_size,  True),
        ("Smallest First", lambda p: p.stat().st_size,  False),
    ]

    _IMG_SORT_OPTIONS = [
        ("Name A → Z",     lambda p: p.name.lower(),    False),
        ("Name Z → A",     lambda p: p.name.lower(),    True),
        ("Newest First",   lambda p: p.stat().st_mtime, True),
        ("Oldest First",   lambda p: p.stat().st_mtime, False),
    ]

    def __init__(self, config_manager: ConfigManager, version: str):
        super().__init__()
        self.config = config_manager
        self.version = version
        self._worker: BatchChainWorker | None = None
        self._img_loader: ImageLoaderThread | None = None
        self._vid_loader: VideoLoaderThread | None = None
        self._last_vid_dir: str = ""
        self._seg_dots: list[SegmentDot] = []
        self._seg_time_labels: list[QLabel] = []
        # Result of the last batch-workflow validation of the active chain.
        # Start / Auto Run stay disabled while _chain_errors is non-empty.
        self._chain_errors: list[str] = []
        self._chain_warnings: list[str] = []
        # LoRA inventory for the active chain (see _validate_active_chain)
        self._lora_refs: dict[str, list[str]] = {}
        self._lora_remote_pending = False
        self._lora_remote_note = ""          # status text for the pod check
        self._lora_remote_error = ""         # pod check failed (network/config)
        self._pod_missing_jobs: list[LoraUploadJob] = []
        self._remote_check_worker: RemoteLoraCheckWorker | None = None
        self._remote_check_token = 0
        self._lora_upload_worker: LoraUploadWorker | None = None
        self._start_after_upload = False
        self._auto_mode = False
        self._auto_stop_requested = False
        self._auto_continue = False
        self._seg_times_sec: dict[int, float] = {}  # per-segment wall times, for ETA
        self._batch_registry_ctx: tuple | None = None  # (input_dir, chain, keys) of running batch
        # Sampler-pass tracking: ComfyUI restarts the raw progress cycle for
        # each sampler node, so we count cycles to keep the segment bar monotonic
        self._step_seg = 0
        self._step_last_value = 0
        self._step_last_max = 0
        self._step_cycle = 1
        self._steps_before = 0    # steps finished in this segment's completed passes
        self._seg_plan = (0, 0)   # (expected passes, expected total steps) from the worker
        self._cycles_per_seg = 0  # fallback: learned when the first segment completes
        # Post-sampler phases (VAE decode, encode, save) have no step-level
        # progress of their own, so they're tracked as flat ticks appended
        # to the segment's step total — otherwise the bar reads 100% while
        # the file is still being decoded/written.
        self._seg_post_phases = 0
        self._post_phase_done = 0
        self._sampler_done = 0    # sampler-only steps completed, cached for phase ticks

        self.setWindowTitle(f"ComfyUI Workflow Chain Automator  v{version}")
        self.setMinimumSize(1200, 780)
        self.resize(1600, 860)
        self.setStyleSheet(STYLESHEET)

        self._build_ui()
        self._refresh_chain_folders()
        self._populate_images()

    def _generation_running(self) -> bool:
        """PodControl asks this: a running batch (or a LoRA upload that will
        start one) means the pod is working, so a spend-limit stop waits and
        the idle countdown never arms."""
        if self._worker is not None and self._worker.isRunning():
            return True
        return bool(self._lora_upload_worker and self._lora_upload_worker.isRunning())

    def _on_server_changed(self):
        """A pod came up (or went away) and PodControl rewrote mode/runpod_url:
        refresh the mode badges and re-run the pod-side LoRA check."""
        self._generate_tab.refresh_mode()
        self._prompt_writer_tab.refresh_mode()
        if not (self._worker is not None and self._worker.isRunning()):
            self._validate_active_chain(show_dialog=False, remote=True)

    @property
    def _seg_count(self) -> int:
        folder = self.config.get("active_chain_folder", "")
        wf_dir = Path(self.config.get("workflow_dir", ""))
        if folder and wf_dir:
            chain_dir = wf_dir / folder
            if chain_dir.exists():
                return min(len(list(chain_dir.glob("workflow_segment_*_batch.json"))), MAX_SEGMENTS)
            return 0
        return min(max(len(self.config.get("workflows", [])), 1), MAX_SEGMENTS)

    def _ffmpeg_path(self) -> str:
        # The configured ffmpeg can vanish out from under us (e.g. it lived
        # inside a ComfyUI venv that got deleted) — fall back to an
        # ffmpeg.exe shipped next to the app, then to PATH, so thumbnails,
        # stitching, and frame extraction keep working.
        configured = (self.config.get("ffmpeg_path", "") or "").strip()
        if configured and Path(configured).exists():
            return configured
        bundled = Path(self.config.get("_base_dir", ".")) / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)
        return "ffmpeg"

    def _effective_video_dir(self) -> Path:
        """Root final-video folder + active chain subfolder (auto-created on use)."""
        root = Path(self.config.get("final_video_dir", ""))
        folder = self.config.get("active_chain_folder", "").strip()
        return root / folder if folder else root

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────
        header_row = QHBoxLayout()

        # Mode toggle buttons
        mode_btn_style = f"""
            QPushButton {{
                background-color: {COLORS['bg_light']};
                color: {COLORS['fg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 10pt;
                font-weight: bold;
                padding: 4px 16px;
                min-width: 90px;
            }}
            QPushButton:checked {{
                background-color: {COLORS['accent']};
                color: white;
                border: 1px solid {COLORS['accent']};
            }}
            QPushButton:hover:!checked {{ background-color: {COLORS['bg_medium']}; }}
        """
        self._chain_btn = QPushButton("⛓  Chain")
        self._chain_btn.setCheckable(True)
        self._chain_btn.setChecked(True)
        self._chain_btn.setFixedHeight(32)
        self._chain_btn.setStyleSheet(mode_btn_style)
        self._chain_btn.clicked.connect(lambda: self._switch_view(0))

        self._library_btn = QPushButton("🎬  Library")
        self._library_btn.setCheckable(True)
        self._library_btn.setChecked(False)
        self._library_btn.setFixedHeight(32)
        self._library_btn.setStyleSheet(mode_btn_style)
        self._library_btn.clicked.connect(lambda: self._switch_view(1))

        self._generate_btn = QPushButton("✨  Generate")
        self._generate_btn.setCheckable(True)
        self._generate_btn.setChecked(False)
        self._generate_btn.setFixedHeight(32)
        self._generate_btn.setStyleSheet(mode_btn_style)
        self._generate_btn.clicked.connect(lambda: self._switch_view(2))

        self._prompt_btn = QPushButton("📝  Prompt Writer")
        self._prompt_btn.setCheckable(True)
        self._prompt_btn.setChecked(False)
        self._prompt_btn.setFixedHeight(32)
        self._prompt_btn.setStyleSheet(mode_btn_style)
        self._prompt_btn.clicked.connect(lambda: self._switch_view(3))

        header = QLabel("ComfyUI Workflow Chain Automator")
        header.setObjectName("header")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setFixedHeight(36)
        settings_btn.setToolTip("Settings")
        settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_light']};
                color: {COLORS['fg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 10pt;
                font-weight: normal;
                padding: 0px 12px;
            }}
            QPushButton:hover {{ background-color: {COLORS['accent']}; color: white; }}
        """)
        settings_btn.clicked.connect(self._open_settings)

        # RunPod pod control (copied from ComfyUI Video Creator): spend
        # readout + Start/Stop Pod button. It owns everything pod-related;
        # the window only answers "is a batch running right now?".
        self._pod = PodControl(self.config, self._generation_running, self)
        self._pod.server_changed.connect(self._on_server_changed)
        self._pod.log.connect(self._on_log)

        header_row.addWidget(self._chain_btn)
        header_row.addSpacing(4)
        header_row.addWidget(self._library_btn)
        header_row.addSpacing(4)
        header_row.addWidget(self._generate_btn)
        header_row.addSpacing(4)
        header_row.addWidget(self._prompt_btn)
        header_row.addStretch()
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self._pod)
        header_row.addSpacing(8)
        header_row.addWidget(settings_btn)
        root.addLayout(header_row)

        # ── Stacked pages ─────────────────────────────────────────────────
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_chain_page())
        self._stack.addWidget(self._build_library_page())
        self._generate_tab = GenerateTab(self.config, parent=self)
        self._generate_tab.send_to_chain.connect(self._on_send_to_chain)
        self._generate_tab.start_one_shot.connect(self._on_start_one_shot)
        self._stack.addWidget(self._generate_tab)

        self._prompt_writer_tab = PromptWriterTab(self.config, parent=self)
        self._prompt_writer_tab.send_to_generate.connect(self._on_send_to_generate)
        self._stack.addWidget(self._prompt_writer_tab)

    def _build_chain_page(self) -> QWidget:
        page = QWidget()
        split = QHBoxLayout(page)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(12)

        # Left — image picker
        left = QVBoxLayout()
        left.setSpacing(6)

        folder_row = QHBoxLayout()
        folder_lbl = QLabel("Image Folder:")
        folder_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._input_dir_edit = QLineEdit(self.config.get("input_dir", ""))
        self._input_dir_edit.setPlaceholderText("Folder containing starting images...")
        self._input_dir_edit.setReadOnly(True)
        folder_browse_btn = QPushButton("Browse")
        folder_browse_btn.setObjectName("small_btn")
        folder_browse_btn.setFixedHeight(30)
        folder_browse_btn.clicked.connect(self._browse_input_dir)
        self._show_all_chk = QCheckBox("Show all")
        self._show_all_chk.setToolTip("Include images that already have a video in the library")
        self._show_all_chk.setChecked(False)
        self._show_all_chk.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._show_all_chk.stateChanged.connect(lambda _: (self._apply_image_filter(), self._update_auto_buttons()))
        self._img_sort_combo = QComboBox()
        self._img_sort_combo.setFixedHeight(30)
        self._img_sort_combo.setMinimumWidth(140)
        for label, *_ in self._IMG_SORT_OPTIONS:
            self._img_sort_combo.addItem(label)
        self._img_sort_combo.currentIndexChanged.connect(lambda _: self._populate_images())
        folder_row.addWidget(folder_lbl)
        folder_row.addWidget(self._input_dir_edit, stretch=1)
        folder_row.addWidget(folder_browse_btn)
        folder_row.addSpacing(8)
        folder_row.addWidget(self._img_sort_combo)
        folder_row.addSpacing(8)
        folder_row.addWidget(self._show_all_chk)
        left.addLayout(folder_row)

        self._img_group = QGroupBox("Starting Images — Ctrl+click or Shift+click to select multiple")
        img_layout = QVBoxLayout(self._img_group)
        img_layout.setContentsMargins(6, 6, 6, 6)
        self.image_grid = ThumbnailGrid()
        self.image_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        img_layout.addWidget(self.image_grid)
        self.image_grid.itemSelectionChanged.connect(self._on_image_selected)
        left.addWidget(self._img_group, stretch=1)

        self.selected_label = QLabel("Select images to include in the batch")
        self.selected_label.setObjectName("subtitle")
        self.selected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.selected_label)

        split.addLayout(left, stretch=3)

        # Right — progress + log + buttons
        right = QVBoxLayout()
        right.setSpacing(8)

        # ── Chain selector ────────────────────────────────────────────────
        chain_sel_row = QHBoxLayout()
        chain_sel_lbl = QLabel("Chain:")
        chain_sel_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        chain_sel_lbl.setFixedWidth(48)
        self._chain_folder_combo = QComboBox()
        self._chain_folder_combo.setMinimumHeight(30)
        self._chain_folder_combo.setToolTip("Select a video chain workflow folder")
        self._chain_folder_combo.currentIndexChanged.connect(self._on_chain_folder_changed)
        refresh_chain_btn = QPushButton("↻ Refresh")
        refresh_chain_btn.setObjectName("small_btn")
        refresh_chain_btn.setFixedHeight(30)
        refresh_chain_btn.setToolTip("Refresh chain folder list")
        refresh_chain_btn.clicked.connect(self._refresh_chain_folders)
        chain_sel_row.addWidget(chain_sel_lbl)
        chain_sel_row.addWidget(self._chain_folder_combo, stretch=1)
        chain_sel_row.addWidget(refresh_chain_btn)
        self._sync_loras_btn = QPushButton("⇅ LoRAs")
        # The global QPushButton padding (10px 28px @ 11pt) needs ~40px of
        # height; this button sits in the 30px chain row, so give it its
        # own compact padding instead of clipping the text.
        self._sync_loras_btn.setMinimumHeight(30)
        self._sync_loras_btn.setStyleSheet("QPushButton { padding: 4px 12px; font-size: 10pt; }")
        self._sync_loras_btn.setToolTip(
            "Upload the LoRAs this chain uses that are missing on the pod (RunPod mode)")
        self._sync_loras_btn.clicked.connect(self._sync_loras_clicked)
        chain_sel_row.addWidget(self._sync_loras_btn)
        right.addLayout(chain_sel_row)

        # Validation verdict for the selected chain's batch workflows —
        # hidden when everything checks out, red with the problem otherwise.
        self._chain_status_label = QLabel("")
        self._chain_status_label.setWordWrap(True)
        self._chain_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._chain_status_label.setStyleSheet(
            f"color:{COLORS['error']}; font-size:9pt; padding:2px 4px;")
        self._chain_status_label.hide()
        right.addWidget(self._chain_status_label)

        self._seg_group = QGroupBox("Segment Progress")
        self._seg_layout = QVBoxLayout(self._seg_group)
        self._rebuild_seg_panel()
        right.addWidget(self._seg_group)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_list = QListWidget()
        self.log_list.setSpacing(-1)
        self.log_list.setUniformItemSizes(True)
        log_layout.addWidget(self.log_list)
        right.addWidget(log_group, stretch=1)

        self.final_label = QLabel("")
        self.final_label.setObjectName("final_label")
        self.final_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.final_label.setWordWrap(True)
        right.addWidget(self.final_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.start_btn = QPushButton("▶  Start Batch")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("✕  Cancel")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.start_btn)
        btn_row.addSpacing(12)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        right.addLayout(btn_row)

        # ── Auto mode row ─────────────────────────────────────────────────
        auto_row = QHBoxLayout()
        auto_row.addStretch()
        auto_lbl = QLabel("Batch size:")
        auto_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._auto_size_spin = QSpinBox()
        self._auto_size_spin.setRange(1, 50)
        self._auto_size_spin.setValue(4)
        self._auto_size_spin.setFixedHeight(28)
        self._auto_size_spin.setFixedWidth(64)
        self._auto_size_spin.setToolTip("Images per auto batch (1–50)")
        _auto_btn_style = "font-size: 9pt; padding: 4px 14px;"
        self._auto_btn = QPushButton("▶▶  Auto Run")
        self._auto_btn.setFixedHeight(28)
        self._auto_btn.setStyleSheet(
            f"QPushButton {{ background-color: #4a78d4; color: white;"
            f" border-radius: 4px; font-weight: bold; {_auto_btn_style} }}"
            f"QPushButton:hover {{ background-color: #5b8ce0; }}"
            f"QPushButton:disabled {{ background-color: {COLORS['bg_light']};"
            f" color: {COLORS['fg_dim']}; {_auto_btn_style} }}"
        )
        self._auto_btn.setToolTip("Automatically process all images N at a time, no prompts between batches")
        self._auto_btn.clicked.connect(self._start_auto)
        self._stop_auto_btn = QPushButton("⏹  Stop After Batch")
        self._stop_auto_btn.setObjectName("cancel_btn")
        self._stop_auto_btn.setFixedHeight(28)
        self._stop_auto_btn.setStyleSheet(
            f"QPushButton {{ font-size: 9pt; padding: 4px 14px; }}"
        )
        self._stop_auto_btn.setEnabled(False)
        self._stop_auto_btn.setToolTip("Finish the current batch then stop auto mode")
        self._stop_auto_btn.clicked.connect(self._stop_auto_after_batch)
        auto_row.addWidget(auto_lbl)
        auto_row.addSpacing(4)
        auto_row.addWidget(self._auto_size_spin)
        auto_row.addSpacing(10)
        auto_row.addWidget(self._auto_btn)
        auto_row.addSpacing(8)
        auto_row.addWidget(self._stop_auto_btn)
        auto_row.addStretch()
        right.addLayout(auto_row)

        split.addLayout(right, stretch=2)
        return page

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Toolbar row
        toolbar = QHBoxLayout()
        vid_folder_lbl = QLabel("Video Folder:")
        vid_folder_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._vid_dir_edit = QLineEdit(self.config.get("final_video_dir", ""))
        self._vid_dir_edit.setPlaceholderText("Folder containing video files...")
        self._vid_dir_edit.setReadOnly(True)
        vid_browse_btn = QPushButton("Browse")
        vid_browse_btn.setObjectName("small_btn")
        vid_browse_btn.setFixedHeight(40)
        vid_browse_btn.clicked.connect(self._browse_video_dir)
        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setFixedHeight(40)
        refresh_btn.clicked.connect(lambda: self._populate_videos(force=True))
        self._vid_sort_combo = QComboBox()
        self._vid_sort_combo.setFixedHeight(40)
        self._vid_sort_combo.setMinimumWidth(160)
        for label, *_ in self._VID_SORT_OPTIONS:
            self._vid_sort_combo.addItem(label)
        self._vid_sort_combo.currentIndexChanged.connect(self._on_vid_sort_changed)
        self._vid_play_btn = QPushButton("▶  Play Selected")
        self._vid_play_btn.setFixedHeight(40)
        self._vid_play_btn.setEnabled(False)
        self._vid_play_btn.clicked.connect(self._play_selected_videos)
        self._vid_delete_btn = QPushButton("🗑  Delete")
        self._vid_delete_btn.setFixedHeight(40)
        self._vid_delete_btn.setObjectName("cancel_btn")
        self._vid_delete_btn.setEnabled(False)
        self._vid_delete_btn.clicked.connect(self._delete_selected_video)
        self._vid_convert_btn = QPushButton("🔄  Convert")
        self._vid_convert_btn.setFixedHeight(40)
        self._vid_convert_btn.setEnabled(False)
        self._vid_convert_btn.setToolTip("Convert selected videos to AVI, MP4 Baseline, or MOV")
        self._vid_convert_btn.clicked.connect(self._convert_selected_videos)
        self._vid_settings_btn = QPushButton("ℹ️  Settings")
        self._vid_settings_btn.setFixedHeight(40)
        self._vid_settings_btn.setEnabled(False)
        self._vid_settings_btn.setToolTip("Show the prompt/sampler/model settings used to generate the selected video")
        self._vid_settings_btn.clicked.connect(self._show_video_settings)
        toolbar.addWidget(vid_folder_lbl)
        toolbar.addWidget(self._vid_dir_edit, stretch=1)
        toolbar.addWidget(vid_browse_btn)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._vid_sort_combo)
        toolbar.addSpacing(4)
        toolbar.addWidget(refresh_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._vid_play_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._vid_convert_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._vid_settings_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._vid_delete_btn)
        layout.addLayout(toolbar)

        # Video grid
        vid_group = QGroupBox("Videos — double-click to play one, or select multiple and click Play Selected")
        vid_layout = QVBoxLayout(vid_group)
        vid_layout.setContentsMargins(6, 6, 6, 6)
        self.video_grid = ThumbnailGrid()
        self.video_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.video_grid.itemDoubleClicked.connect(self._on_video_double_clicked)
        self.video_grid.itemSelectionChanged.connect(self._on_vid_selection_changed)
        vid_layout.addWidget(self.video_grid)
        layout.addWidget(vid_group, stretch=1)

        # Status bar
        lib_bottom = QHBoxLayout()
        self._vid_status_label = QLabel("Select a video folder to browse")
        self._vid_status_label.setObjectName("subtitle")
        self._vid_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vid_progress = QProgressBar()
        self._vid_progress.setRange(0, 1)
        self._vid_progress.setValue(0)
        self._vid_progress.setFixedHeight(16)
        self._vid_progress.setVisible(False)
        lib_bottom.addWidget(self._vid_status_label, stretch=1)
        lib_bottom.addWidget(self._vid_progress)
        layout.addLayout(lib_bottom)

        return page

    def _switch_view(self, index: int):
        self._chain_btn.setChecked(index == 0)
        self._library_btn.setChecked(index == 1)
        self._generate_btn.setChecked(index == 2)
        self._prompt_btn.setChecked(index == 3)
        self._stack.setCurrentIndex(index)
        if index == 1:
            self._populate_videos()
        elif index == 2:
            self._generate_tab.refresh_mode()
        elif index == 3:
            self._prompt_writer_tab.refresh_mode()

    def _on_send_to_generate(self, text: str):
        self._generate_tab.set_positive_prompt(text)
        self._switch_view(2)

    # ------------------------------------------------------------------ #
    # Segment panel
    # ------------------------------------------------------------------ #

    def _rebuild_seg_panel(self):
        while self._seg_layout.count():
            item = self._seg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                child = item.layout()
                while child.count():
                    c = child.takeAt(0)
                    if c.widget():
                        c.widget().deleteLater()

        self._seg_dots = []
        self._seg_time_labels = []
        n = self._seg_count

        if n == 0:
            no_wf_label = QLabel("No *_batch.json workflow files found in selected folder")
            no_wf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_wf_label.setStyleSheet(f"color:{COLORS['fg_dim']}; font-size:10pt;")
            self._seg_layout.addWidget(no_wf_label)
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self._seg_layout.addWidget(self.progress_bar)
            self.step_bar = self._make_step_bar()
            self._seg_layout.addWidget(self.step_bar)
            self.progress_label = QLabel("No workflows configured")
            self.progress_label.setObjectName("subtitle")
            self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._seg_layout.addWidget(self.progress_label)
            return

        dots_row = QHBoxLayout()
        dots_row.setSpacing(6)
        dots_row.addStretch()
        for i in range(1, n + 1):
            dot = SegmentDot(i)
            dot.double_clicked.connect(self._on_seg_dot_double_clicked)
            self._seg_dots.append(dot)
            dots_row.addWidget(dot)
            if i < n:
                sep = QLabel("—")
                sep.setStyleSheet(f"color:{COLORS['fg_dim']};")
                dots_row.addWidget(sep)
        dots_row.addStretch()
        self._seg_layout.addLayout(dots_row)

        self.progress_bar = QProgressBar()
        # 100 ticks per segment so live sampler-step progress renders smoothly
        self.progress_bar.setRange(0, n * 100)
        self.progress_bar.setValue(0)
        self._seg_layout.addWidget(self.progress_bar)

        self.step_bar = self._make_step_bar()
        self._seg_layout.addWidget(self.step_bar)

        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("subtitle")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._seg_layout.addWidget(self.progress_label)

        times_row = QHBoxLayout()
        times_row.setSpacing(4)
        times_row.addStretch()
        for i in range(1, n + 1):
            time_lbl = QLabel("[m:s]")
            time_lbl.setFixedWidth(55)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            time_lbl.setStyleSheet(
                f"color:{COLORS['fg_secondary']}; font-size:8pt; font-family:Consolas;"
            )
            self._seg_time_labels.append(time_lbl)
            times_row.addWidget(time_lbl)
            if i < n:
                gap = QLabel()
                gap.setFixedWidth(3)
                times_row.addWidget(gap)
        times_row.addStretch()
        self._seg_layout.addLayout(times_row)

    def _make_step_bar(self) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFixedHeight(16)
        bar.setFormat("Step —")
        bar.setStyleSheet(
            f"QProgressBar {{ font-size: 8pt; }}"
            f"QProgressBar::chunk {{ background-color: {COLORS['success']}; }}"
        )
        return bar

    # ------------------------------------------------------------------ #
    # Image picker (Chain view)
    # ------------------------------------------------------------------ #

    def _existing_video_stems(self) -> set[str]:
        """Return stems of videos in the current template's output folder.
        Adds the raw stem, the run-timestamp-stripped stem, and the
        _N-stripped stem so images like 'photo.png' are excluded when
        'photo_20260709_141530.mp4' or auto-numbered 'photo_1.mp4' exists."""
        vid_dir = self._effective_video_dir()
        if not vid_dir.exists():
            return set()
        stems: set[str] = set()
        for p in vid_dir.iterdir():
            if p.suffix.lower() in VIDEO_EXTS:
                stems.add(p.stem)
                unstamped = RUN_STAMP_RE.sub("", p.stem)
                stems.add(unstamped)
                stems.add(re.sub(r'_\d+$', '', unstamped))
        return stems

    # ── Per-chain processed registry ──────────────────────────────────
    # The video files alone aren't a reliable record of what a chain has
    # processed — finished videos get moved out of the chain's output
    # folder. This registry (stored with the image folder's thumbnails)
    # keeps the history per chain, keyed by the chain folder name.

    def _current_input_dir(self) -> Path:
        return Path(self._input_dir_edit.text().strip() or self.config.get("input_dir", ""))

    def _registry_path(self, input_dir: Path) -> Path:
        return input_dir / "thumbnails" / "processed_chains.json"

    def _load_registry(self, input_dir: Path) -> dict:
        try:
            with open(self._registry_path(input_dir), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _processed_stems(self) -> set[str]:
        chain = self.config.get("active_chain_folder", "").strip()
        if not chain:
            return set()
        return set(self._load_registry(self._current_input_dir()).get(chain, {}))

    def _record_processed(self, input_dir: Path, chain: str, keys: list[str]):
        if not chain or not keys:
            return
        reg = self._load_registry(input_dir)
        entry = reg.setdefault(chain, {})
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for k in keys:
            entry[Path(k).stem] = stamp
        path = self._registry_path(input_dir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=1)
        except OSError:
            pass

    def _unrecord_processed(self, input_dir: Path, chain: str, stems: set[str]):
        """Remove stems from a chain's processed registry entry — used when a
        library video is deleted, so its source image counts as unprocessed
        (a bad generation) and reappears in the chain's image list."""
        if not chain or not stems:
            return
        reg = self._load_registry(input_dir)
        entry = reg.get(chain)
        if not entry:
            return
        changed = False
        for s in stems:
            if entry.pop(s, None) is not None:
                changed = True
        if not changed:
            return
        path = self._registry_path(input_dir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=1)
        except OSError:
            pass

    def _populate_images(self):
        input_dir = Path(self._input_dir_edit.text().strip() or self.config.get("input_dir", ""))

        if self._img_loader and self._img_loader.isRunning():
            self._img_loader.cancel()
            self._img_loader.wait()

        self.image_grid.clear_grid()
        self.selected_label.setText("Loading images...")
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("Loading images...")
        self.start_btn.setEnabled(False)

        if not input_dir.exists():
            self.selected_label.setText("No images found in input folder")
            self.progress_bar.setRange(0, self._seg_count * 100)
            self.progress_label.setText("Ready")
            self._update_start_enabled()
            return

        # Warn if any stem appears with more than one extension
        thumb_dir = input_dir / "thumbnails"
        stem_exts: dict[str, list[str]] = {}
        for p in input_dir.rglob("*"):
            if p.suffix.lower() in IMAGE_EXTS and thumb_dir not in p.parents:
                stem_exts.setdefault(p.stem, []).append(p.suffix.lower())
        duplicates = {s: exts for s, exts in stem_exts.items() if len(exts) > 1}
        if duplicates:
            lines = "\n".join(
                f"  {s}: {', '.join(exts)}" for s, exts in list(duplicates.items())[:10]
            )
            QMessageBox.warning(
                self, "Duplicate Filenames Detected",
                f"Some files share the same name but have different extensions:\n\n{lines}\n\n"
                "Consider converting your batch folder to a single extension (e.g. all PNG) "
                "to avoid ambiguous one-to-one matching."
            )

        sort_idx = self._img_sort_combo.currentIndex()
        _, sort_key, sort_reverse = self._IMG_SORT_OPTIONS[sort_idx]
        self._img_loader = ImageLoaderThread(input_dir, sort_key, sort_reverse)
        self._img_loader.image_ready.connect(self.image_grid.add_item)
        self._img_loader.progress.connect(self._on_img_load_progress)
        self._img_loader.finished_loading.connect(self._on_img_load_finished)
        self._img_loader.start()

    def _on_img_load_progress(self, current: int, total: int):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"Loading images... {current}/{total}")

    def _on_img_load_finished(self, total: int):
        self.progress_bar.setRange(0, self._seg_count * 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Ready")
        self._update_start_enabled()
        self._apply_image_filter()

    def _apply_image_filter(self):
        """Show/hide grid items to match the active template — images that
        already have a video are hidden (unless 'Show all'). This replaces
        rescanning the image folder when switching chain folders."""
        excluded = set() if self._show_all_chk.isChecked() \
            else self._existing_video_stems() | self._processed_stems()
        visible = 0
        for i in range(self.image_grid.count()):
            item = self.image_grid.item(i)
            stem = Path(item.data(Qt.ItemDataRole.UserRole)).stem
            hide = stem in excluded
            if hide and item.isSelected():
                item.setSelected(False)
            item.setHidden(hide)
            if not hide:
                visible += 1
        if self.image_grid.count() == 0:
            self.selected_label.setText("No images found in input folder")
        elif visible == 0:
            self.selected_label.setText("All images already have videos for this chain — check 'Show all' to reuse them")
        else:
            self.selected_label.setText(f"{visible} image{'s' if visible != 1 else ''} — select to include in the batch")
        return visible

    def _visible_image_items(self) -> list[QListWidgetItem]:
        return [self.image_grid.item(i) for i in range(self.image_grid.count())
                if not self.image_grid.item(i).isHidden()]

    def _browse_input_dir(self):
        current = self._input_dir_edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder", current or str(Path.home()))
        if folder:
            if Path(folder).name.lower() == "thumbnails":
                QMessageBox.warning(
                    self, "Wrong Folder",
                    "That's the thumbnails cache folder — it only holds small downscaled "
                    "previews. Select the parent folder with the full-size originals instead."
                )
                return
            self._input_dir_edit.setText(folder)
            self.config.set("input_dir", folder)
            self.config.save()
            self._populate_images()

    def _on_image_selected(self):
        keys = self.image_grid.selected_keys()
        if not keys:
            return
        self.selected_label.setText(
            f"{len(keys)} image{'s' if len(keys) > 1 else ''} selected"
        )

    # ------------------------------------------------------------------ #
    # Video library (Library view)
    # ------------------------------------------------------------------ #

    def _populate_videos(self, force: bool = False):
        vid_dir = Path(self._vid_dir_edit.text().strip()) if self._vid_dir_edit.text().strip() else self._effective_video_dir()

        # Skip reload if same folder already loaded
        if not force and str(vid_dir) == self._last_vid_dir and self.video_grid.count() > 0:
            return

        if self._vid_loader and self._vid_loader.isRunning():
            self._vid_loader.cancel()
            self._vid_loader.wait()

        self._last_vid_dir = str(vid_dir)
        self.video_grid.clear_grid()
        self._vid_progress.setVisible(True)
        self._vid_progress.setRange(0, 0)
        self._vid_status_label.setText("Loading videos...")

        if not vid_dir.exists():
            self._vid_status_label.setText("Video folder not found — check Settings")
            self._vid_progress.setVisible(False)
            return

        self._thumb_gen_dlg: QProgressDialog | None = None
        sort_idx = self._vid_sort_combo.currentIndex()
        _, sort_key, sort_reverse = self._VID_SORT_OPTIONS[sort_idx]
        self._vid_loader = VideoLoaderThread(vid_dir, self._ffmpeg_path(), sort_key, sort_reverse)
        self._vid_loader.video_ready.connect(self.video_grid.add_item)
        self._vid_loader.thumbnails_needed.connect(self._on_thumbnails_needed)
        self._vid_loader.progress.connect(self._on_vid_load_progress)
        self._vid_loader.finished_loading.connect(self._on_vid_load_finished)
        self._vid_loader.start()

    def _on_thumbnails_needed(self, count: int):
        self._thumb_gen_dlg = QProgressDialog(
            f"Generating {count} new thumbnail{'s' if count != 1 else ''}...",
            None, 0, count, self
        )
        self._thumb_gen_dlg.setWindowTitle("Updating Library")
        self._thumb_gen_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._thumb_gen_dlg.setMinimumWidth(380)
        self._thumb_gen_dlg.setAutoClose(False)
        self._thumb_gen_dlg.setAutoReset(False)
        self._thumb_gen_dlg.setValue(0)
        self._thumb_gen_dlg.show()

    def _on_vid_load_progress(self, current: int, total: int):
        if self._thumb_gen_dlg and self._thumb_gen_dlg.isVisible():
            self._thumb_gen_dlg.setLabelText(f"Generating thumbnails... {current}/{total}")
            self._thumb_gen_dlg.setValue(current)
        else:
            self._vid_progress.setRange(0, total)
            self._vid_progress.setValue(current)
            self._vid_status_label.setText(f"Loading thumbnails... {current}/{total}")

    def _on_vid_load_finished(self, total: int):
        if self._thumb_gen_dlg:
            self._thumb_gen_dlg.close()
            self._thumb_gen_dlg = None
        self._vid_progress.setVisible(False)
        if total == 0:
            self._vid_status_label.setText("No video files found in folder")
        else:
            self._vid_status_label.setText(f"{total} video{'s' if total != 1 else ''} — double-click to play")

    def _on_vid_sort_changed(self):
        self._populate_videos(force=True)

    def _sync_lib_dir_display(self):
        """Update the Library folder display to the current template's output subfolder."""
        self._vid_dir_edit.setText(str(self._effective_video_dir()))
        self._last_vid_dir = ""  # force reload next time Library is shown

    def _browse_video_dir(self):
        # Browse selects the ROOT folder; effective dir = root / active_chain_folder
        root = self.config.get("final_video_dir", "")
        folder = QFileDialog.getExistingDirectory(self, "Select Root Video Folder", root or str(Path.home()))
        if folder:
            # Users naturally pick the chain's own folder (where they see the
            # videos), but this setting is the ROOT the chain name gets
            # appended to — keeping their pick as-is would make the library
            # look in <chain>/<chain>, an empty doubled path. Step up to the
            # parent so the effective dir lands back on the folder they chose.
            chain = self.config.get("active_chain_folder", "").strip()
            picked = Path(folder)
            if chain and picked.name == chain:
                folder = str(picked.parent)
                QMessageBox.information(
                    self, "Root Folder Adjusted",
                    f"You picked the chain folder itself:\n{picked}\n\n"
                    f"This setting is the root folder — the active chain name "
                    f"(“{chain}”) is added automatically. Using its parent:\n{folder}",
                )
            self.config.set("final_video_dir", folder)
            self.config.save()
            self._sync_lib_dir_display()
            self._populate_videos()

    def _on_vid_selection_changed(self):
        keys = self.video_grid.selected_keys()
        has_sel = bool(keys)
        self._vid_play_btn.setEnabled(has_sel)
        self._vid_convert_btn.setEnabled(has_sel)
        self._vid_delete_btn.setEnabled(has_sel)
        self._vid_settings_btn.setEnabled(len(keys) == 1)
        total = self.video_grid.count()
        if has_sel:
            n = len(keys)
            self._vid_status_label.setText(f"{n} of {total} selected")
        elif total > 0:
            self._vid_status_label.setText(f"{total} video{'s' if total != 1 else ''} — double-click to play")

    def _play_selected_videos(self):
        keys = self.video_grid.selected_keys()
        existing = [k for k in keys if Path(k).exists()]
        if not existing:
            return
        # Library playback closes itself after the last clip — nothing to
        # dismiss once the selection has played through.
        player = VideoPlayerDialog(existing[0], parent=self, playlist=existing, auto_close=True)
        player.exec()

    def _on_video_double_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            player = VideoPlayerDialog(path, parent=self, auto_close=True)
            player.exec()

    def _delete_selected_video(self):
        keys = self.video_grid.selected_keys()
        if not keys:
            return
        n = len(keys)
        if n == 1:
            msg = f"Permanently delete:\n{Path(keys[0]).name}?\n\nThis cannot be undone."
        else:
            msg = f"Permanently delete {n} videos?\n\nThis cannot be undone."
        reply = QMessageBox.question(
            self, "Delete Video", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        freed_stems: set[str] = set()
        for key in keys:
            path = Path(key)
            try:
                path.unlink()
                (path.parent / "thumbnails" / (path.stem + ".jpg")).unlink(missing_ok=True)
                unstamped = RUN_STAMP_RE.sub("", path.stem)
                freed_stems.update({path.stem, unstamped, re.sub(r'_\d+$', '', unstamped)})
            except OSError as e:
                errors.append(f"{path.name}: {e}")
        if errors:
            QMessageBox.critical(self, "Error", "Some files could not be deleted:\n" + "\n".join(errors))
        for item in self.video_grid.selectedItems():
            self.video_grid.takeItem(self.video_grid.row(item))
        self._vid_delete_btn.setEnabled(False)
        count = self.video_grid.count()
        self._vid_status_label.setText(
            f"{count} video{'s' if count != 1 else ''} — double-click to play"
            if count > 0 else "No video files found in folder"
        )

        # A deleted video means its source image was a bad generation —
        # un-mark it as processed so it reappears in the chain's image list.
        if freed_stems:
            chain = self.config.get("active_chain_folder", "").strip()
            self._unrecord_processed(self._current_input_dir(), chain, freed_stems)
            self._apply_image_filter()

    def _show_video_settings(self):
        keys = self.video_grid.selected_keys()
        if len(keys) != 1:
            return
        dlg = VideoSettingsDialog(keys[0], parent=self)
        dlg.exec()

    def _convert_selected_videos(self):
        keys = self.video_grid.selected_keys()
        if not keys:
            return

        # Default output folder = same folder as first selected video
        default_out = str(Path(keys[0]).parent)
        dlg = ConvertDialog(len(keys), default_out, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        preset = dlg.selected_preset()
        out_dir = dlg.output_dir()
        if not out_dir:
            QMessageBox.warning(self, "Convert", "Please choose an output folder.")
            return

        # Progress dialog
        self._convert_progress = QProgressDialog(
            f"Converting 0 / {len(keys)}...", "Cancel", 0, len(keys), self
        )
        self._convert_progress.setWindowTitle("Converting Videos")
        self._convert_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._convert_progress.setMinimumWidth(420)
        self._convert_progress.setAutoClose(False)
        self._convert_progress.setAutoReset(False)
        self._convert_progress.setValue(0)
        self._convert_progress.show()

        self._converter = VideoConverterThread(keys, preset, out_dir, self._ffmpeg_path())
        self._converter.progress.connect(self._on_convert_progress)
        self._converter.finished.connect(self._on_convert_finished)
        self._convert_progress.canceled.connect(self._converter.cancel)
        self._converter.start()

    def _on_convert_progress(self, current: int, total: int, filename: str):
        self._convert_progress.setLabelText(f"Converting {current} / {total}: {filename}")
        self._convert_progress.setValue(current)

    def _on_convert_finished(self, success: int, errors: list):
        self._convert_progress.close()
        if errors:
            err_text = "\n".join(errors[:10])
            if len(errors) > 10:
                err_text += f"\n…and {len(errors) - 10} more"
            QMessageBox.warning(
                self, "Convert",
                f"Converted {success} file{'s' if success != 1 else ''} successfully.\n\n"
                f"Errors ({len(errors)}):\n{err_text}"
            )
        else:
            QMessageBox.information(
                self, "Convert",
                f"Done — {success} file{'s' if success != 1 else ''} converted successfully."
            )

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    def _refresh_chain_folders(self):
        wf_dir = Path(self.config.get("workflow_dir", ""))
        self._chain_folder_combo.blockSignals(True)
        self._chain_folder_combo.clear()
        if wf_dir.exists():
            folders = sorted(
                p.name for p in wf_dir.iterdir()
                if p.is_dir()
            )
            for f in folders:
                self._chain_folder_combo.addItem(f)
        last = self.config.get("active_chain_folder", "")
        if last:
            idx = self._chain_folder_combo.findText(last)
            if idx >= 0:
                self._chain_folder_combo.setCurrentIndex(idx)
        self._chain_folder_combo.blockSignals(False)
        # Always persist whatever folder is currently shown so the worker sees it
        current = self._chain_folder_combo.currentText()
        if current:
            self.config.set("active_chain_folder", current)
            self.config.save()
        # Rebuild segment panel to reflect the now-selected folder
        self._rebuild_seg_panel()
        self._sync_lib_dir_display()
        # Pre-validate the chain that came up selected (startup restores the
        # last-used one without any dropdown interaction) so the user learns
        # right away whether it needs fixing. Only pop the dialog once the
        # window is on screen; at startup it is deferred to showEvent.
        self._validate_active_chain(show_dialog=self.isVisible())

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_startup_validation_shown", False):
            self._startup_validation_shown = True
            if self._chain_errors:
                # Let the window paint first, then explain what is wrong.
                QTimer.singleShot(0, lambda: self._report_chain_validation(startup=True))
            # After the window is actually on screen, so the pod prompt has
            # a parent to centre on rather than appearing behind it.
            QTimer.singleShot(200, self._pod.check_on_launch)

    def _on_chain_folder_changed(self, _idx: int):
        folder = self._chain_folder_combo.currentText()
        self.config.set("active_chain_folder", folder)
        self.config.save()
        self._rebuild_seg_panel()
        self._validate_active_chain(show_dialog=True)
        # Re-filter in place — no rescan of the image folder
        self._apply_image_filter()
        self._sync_lib_dir_display()

    # ------------------------------------------------------------------ #
    # Batch workflow validation
    # ------------------------------------------------------------------ #

    def _active_chain_dir(self) -> Path:
        wf_dir = Path(self.config.get("workflow_dir", ""))
        folder = self.config.get("active_chain_folder", "").strip()
        return wf_dir / folder if folder else wf_dir

    def _validate_active_chain(self, show_dialog: bool, remote: bool = True) -> bool:
        """Check every workflow_segment_*_batch.json the active chain would
        run (wiring + LoRA inventory). Updates the status line under the
        Chain selector, gates the Start / Auto Run buttons, and (optionally)
        pops a dialog spelling out exactly what must change. Returns True
        when the chain is OK. remote=False skips re-launching the
        background pod check (used by Start, which needs a sync answer)."""
        self._chain_errors, self._chain_warnings = validate_batch_chain_dir(
            self._active_chain_dir())
        self._check_chain_loras(remote=remote)
        self._refresh_chain_status()
        if show_dialog and self._chain_errors:
            self._report_chain_validation(startup=False)
        return not self._chain_errors

    def _check_chain_loras(self, remote: bool):
        """Every LoRA the chain's batch workflows name must exist in the
        local LoRA folder (blocking) and, in RunPod mode, on the pod's
        volume (checked via S3 in the background; missing ones are queued
        for upload rather than blocking)."""
        self._pod_missing_jobs = []
        self._lora_remote_error = ""
        if remote:
            self._lora_remote_pending = False
            self._lora_remote_note = ""
        self._lora_refs = {}
        if not self.config.get(CFG_LORA_CHECK, True):
            return
        self._lora_refs = collect_chain_loras(self._active_chain_dir())
        if not self._lora_refs:
            return
        loras_dir = (self.config.get("loras_dir", "") or "").strip()
        if not loras_dir or not Path(loras_dir).is_dir():
            self._chain_errors.append(
                f"LoRA folder is not set or does not exist ({loras_dir or 'blank'}). "
                f"This chain uses {len(self._lora_refs)} LoRA(s); set Settings > Folders > "
                f"LoRA Folder to the models/loras folder of the ComfyUI install you run."
            )
            return
        local = check_local_loras(loras_dir, self._lora_refs.keys())
        for name in local.missing:
            files = ", ".join(self._lora_refs[name])
            self._chain_errors.append(
                f"LoRA '{name}' (used by {files}) is not in the local LoRA folder "
                f"{loras_dir}. Put the file there, or double-click the segment's dot and "
                f"pick a different LoRA from the dropdown."
            )
        for name, actual in local.case_mismatch.items():
            self._chain_warnings.append(
                f"LoRA '{name}' is on disk as '{actual}' (different capitalization). Windows "
                f"finds it, the Linux pod will not — rename the file or fix the workflow."
            )
        if self.config.get("mode", "local") != "runpod":
            return
        cfg = self.config.get_all()
        if not s3_configured(cfg):
            self._chain_warnings.append(
                "RunPod mode: S3 volume access is not configured (Settings > RunPod Volume), so "
                "the LoRAs on the pod were not verified — a missing file will fail on the server."
            )
            return
        if not remote:
            # Start re-validates synchronously; keep the last pod result.
            self._pod_missing_jobs = self._last_pod_missing_jobs(local)
            return
        self._lora_remote_pending = True
        self._lora_remote_note = "Checking which LoRAs are on the pod..."
        self._remote_check_token += 1
        token = self._remote_check_token
        worker = RemoteLoraCheckWorker(cfg, sorted(self._lora_refs.keys()), local)
        worker.done.connect(lambda status, t=token, l=local: self._on_remote_lora_check(t, l, status))
        self._remote_check_worker = worker
        worker.start()

    def _last_pod_missing_jobs(self, local) -> list[LoraUploadJob]:
        names = getattr(self, "_last_pod_missing_names", [])
        jobs = []
        for name in names:
            path = local.present.get(name)
            if path is not None:
                jobs.append(LoraUploadJob(name, path, path.stat().st_size))
        return jobs

    def _on_remote_lora_check(self, token: int, local, status):
        if token != self._remote_check_token:
            return  # a newer check superseded this one
        self._lora_remote_pending = False
        if status.error:
            self._lora_remote_error = status.error
            self._lora_remote_note = (
                f"Could not check the pod's LoRA folder ({status.error}). "
                f"The batch can still start, but a LoRA missing on the pod will fail there."
            )
            self._last_pod_missing_names = []
        else:
            self._last_pod_missing_names = list(status.missing)
            jobs = []
            for name in status.missing:
                path = local.present.get(name)
                if path is not None:
                    jobs.append(LoraUploadJob(name, path, path.stat().st_size))
            self._pod_missing_jobs = jobs
            parts = []
            if jobs:
                total_mb = sum(j.size for j in jobs) / 1e6
                parts.append(
                    f"{len(jobs)} LoRA(s) missing on the pod ({total_mb:.0f} MB) — they will be "
                    f"uploaded when you press Start Batch, or press ⇅ LoRAs now: "
                    + ", ".join(j.name for j in jobs)
                )
            if status.size_mismatch:
                parts.append("Size differs local vs pod (re-upload with ⇅ LoRAs to be safe): " + ", ".join(
                    f"{n} ({l / 1e6:.0f} MB vs {r / 1e6:.0f} MB)" for n, (l, r) in status.size_mismatch.items()))
            if not parts:
                parts.append(f"All {len(status.present)} LoRA(s) this chain uses are on the pod.")
            self._lora_remote_note = "\n".join(parts)
        self._refresh_chain_status()
        if self._start_after_upload:
            self._start_after_upload = False
            if self._pod_missing_jobs:
                QMessageBox.critical(
                    self, "LoRA upload incomplete",
                    "Some LoRAs are still missing on the pod after the upload:\n  "
                    + "\n  ".join(j.name for j in self._pod_missing_jobs)
                    + "\n\nThe batch was not started.")
            elif not self._lora_remote_error:
                self._start()

    def _refresh_chain_status(self):
        folder = self._chain_folder_combo.currentText() or "(none)"
        if self._chain_errors:
            n = len(self._chain_errors)
            # One line per problem (file + what is wrong); the full text with
            # the fix for each lives in the dialog and the tooltip.
            shown = [e.split("\n", 1)[0] for e in self._chain_errors[:3]]
            more = n - len(shown)
            lines = [f"• {e}" for e in shown]
            if more:
                lines.append(f"• … and {more} more")
            lines.append("Start Batch is disabled — fix the workflow(s), re-export (API), "
                         "then press ↻ or re-select the chain.")
            self._chain_status_label.setStyleSheet(
                f"color:{COLORS['error']}; font-size:9pt; padding:2px 4px;")
            self._chain_status_label.setText(
                f"⚠ Chain '{folder}' cannot run — {n} problem{'s' if n != 1 else ''} "
                f"in its batch workflows:\n" + "\n".join(lines)
            )
            self._chain_status_label.setToolTip("\n\n".join(self._chain_errors))
            self._chain_status_label.show()
            self.start_btn.setToolTip(
                "Disabled: fix the batch workflow problems listed under the Chain selector")
        elif self._chain_warnings:
            self._chain_status_label.setStyleSheet(
                f"color:{COLORS['warning']}; font-size:9pt; padding:2px 4px;")
            self._chain_status_label.setText(
                "\n".join(f"• {w}" for w in self._chain_warnings))
            self._chain_status_label.show()
            self.start_btn.setToolTip("")
        else:
            self._chain_status_label.clear()
            self._chain_status_label.hide()
            self.start_btn.setToolTip("")
        # Pod LoRA status rides along under the wiring/local verdict
        if self._lora_remote_note and not self._chain_errors:
            color = COLORS['warning'] if (self._pod_missing_jobs or self._lora_remote_error
                                          or self._lora_remote_pending) else COLORS['success']
            existing = self._chain_status_label.text()
            self._chain_status_label.setStyleSheet(
                f"color:{color}; font-size:9pt; padding:2px 4px;")
            self._chain_status_label.setText(
                (existing + "\n" if existing else "") + self._lora_remote_note)
            self._chain_status_label.show()
        self._sync_loras_btn.setEnabled(
            bool(self._pod_missing_jobs) and not self._lora_remote_pending
            and not (self._lora_upload_worker and self._lora_upload_worker.isRunning()))
        self._update_start_enabled()
        self._update_auto_buttons()

    def _report_chain_validation(self, startup: bool):
        folder = self._chain_folder_combo.currentText() or "(none)"
        lead = (
            f"The chain '{folder}' loaded at startup cannot be run as a batch."
            if startup else
            f"The chain '{folder}' cannot be run as a batch."
        )
        body = "\n\n".join(
            f"{i}. {e}" for i, e in enumerate(self._chain_errors, 1))
        text = (
            f"{lead}\n\n{body}\n\n"
            "Start Batch stays disabled until every problem above is fixed. "
            "After re-exporting the workflow, press ↻ next to the Chain selector "
            "or re-select the chain to check again."
        )
        # A plain QMessageBox grows with its text and can run off the screen
        # when a chain has several broken segments — use a scrollable dialog.
        dlg = QDialog(self)
        dlg.setWindowTitle("Batch workflow needs fixing")
        dlg.setMinimumSize(760, 440)
        lay = QVBoxLayout(dlg)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        lay.addWidget(view)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    def _update_start_enabled(self):
        running = self._worker is not None and self._worker.isRunning()
        loading = self._img_loader is not None and self._img_loader.isRunning()
        uploading = self._lora_upload_worker is not None and self._lora_upload_worker.isRunning()
        self.start_btn.setEnabled(
            not running and not loading and not uploading
            and not self._lora_remote_pending and not self._chain_errors)

    # ------------------------------------------------------------------ #
    # LoRA upload to the pod
    # ------------------------------------------------------------------ #

    def _sync_loras_clicked(self):
        if not self._pod_missing_jobs:
            QMessageBox.information(self, "LoRAs", "Nothing to upload — every LoRA this chain uses is on the pod.")
            return
        self._start_after_upload = False
        self._run_lora_upload()

    def _run_lora_upload(self):
        jobs = list(self._pod_missing_jobs)
        if not jobs:
            return
        self._lora_upload_worker = LoraUploadWorker(self.config.get_all(), jobs)
        self._lora_upload_worker.log.connect(self._on_log)
        self._lora_upload_worker.progress.connect(self._on_lora_upload_progress)
        self._lora_upload_worker.finished_ok.connect(self._on_lora_upload_done)
        total_mb = sum(j.size for j in jobs) / 1e6
        self._on_log(f"Uploading {len(jobs)} LoRA(s) ({total_mb:.0f} MB) to the pod's LoRA folder...")
        self.progress_label.setText(f"Uploading LoRAs 0/{len(jobs)}...")
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self._lora_upload_worker.start()
        self._update_start_enabled()
        self._sync_loras_btn.setEnabled(False)

    def _on_lora_upload_progress(self, done: int, total: int, name: str, files_done: int, files_total: int):
        self.progress_bar.setValue(int(done * 1000 / total) if total else 0)
        self.progress_label.setText(
            f"Uploading LoRAs {files_done}/{files_total} — {name}  ({done / 1e6:.0f} / {total / 1e6:.0f} MB)")

    def _on_lora_upload_done(self, errors: list):
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        if errors:
            self.progress_label.setText("LoRA upload failed")
            self._start_after_upload = False
            QMessageBox.critical(
                self, "LoRA upload failed",
                "These LoRAs did not make it to the pod:\n\n"
                + "\n".join(f"{n}: {e}" for n, e in errors)
                + "\n\nFix the problem and press ⇅ LoRAs to retry. The batch was not started.")
        else:
            self.progress_label.setText("LoRA upload complete — re-checking the pod...")
            self._on_log("All LoRAs uploaded. Re-checking the pod's LoRA folder...")
        # Re-run the pod check; if a Start was waiting on the upload it
        # resumes from _on_remote_lora_check once the pod confirms the files.
        self._validate_active_chain(show_dialog=False)

    def _on_seg_dot_double_clicked(self, segment: int):
        workflow_dir = Path(self.config.get("workflow_dir", ""))
        folder = self.config.get("active_chain_folder", "")
        if folder:
            seg_file = f"workflow_segment_{segment:02d}_batch.json"
            json_path = workflow_dir / folder / seg_file
        else:
            workflows = self.config.get("workflows", [])
            wf = next((w for w in workflows if w["segment"] == segment), None)
            if not wf:
                return
            json_path = workflow_dir / wf["json_file"]
        dlg = SegmentEditorDialog(segment, json_path, config=self.config, parent=self)
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog(self.config, parent=self)
        if dlg.exec():
            self._refresh_chain_folders()
            self._populate_images()
            self._sync_lib_dir_display()
            self._generate_tab.refresh_mode()
            self._generate_tab.refresh_workflows()
            self._prompt_writer_tab.refresh_mode()

    # ------------------------------------------------------------------ #
    # Generate tab signal handlers
    # ------------------------------------------------------------------ #

    def _inject_generated_image(self, path: str):
        """Add a generated image into the chain grid and select it."""
        input_dir = Path(self._input_dir_edit.text().strip() or self.config.get("input_dir", ""))
        img_path = Path(path)
        try:
            key = str(img_path.relative_to(input_dir))
        except ValueError:
            key = img_path.name

        # If already in grid, just select it
        self.image_grid.select_key(key)
        if self.image_grid.selected_key() == key:
            self.selected_label.setText(f"Selected: {key}")
            return

        # Load thumbnail and add to grid
        img = QImage(path)
        if img.isNull():
            return
        img = img.scaled(
            THUMB_SIZE, THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_grid.add_item(img, key, img_path.name)
        self.image_grid.select_key(key)
        self.selected_label.setText(f"Selected: {key}")

    def _on_send_to_chain(self, path: str):
        self._inject_generated_image(path)
        self._switch_view(0)

    def _on_start_one_shot(self, path: str):
        self._inject_generated_image(path)
        self._switch_view(0)
        self._start()

    # ------------------------------------------------------------------ #
    # Auto mode
    # ------------------------------------------------------------------ #

    def _select_next_auto_batch(self) -> bool:
        """Select the next _auto_size_spin visible images from the top of the
        grid. Returns False if no unprocessed images remain."""
        self.image_grid.clearSelection()
        visible = self._visible_image_items()
        if not visible:
            return False
        for item in visible[:self._auto_size_spin.value()]:
            item.setSelected(True)
        keys = self.image_grid.selected_keys()
        if keys:
            self.selected_label.setText(f"{len(keys)} image{'s' if len(keys) > 1 else ''} selected  (auto)")
            return True
        return False

    def _start_auto(self):
        if not self._select_next_auto_batch():
            QMessageBox.information(self, "Auto Run", "No images remaining in the grid.")
            return
        self._auto_mode = True
        self._auto_stop_requested = False
        self._auto_continue = False
        self._update_auto_buttons()
        self._start()

    def _stop_auto_after_batch(self):
        self._auto_stop_requested = True
        self._stop_auto_btn.setEnabled(False)
        self.progress_label.setText(self.progress_label.text() + "  (stopping after batch…)")

    def _update_auto_buttons(self):
        show_all = self._show_all_chk.isChecked()
        running = self._auto_mode and not self._auto_stop_requested
        blocked = bool(self._chain_errors)
        self._auto_btn.setEnabled(not self._auto_mode and not show_all and not blocked)
        self._auto_btn.setToolTip(
            "Disabled: the selected chain's batch workflows failed validation — "
            "see the message under the Chain selector"
            if blocked else
            "Disabled: uncheck 'Show all' before using Auto Run"
            if show_all else
            "Automatically process all images N at a time, no prompts between batches"
        )
        self._stop_auto_btn.setEnabled(running)

    # ------------------------------------------------------------------ #
    # Chain start / cancel
    # ------------------------------------------------------------------ #

    def _start(self):
        self.config.save()
        self.final_label.setText("")

        keys = self.image_grid.selected_keys()
        if not keys:
            QMessageBox.critical(self, "Error", "Select at least one image for the batch.")
            return
        # Re-check right before starting — the JSON may have been edited (or
        # broken) since the chain was selected.
        if not self._validate_active_chain(show_dialog=True, remote=False):
            if self._auto_mode:
                self._auto_mode = False
                self._auto_stop_requested = False
                self._update_auto_buttons()
            return
        if self._pod.over_limit():
            limit = float(self.config.get("runpod_spend_limit", 0) or 0)
            if self._auto_mode:
                self._auto_mode = False
                self._auto_stop_requested = False
                self._update_auto_buttons()
            QMessageBox.warning(
                self, "Spend limit reached",
                f"This pod has hit the ${limit:.2f} session limit, so no new batches are "
                "being started. It will stop once the current batch finishes.\n\n"
                "Raise the limit in Settings > RunPod to keep going.")
            return
        if self._pod_missing_jobs:
            names = "\n  ".join(f"{j.name} ({j.size / 1e6:.0f} MB)" for j in self._pod_missing_jobs)
            total_mb = sum(j.size for j in self._pod_missing_jobs) / 1e6
            answer = QMessageBox.question(
                self, "Upload missing LoRAs?",
                f"This chain uses {len(self._pod_missing_jobs)} LoRA(s) that are not on the pod "
                f"({total_mb:.0f} MB total):\n\n  {names}\n\n"
                "Upload them from the local LoRA folder now? The batch starts automatically "
                "once the pod confirms the files.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                if self._auto_mode:
                    self._auto_mode = False
                    self._auto_stop_requested = False
                    self._update_auto_buttons()
                return
            self._start_after_upload = True
            self._run_lora_upload()
            return
        self._reset_ui()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_label.setText(f"Batch: {len(keys)} images — Starting...")
        sep_date = datetime.now().strftime("%m/%d/%Y  %H:%M:%S")
        self._write_daily_log("")
        self._write_daily_log("=" * 80)
        self._write_daily_log(f"  NEW BATCH  |  {sep_date}  |  {len(keys)} image(s)")
        self._write_daily_log("=" * 80)
        for k in keys:
            self._write_daily_log(f"  - {Path(k).name}")
        eff_dir = self._effective_video_dir()
        eff_dir.mkdir(parents=True, exist_ok=True)
        # Snapshot for the processed registry — chain/folder could be switched
        # in the UI while the batch runs
        self._batch_registry_ctx = (
            self._current_input_dir(),
            self.config.get("active_chain_folder", "").strip(),
            list(keys),
        )
        if self._worker:
            self._worker.wait(5000)
        worker_cfg = self.config.get_all()
        worker_cfg["final_video_dir"] = str(eff_dir)
        worker_cfg["ffmpeg_path"] = self._ffmpeg_path()
        self._worker = BatchChainWorker(worker_cfg, keys)
        self._worker.log.connect(self._on_log)
        self._worker.segment_done.connect(self._on_segment_done)
        self._worker.segment_time.connect(self._on_segment_time)
        self._worker.segment_secs.connect(self._on_segment_secs)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.segment_plan.connect(self._on_segment_plan)
        self._worker.phase_progress.connect(self._on_phase_progress)
        self._worker.all_done.connect(self._on_batch_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._pod.cancel_idle_timer()
        self._worker.start()
        self._seg_dots[0].set_active()
        self.progress_label.setText(f"Batch: {len(keys)} images — Segment 1/{self._seg_count}...")

    def _cancel(self):
        if self._lora_upload_worker and self._lora_upload_worker.isRunning():
            self._lora_upload_worker.cancel()
            self._start_after_upload = False
            self._on_log("Cancelling LoRA upload after the current file...")
        if self._worker:
            self._worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.progress_label.setText("Cancelling...")

    # ------------------------------------------------------------------ #
    # Worker signal handlers
    # ------------------------------------------------------------------ #

    _LOG_NOISE = ("] Running... (", "] Queued... (", "] Waiting for history... (", "] Not yet in history... (")

    def _on_log(self, message: str):
        self.log_list.addItem(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        self.log_list.scrollToBottom()
        if not any(n in message for n in self._LOG_NOISE):
            self._write_daily_log(message)

    def _on_segment_time(self, seg: int, elapsed: str):
        if seg - 1 < len(self._seg_time_labels):
            self._seg_time_labels[seg - 1].setText(elapsed)
            self._seg_time_labels[seg - 1].setStyleSheet(
                f"color:{COLORS['success']}; font-size:10pt; font-family:Consolas; font-weight:bold;"
            )

    def _on_segment_secs(self, seg: int, secs: float):
        self._seg_times_sec[seg] = secs

    def _on_segment_plan(self, seg: int, passes: int, total_steps: int, post_phases: int):
        """Worker parsed the segment's workflow: `passes` sampler executions
        (samplers × images) totalling `total_steps` steps, plus `post_phases`
        post-sampler stages (VAE decode, encode, save) that have no step-level
        progress of their own but still take real time. (0, 0, 0) if the
        workflow had no readable sampler nodes."""
        self._seg_plan = (passes, total_steps)
        self._seg_post_phases = post_phases
        self._post_phase_done = 0
        self._sampler_done = 0

    def _on_step_progress(self, seg: int, value: int, vmax: int):
        if vmax <= 0:
            return
        # Each sampler pass restarts the raw step counter; count the passes
        # (and the steps they contained) so progress only ever moves forward.
        if seg != self._step_seg:
            self._step_seg = seg
            self._step_cycle = 1
            self._steps_before = 0
            self._post_phase_done = 0
        elif value < self._step_last_value:
            self._step_cycle += 1
            self._steps_before += self._step_last_max
        self._step_last_value = value
        self._step_last_max = vmax

        frac = min(value / vmax, 1.0)
        _, plan_steps = self._seg_plan
        self._sampler_done = min(self._steps_before + value, plan_steps) if plan_steps else 0
        self._render_step_progress(seg, frac)

    def _on_phase_progress(self, seg: int):
        """A post-sampler node (VAE decode, encode, save) started — the
        sampler already reported 100%, so without this the bar would sit at
        a false "done" for however long that stage takes."""
        if seg != self._step_seg or not self._seg_post_phases:
            return
        self._post_phase_done = min(self._post_phase_done + 1, self._seg_post_phases)
        self._render_step_progress(seg, 1.0)

    def _render_step_progress(self, seg: int, frac: float):
        _, plan_steps = self._seg_plan
        total = plan_steps + self._seg_post_phases
        if plan_steps:
            # Exact plan from the workflow JSON: step bar fills once across
            # the whole segment (all samplers × all images, then any
            # post-sampler decode/encode/save phases)
            done = min(self._sampler_done + self._post_phase_done, total)
            seg_frac = done / total
            self.step_bar.setValue(int(seg_frac * 100))
            self.step_bar.setFormat(f"Step {done}/{total}")
            step_txt = f"step {done}/{total}"
        else:
            # Fallback: per-pass step bar + pass count learned from segment 1
            self.step_bar.setValue(int(frac * 100))
            self.step_bar.setFormat(f"Step {self._step_last_value}/{self._step_last_max}")
            step_txt = f"step {self._step_last_value}/{self._step_last_max}"
            if self._cycles_per_seg:
                seg_frac = min((self._step_cycle - 1 + frac) / self._cycles_per_seg, 1.0)
            else:
                seg_frac = frac  # first segment: pass count not yet known

        bar_val = int(((seg - 1) + seg_frac) * 100)
        if bar_val > self.progress_bar.value():
            self.progress_bar.setValue(bar_val)

        eta = self._estimate_eta(seg, seg_frac)
        eta_txt = f"  —  ~{eta} left" if eta else ""
        stop_txt = "  (stopping after batch…)" if self._auto_stop_requested else ""
        self.progress_label.setText(
            f"Batch — Segment {seg}/{self._seg_count} — {step_txt}{eta_txt}{stop_txt}"
        )

    def _estimate_eta(self, seg: int, frac: float) -> str:
        """Project time left from this session's per-segment wall times.
        Empty until at least one segment has completed."""
        if not self._seg_times_sec:
            return ""
        avg = sum(self._seg_times_sec.values()) / len(self._seg_times_sec)
        remaining = 0.0
        for s in range(seg, self._seg_count + 1):
            expected = self._seg_times_sec.get(s, avg)
            remaining += expected * (1.0 - frac) if s == seg else expected
        m, s_ = divmod(int(remaining), 60)
        return f"{m}m {s_:02d}s" if m else f"{s_}s"

    def _on_segment_done(self, seg: int):
        n = self._seg_count
        if seg - 1 < len(self._seg_dots):
            self._seg_dots[seg - 1].set_done()
        self.progress_bar.setValue(seg * 100)
        if not self._cycles_per_seg and seg == self._step_seg:
            self._cycles_per_seg = self._step_cycle
        self.step_bar.setValue(0)
        self.step_bar.setFormat("Step —")
        if seg < n:
            if seg < len(self._seg_dots):
                self._seg_dots[seg].set_active()
            self.progress_label.setText(f"Batch — Segment {seg + 1}/{n} — running...")
        else:
            self.progress_label.setText("Stitching all videos...")

    def _alert(self):
        """The one alert sound (Settings > Prompts & Sound), shared with the
        pod chain's "pod found" / "gave up" alerts."""
        if not self.config.get("alert_sound_enabled", True):
            return
        alerts.play(self.config.get("alert_sound_path", ""))

    def _on_batch_done(self, final_paths: list):
        n = len(final_paths)
        self._write_daily_log(f"=== Batch complete: {n} video{'s' if n != 1 else ''} ===")
        self.progress_label.setText(f"Batch complete — {n} video{'s' if n != 1 else ''}")
        self.final_label.setText(f"{n} videos saved to final video folder")

        # Remember these images as processed for this chain, so the history
        # survives the finished videos being moved out of the output folder
        if self._batch_registry_ctx:
            in_dir, chain, keys = self._batch_registry_ctx
            self._record_processed(in_dir, chain, keys)
            self._batch_registry_ctx = None

        # Newly stitched videos exist now, so re-filtering hides their images
        self._apply_image_filter()

        # ── Auto mode: skip dialog and continue or stop ───────────────────
        if self._auto_mode:
            if not self._auto_stop_requested and self._select_next_auto_batch():
                # Next batch is started from _on_worker_finished, once the
                # current worker thread has fully exited — starting it here
                # would drop the last reference to a still-running QThread.
                self._auto_continue = True
            else:
                # No more images, or stop was requested — wind down auto mode
                remaining = len(self._visible_image_items())
                if self._auto_stop_requested:
                    self.progress_label.setText("Auto mode stopped by user.")
                else:
                    self.progress_label.setText(f"Auto mode complete — no images remaining.")
                self._write_daily_log(
                    f"=== Auto mode ended — {remaining} image(s) left in grid ==="
                )
                # Overnight runs end here — worth walking back for.
                self._alert()
                self._auto_mode = False
                self._auto_stop_requested = False
                self._update_auto_buttons()
            return

        # ── Normal mode: ask to play ──────────────────────────────────────
        self._alert()
        msg = "\n".join(Path(p).name for p in final_paths)
        reply = QMessageBox.question(
            self, "Batch Complete",
            f"Generated {n} video{'s' if n != 1 else ''}:\n\n{msg}\n\nPlay all videos now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            seen: set[str] = set()
            existing = []
            for p in final_paths:
                if Path(p).exists() and p not in seen:
                    existing.append(p)
                    seen.add(p)
            if existing:
                # Batch-completion playback closes itself after the last result.
                player = VideoPlayerDialog(existing[0], parent=self, playlist=existing, auto_close=True)
                player.exec()

    def _on_error(self, message: str):
        self._write_daily_log(f"ERROR: {message}")
        self.progress_label.setText("Error")
        if self._auto_mode:
            self._auto_mode = False
            self._auto_stop_requested = False
            self._update_auto_buttons()
        QMessageBox.critical(self, "Error", message)

    def _on_worker_finished(self):
        if self._auto_continue:
            self._auto_continue = False
            self._start()
            return
        if self._auto_mode:
            # Worker finished without completing a batch (cancelled / error mid-auto)
            self._auto_mode = False
            self._auto_stop_requested = False
            self._update_auto_buttons()
        self._update_start_enabled()
        self.cancel_btn.setEnabled(False)
        # A deferred "stop when the spend limit is hit" lands here, once the
        # batch it was waiting for has actually finished; otherwise the idle
        # countdown (Settings > RunPod > Idle stop) arms.
        self._pod.run_finished()
        self._pod.start_idle_timer()

    # ------------------------------------------------------------------ #
    # Daily log
    # ------------------------------------------------------------------ #

    def _write_daily_log(self, message: str):
        vid_dir = self._effective_video_dir()
        if not vid_dir.exists():
            try:
                vid_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return
        today = datetime.now().strftime("%m_%d_%Y")
        log_path = vid_dir / f"ComfyUI_Chain_Log_{today}.txt"
        timestamp = datetime.now().strftime("%H:%M:%S")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _reset_ui(self):
        for dot in self._seg_dots:
            dot.set_pending()
        for lbl in self._seg_time_labels:
            lbl.setText("—")
            lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:8pt; font-family:Arial;")
        self.progress_bar.setValue(0)
        self.step_bar.setValue(0)
        self.step_bar.setFormat("Step —")
        self._step_seg = 0
        self._step_last_value = 0
        self._step_last_max = 0
        self._step_cycle = 1
        self._steps_before = 0
        self._seg_plan = (0, 0)
        self._cycles_per_seg = 0
        self._seg_post_phases = 0
        self._post_phase_done = 0
        self._sampler_done = 0
        self.log_list.clear()

    def closeEvent(self, event):
        for loader in (self._img_loader, self._vid_loader):
            if loader and loader.isRunning():
                loader.cancel()
                loader.wait(3000)
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        # Ask about any pod this session is connected to — one adopted from the
        # launch chooser too, not only one this app started.
        if self._pod.pod_id and self.config.get("runpod_auto_stop_on_exit", True):
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
            if ans == QMessageBox.StandardButton.Yes:
                self._pod.shutdown()
            else:
                self._pod.leave_running()
        self.config.set("input_dir", self._input_dir_edit.text().strip())
        self.config.set("active_chain_folder", self._chain_folder_combo.currentText())
        self.config.save()
        event.accept()
