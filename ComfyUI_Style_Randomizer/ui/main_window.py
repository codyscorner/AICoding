import random
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps
from PyQt6.QtCore import Qt, QByteArray, QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QImage, QColor, QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QLineEdit,
    QProgressBar, QListWidget, QListWidgetItem, QGroupBox,
    QVBoxLayout, QHBoxLayout, QSplitter, QStackedWidget,
    QFileDialog, QAbstractItemView, QPlainTextEdit, QCheckBox,
    QStatusBar, QComboBox, QMessageBox, QDialog, QSizePolicy,
    QSpinBox, QProgressDialog,
)

import csv

from config import ConfigManager
from worker import (
    BatchStyleWorker, append_daily_log, load_prompts, log_prompt_used, PromptEntry,
    IMAGE_EXTS, OUTPUT_EXTS, PROMPT_LOG_NAME,
)
from ui.styles import COLORS
from ui.settings_dialog import SettingsDialog
from ui.prompt_editor import PromptEditorDialog
from ui.pin_dialog import PinPromptDialog
from ui.pod_control import PodControl
import alerts
import json
import time
import model_sync
import textwrap

THUMB_SIZE = 120

SORT_OPTIONS = [
    ("Newest First",   lambda p: p.stat().st_mtime, True),
    ("Oldest First",   lambda p: p.stat().st_mtime, False),
    ("Name A → Z",     lambda p: p.name.lower(),    False),
    ("Name Z → A",     lambda p: p.name.lower(),    True),
    ("Largest First",  lambda p: p.stat().st_size,  True),
    ("Smallest First", lambda p: p.stat().st_size,  False),
]

_MODE_BTN_STYLE = f"""
    QPushButton {{
        background-color: {COLORS['bg_light']};
        color: {COLORS['fg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: 4px;
        font-size: 10pt;
        font-weight: bold;
        padding: 4px 18px;
        min-width: 100px;
    }}
    QPushButton:checked {{
        background-color: {COLORS['accent']};
        color: white;
        border: 1px solid {COLORS['accent']};
    }}
    QPushButton:hover:!checked {{ background-color: {COLORS['bg_medium']}; }}
"""


# ------------------------------------------------------------------ #
# Background image loaders
# ------------------------------------------------------------------ #

class ImageLoaderThread(QThread):
    image_ready       = pyqtSignal(QImage, str, str, bool)  # img, key, label, is_processed
    thumbnails_needed = pyqtSignal(int)                      # count before generation starts
    gen_progress      = pyqtSignal(int, int)                 # current, total (generation phase)
    progress          = pyqtSignal(int, int)                 # loaded, total (loading phase)
    finished_loading  = pyqtSignal(int)

    def __init__(self, input_dir: Path, processed_stems: set | None = None, show_all: bool = False):
        super().__init__()
        self._input_dir = input_dir
        self._processed_stems = processed_stems or set()
        self._show_all = show_all
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            all_images = sorted(
                (p for p in self._input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            self.finished_loading.emit(0)
            return

        thumb_dir = self._input_dir / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)

        # Phase 1: generate missing thumbnails for all images in folder
        missing = [
            (p, thumb_dir / (p.stem + ".jpg"))
            for p in all_images
            if not (thumb_dir / (p.stem + ".jpg")).exists()
        ]
        if missing:
            self.thumbnails_needed.emit(len(missing))
            for i, (img_path, thumb_path) in enumerate(missing, 1):
                if self._cancelled:
                    return
                self._generate_thumb(img_path, thumb_path)
                self.gen_progress.emit(i, len(missing))

        # Phase 2: load filtered set from cache
        images = [
            p for p in all_images
            if self._show_all or p.stem not in self._processed_stems
        ]
        total  = len(images)
        loaded = 0
        for img_path in images:
            if self._cancelled:
                return
            is_processed = img_path.stem in self._processed_stems
            thumb_path = thumb_dir / (img_path.stem + ".jpg")
            img = QImage(str(thumb_path))
            if img.isNull():
                try:
                    pil = Image.open(img_path)
                    pil = ImageOps.exif_transpose(pil).convert("RGBA")
                    data = pil.tobytes("raw", "RGBA")
                    img = QImage(data, pil.width, pil.height, QImage.Format.Format_RGBA8888)
                except Exception:
                    img = QImage(str(img_path))
            if img.isNull():
                continue
            img = img.scaled(
                THUMB_SIZE, THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_ready.emit(img, str(img_path), img_path.name, is_processed)
            loaded += 1
            self.progress.emit(loaded, total)

        self.finished_loading.emit(loaded)

    def _generate_thumb(self, img_path: Path, thumb_path: Path):
        try:
            pil = Image.open(img_path)
            pil = ImageOps.exif_transpose(pil).convert("RGB")
            pil.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            pil.save(thumb_path, "JPEG", quality=85)
        except Exception:
            pass


class LibraryLoaderThread(QThread):
    image_ready       = pyqtSignal(QImage, str, str)
    progress          = pyqtSignal(int, int)  # current, total (generation phase)
    thumbnails_needed = pyqtSignal(int)        # count before generation starts
    finished_loading  = pyqtSignal(int)

    def __init__(self, output_dir: Path, sort_idx: int = 0):
        super().__init__()
        self._output_dir = output_dir
        _, self._sort_key, self._sort_reverse = SORT_OPTIONS[sort_idx]
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            images = sorted(
                (p for p in self._output_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS),
                key=self._sort_key,
                reverse=self._sort_reverse,
            )
        except OSError:
            self.finished_loading.emit(0)
            return

        thumb_dir = self._output_dir / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)

        # Phase 1: generate missing thumbnails
        missing = [
            (p, thumb_dir / (p.stem + ".jpg"))
            for p in images
            if not (thumb_dir / (p.stem + ".jpg")).exists()
        ]
        if missing:
            self.thumbnails_needed.emit(len(missing))
            for i, (img_path, thumb_path) in enumerate(missing, 1):
                if self._cancelled:
                    return
                self._generate_thumb(img_path, thumb_path)
                self.progress.emit(i, len(missing))

        # Phase 2: load all from cache
        loaded = 0
        for img_path in images:
            if self._cancelled:
                return
            thumb_path = thumb_dir / (img_path.stem + ".jpg")
            img = QImage(str(thumb_path))
            if img.isNull():
                # fallback: decode source image directly
                try:
                    pil = Image.open(img_path)
                    pil = ImageOps.exif_transpose(pil).convert("RGBA")
                    data = pil.tobytes("raw", "RGBA")
                    img = QImage(data, pil.width, pil.height, QImage.Format.Format_RGBA8888)
                except Exception:
                    img = QImage(str(img_path))
            if img.isNull():
                continue
            img = img.scaled(
                THUMB_SIZE, THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_ready.emit(img, str(img_path), img_path.name)
            loaded += 1

        self.finished_loading.emit(loaded)

    def _generate_thumb(self, img_path: Path, thumb_path: Path):
        try:
            pil = Image.open(img_path)
            pil = ImageOps.exif_transpose(pil).convert("RGB")
            pil.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            pil.save(thumb_path, "JPEG", quality=85)
        except Exception:
            pass


# ------------------------------------------------------------------ #
# Full-size image viewer dialog
# ------------------------------------------------------------------ #

class ImageViewerDialog(QDialog):
    _SLIDE_MS = 4000

    def __init__(self, paths: list[str], index: int = 0, parent=None):
        super().__init__(parent)
        self._paths = paths
        self._index = index
        self._orig_pix: QPixmap | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self._SLIDE_MS)
        self._timer.timeout.connect(self._slideshow_tick)
        self.setWindowTitle("Image Viewer")
        self.setMinimumSize(960, 720)
        self.resize(1100, 800)
        self._build_ui()
        self._load_current()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title_lbl = QLabel()
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setObjectName("subtitle")
        layout.addWidget(self._title_lbl)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_lbl.setMinimumSize(200, 200)
        layout.addWidget(self._img_lbl, stretch=1)

        _BTN_H = 42

        nav_row = QHBoxLayout()
        self._prev_btn = QPushButton("←  Prev")
        self._prev_btn.setMinimumWidth(130)
        self._prev_btn.setFixedHeight(_BTN_H)
        self._prev_btn.clicked.connect(self._prev)

        self._next_btn = QPushButton("Next  →")
        self._next_btn.setMinimumWidth(130)
        self._next_btn.setFixedHeight(_BTN_H)
        self._next_btn.clicked.connect(self._next)

        self._play_btn = QPushButton("▶  Slideshow")
        self._play_btn.setMinimumWidth(160)
        self._play_btn.setFixedHeight(_BTN_H)
        self._play_btn.setToolTip("Auto-advance every 4s full-screen  (Space = skip ahead,  Esc = stop)")
        self._play_btn.clicked.connect(self._toggle_slideshow)

        self._fs_btn = QPushButton("⛶  Full Screen")
        self._fs_btn.setMinimumWidth(170)
        self._fs_btn.setFixedHeight(_BTN_H)
        self._fs_btn.clicked.connect(self._toggle_fullscreen)

        close_btn = QPushButton("✕  Close")
        close_btn.setObjectName("cancel_btn")
        close_btn.setMinimumWidth(110)
        close_btn.setFixedHeight(_BTN_H)
        close_btn.clicked.connect(self.accept)

        nav_row.addWidget(self._prev_btn)
        nav_row.addWidget(self._next_btn)
        nav_row.addStretch()
        nav_row.addWidget(self._play_btn)
        nav_row.addSpacing(8)
        nav_row.addWidget(self._fs_btn)
        nav_row.addStretch()
        nav_row.addWidget(close_btn)
        layout.addLayout(nav_row)

    def _load_current(self):
        path = self._paths[self._index]
        name = Path(path).name
        self._title_lbl.setText(f"{name}  ({self._index + 1} / {len(self._paths)})")
        self.setWindowTitle(f"Image Viewer — {name}")
        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(self._paths) - 1)
        self._orig_pix = QPixmap(path)
        self._update_display()

    def _update_display(self):
        if self._orig_pix and not self._orig_pix.isNull():
            scaled = self._orig_pix.scaled(
                self._img_lbl.width(),
                self._img_lbl.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def _prev(self):
        if self._index > 0:
            self._index -= 1
            self._load_current()

    def _next(self):
        if self._index < len(self._paths) - 1:
            self._index += 1
            self._load_current()

    # ------------------------------------------------------------------ #
    # Full screen
    # ------------------------------------------------------------------ #

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self._fs_btn.setText("⛶  Full Screen")
        else:
            self.showFullScreen()
            self._fs_btn.setText("↙  Exit Full Screen")

    # ------------------------------------------------------------------ #
    # Slideshow
    # ------------------------------------------------------------------ #

    def _toggle_slideshow(self):
        if self._timer.isActive():
            self._stop_slideshow()
        else:
            self._start_slideshow()

    def _start_slideshow(self):
        if not self.isFullScreen():
            self.showFullScreen()
            self._fs_btn.setText("↙  Exit Full Screen")
        self._play_btn.setText("⏹  Stop")
        self._timer.start()

    def _stop_slideshow(self):
        self._timer.stop()
        self._play_btn.setText("▶  Slideshow")

    def _slideshow_tick(self):
        if self._index < len(self._paths) - 1:
            self._next()
        else:
            self._timer.stop()
            self._show_end_slide()
            QTimer.singleShot(3000, self._stop_slideshow)

    def _show_end_slide(self):
        self._title_lbl.setText("End of Slideshow")
        w = max(self._img_lbl.width(), 400)
        h = max(self._img_lbl.height(), 300)
        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.black)
        painter = QPainter(pix)
        painter.setPen(QColor(200, 200, 200))
        f = QFont("Arial", 36, QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "✓   End of Slideshow")
        painter.end()
        self._img_lbl.setPixmap(pix)

    # ------------------------------------------------------------------ #
    # Keyboard
    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._prev()
        elif key == Qt.Key.Key_Right:
            self._next()
        elif key == Qt.Key.Key_Space:
            if self._timer.isActive():
                # Skip ahead immediately and reset the 4s countdown
                self._timer.stop()
                if self._index < len(self._paths) - 1:
                    self._next()
                    self._timer.start()
                else:
                    self._show_end_slide()
                    QTimer.singleShot(3000, self._stop_slideshow)
        elif key == Qt.Key.Key_Escape:
            if self._timer.isActive():
                self._stop_slideshow()
            elif self.isFullScreen():
                self.showNormal()
                self._fs_btn.setText("⛶  Full Screen")
            else:
                self.accept()
        elif key == Qt.Key.Key_Return:
            self.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# ------------------------------------------------------------------ #
# Thumbnail grid
# ------------------------------------------------------------------ #

def _paint_done_badge(painter: QPainter):
    """The green check in a thumbnail's top-right corner (image already processed)."""
    badge = 26
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(30, 190, 60, 230))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(THUMB_SIZE - badge - 3, 3, badge, badge)
    painter.setPen(QColor(255, 255, 255))
    painter.setFont(QFont("Arial", 13, QFont.Weight.Bold))
    painter.drawText(THUMB_SIZE - badge - 3, 3, badge, badge, Qt.AlignmentFlag.AlignCenter, "✓")


class ThumbnailGrid(QListWidget):
    def __init__(self, parent=None, selection_mode=QAbstractItemView.SelectionMode.NoSelection):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self.setGridSize(QSize(THUMB_SIZE + 12, THUMB_SIZE + 28))
        self.setSpacing(4)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSelectionMode(selection_mode)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setStyleSheet(
            f"QListWidget {{ background-color: {COLORS['bg_medium']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 3px; }}"
            f"QListWidget::item {{ border: 1px solid transparent; border-radius: 3px; }}"
            f"QListWidget::item:selected {{ border: 2px solid {COLORS['accent']}; "
            f"background-color: rgba(94,75,219,0.25); }}"
        )

    def add_item(self, img: QImage, key: str, label: str, is_processed: bool = False,
                 is_pinned: bool = False):
        pix    = QPixmap.fromImage(img)
        canvas = QPixmap(THUMB_SIZE, THUMB_SIZE)
        canvas.fill(Qt.GlobalColor.black)
        painter = QPainter(canvas)
        painter.drawPixmap((THUMB_SIZE - pix.width()) // 2,
                           (THUMB_SIZE - pix.height()) // 2, pix)
        if is_pinned:
            badge = 24
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(230, 150, 20, 235))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(3, 3, badge, badge)
            painter.setPen(QColor(255, 255, 255))
            f = QFont("Arial", 12, QFont.Weight.Bold)
            painter.setFont(f)
            painter.drawText(3, 3, badge, badge, Qt.AlignmentFlag.AlignCenter, "📌")
        if is_processed:
            _paint_done_badge(painter)
        painter.end()
        item = QListWidgetItem(QIcon(canvas), label)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.addItem(item)

    def all_paths(self) -> list[Path]:
        return [Path(self.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.count())]

    def selected_keys(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.selectedItems()]

    def mark_processed(self, stem: str):
        """Put the green check on a thumbnail already in the grid."""
        for i in range(self.count()):
            item = self.item(i)
            key = item.data(Qt.ItemDataRole.UserRole) if item else None
            if key and Path(key).stem == stem:
                canvas = item.icon().pixmap(THUMB_SIZE, THUMB_SIZE).copy()
                painter = QPainter(canvas)
                _paint_done_badge(painter)
                painter.end()
                item.setIcon(QIcon(canvas))

    def remove_items_by_stems(self, stems: set[str]):
        for i in range(self.count() - 1, -1, -1):
            item = self.item(i)
            key = item.data(Qt.ItemDataRole.UserRole) if item else None
            if key and Path(key).stem in stems:
                self.takeItem(i)


# ------------------------------------------------------------------ #
# Main window
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager, base_dir: Path, version: str = ""):
        super().__init__()
        self._config   = config
        self._base_dir = base_dir
        self._version  = version
        self._prompts: list[PromptEntry] = []
        self._pinned: dict[str, str] = {}  # image stem -> pinned prompt text
        self._worker: BatchStyleWorker | None = None
        self._loader: ImageLoaderThread | None = None
        self._lib_loader: LibraryLoaderThread | None = None
        self._last_lib_dir: str = ""
        self._reroll_worker: BatchStyleWorker | None = None
        self._processed_count: int = 0
        self._auto_mode = False
        self._auto_stop_requested = False
        self._auto_current_batch: list[Path] = []
        self._last_auto_prompt_idx: int = -1
        self._auto_prompt_cursor: int = 0  # cursor for sequential/evens_odds auto mode
        # Model check & sync: the (workflow, server) pair whose models were last
        # confirmed on the pod, so Auto Run checks once, not once per batch.
        self._models_ok_key: tuple | None = None
        self._pending = None  # (proceed, on_drop, key) while a model check/sync runs
        self._model_check: model_sync.ModelCheckWorker | None = None
        self._transfer: model_sync.TransferWorker | None = None
        self._transfer_dlg: QProgressDialog | None = None
        self._xfer_mark: tuple[str, float, int] = ("", 0.0, 0)   # (label, t0, bytes) for the rate readout
        self._pod_only_declined: set[str] = set()                # "run on the pod" answers, this session

        self._build_ui()
        self._restore_view_settings()
        self._load_initial_state()
        # After the window is actually on screen, so the pod prompt has a
        # parent to centre on rather than appearing behind it.
        QTimer.singleShot(200, self._pod.check_on_launch)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _restore_view_settings(self):
        """Bring back what was set last time: prompt order, Auto Run batch size,
        and where the window was. Saved as they change (and the window on close)."""
        idx = self._prompt_order_combo.findData(self._config.get("prompt_order", "evens_odds"))
        self._prompt_order_combo.setCurrentIndex(max(0, idx))
        self._auto_size_spin.setValue(int(self._config.get("auto_batch_size", 4) or 4))
        self._prompt_order_combo.currentIndexChanged.connect(self._on_view_setting_changed)
        self._auto_size_spin.valueChanged.connect(self._on_view_setting_changed)
        geo = self._config.get("window_geometry", "")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))

    def _on_view_setting_changed(self, *_):
        self._config.set("prompt_order", self._prompt_order_combo.currentData())
        self._config.set("auto_batch_size", self._auto_size_spin.value())
        self._config.save()

    def _build_ui(self):
        title = f"ComfyUI Style Randomizer v{self._version}" if self._version else "ComfyUI Style Randomizer"
        self.setWindowTitle(title)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Header with view toggle buttons
        hdr_row = QHBoxLayout()
        self._randomizer_btn = QPushButton("🎲  Randomizer")
        self._randomizer_btn.setCheckable(True)
        self._randomizer_btn.setChecked(True)
        self._randomizer_btn.setFixedHeight(32)
        self._randomizer_btn.setStyleSheet(_MODE_BTN_STYLE)
        self._randomizer_btn.clicked.connect(lambda: self._switch_view(0))

        self._library_btn = QPushButton("🖼  Library")
        self._library_btn.setCheckable(True)
        self._library_btn.setChecked(False)
        self._library_btn.setFixedHeight(32)
        self._library_btn.setStyleSheet(_MODE_BTN_STYLE)
        self._library_btn.clicked.connect(lambda: self._switch_view(1))

        hdr_row.addWidget(self._randomizer_btn)
        hdr_row.addSpacing(4)
        hdr_row.addWidget(self._library_btn)
        hdr_row.addStretch()

        hdr_lbl = QLabel("ComfyUI Style Randomizer")
        hdr_lbl.setObjectName("header")
        hdr_row.addWidget(hdr_lbl)
        hdr_row.addStretch()

        self._mode_lbl = QLabel("● Local")
        self._mode_lbl.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
        hdr_row.addWidget(self._mode_lbl)

        # RunPod pod control (copied from ComfyUI Video Creator): spend readout
        # + Start/Stop Pod button. It owns everything pod-related; the window
        # only answers "is a run going right now?".
        self._pod = PodControl(self._config, self._generation_running, self)
        self._pod.server_changed.connect(self._on_server_changed)
        self._pod.log.connect(self._append_log)
        hdr_row.addSpacing(8)
        hdr_row.addWidget(self._pod)
        hdr_row.addSpacing(8)
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setObjectName("small_btn")
        settings_btn.setFixedWidth(100)
        settings_btn.clicked.connect(self._open_settings)
        hdr_row.addWidget(settings_btn)
        root.addLayout(hdr_row)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_main_page())
        self._stack.addWidget(self._build_library_page())
        root.addWidget(self._stack, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._update_status()

    def _build_main_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # Input folder row
        input_row = QHBoxLayout()
        input_lbl = QLabel("Input Folder:")
        input_lbl.setFixedWidth(120)
        input_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._input_edit = QLineEdit()
        self._input_edit.setText(self._config.get("input_dir", ""))
        self._input_edit.setPlaceholderText("Folder containing source images…")
        self._input_edit.editingFinished.connect(self._on_input_edited)
        input_browse = QPushButton("Browse")
        input_browse.setObjectName("small_btn")
        input_browse.setFixedWidth(70)
        input_browse.clicked.connect(self._browse_input)
        self._img_count_lbl = QLabel("Images: 0")
        self._img_count_lbl.setObjectName("subtitle")
        self._show_all_chk = QCheckBox("Show all")
        self._show_all_chk.setToolTip("Include already-processed images (shown with ✓ badge)")
        self._show_all_chk.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._show_all_chk.setChecked(False)
        self._show_all_chk.stateChanged.connect(self._on_show_all_changed)
        input_row.addWidget(input_lbl)
        input_row.addWidget(self._input_edit, stretch=1)
        input_row.addWidget(input_browse)
        input_row.addSpacing(10)
        input_row.addWidget(self._img_count_lbl)
        input_row.addSpacing(10)
        input_row.addWidget(self._show_all_chk)
        layout.addLayout(input_row)

        # Main character row: one fixed photo used as the workflow's second image
        main_row = QHBoxLayout()
        self._main_chk = QCheckBox("Main character:")
        self._main_chk.setFixedWidth(120)
        self._main_chk.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._main_chk.setToolTip(
            "Use one fixed photo (e.g. you) as the second reference image on every run,\n"
            "while the images in the Input Folder rotate through the first.")
        self._main_chk.setChecked(bool(self._config.get("main_character_enabled", False)))
        self._main_chk.stateChanged.connect(self._on_main_character_changed)
        self._main_edit = QLineEdit()
        self._main_edit.setText(self._config.get("main_character_path", ""))
        self._main_edit.setPlaceholderText("Photo of the person who stays the same in every image…")
        self._main_edit.editingFinished.connect(self._on_main_character_changed)
        main_browse = QPushButton("Browse")
        main_browse.setObjectName("small_btn")
        main_browse.setFixedWidth(70)
        main_browse.clicked.connect(self._browse_main_character)
        self._main_mode_combo = QComboBox()
        self._main_mode_combo.addItem("Stitched, main on left", "stitch_left")
        self._main_mode_combo.addItem("Stitched, main on right", "stitch_right")
        self._main_mode_combo.addItem("Separate 2nd reference", "reference")
        self._main_mode_combo.setToolTip(
            "How the main character reaches the workflow:\n"
            "• Stitched - joined side by side with each folder image into ONE image\n"
            "  (for one-image workflows such as Flux2 Dev).\n"
            "• Separate 2nd reference - its own image in the workflow's second\n"
            "  Load Image node (needs a workflow with two, such as Qwen 2.1).")
        idx = self._main_mode_combo.findData(self._config.get("main_character_mode", "stitch_left"))
        self._main_mode_combo.setCurrentIndex(max(0, idx))
        self._main_mode_combo.currentIndexChanged.connect(self._on_main_character_changed)
        self._main_mode_combo.setFixedWidth(170)
        self._main_thumb = QLabel()
        self._main_thumb.setFixedSize(36, 36)
        self._main_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_row.addWidget(self._main_chk)
        main_row.addWidget(self._main_edit, stretch=1)
        main_row.addWidget(main_browse)
        main_row.addSpacing(10)
        main_row.addWidget(self._main_mode_combo)
        main_row.addSpacing(10)
        main_row.addWidget(self._main_thumb)
        layout.addLayout(main_row)
        self._refresh_main_thumb()

        # Splitter: thumbnails | prompts+log
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_w = QWidget()
        left_v = QVBoxLayout(left_w)
        left_v.setContentsMargins(0, 0, 0, 0)
        self._thumb_grid = ThumbnailGrid()
        self._thumb_grid.itemDoubleClicked.connect(self._on_thumb_double_clicked)
        self._thumb_grid.setToolTip("Double-click an image to pin a specific style to it")
        left_v.addWidget(self._thumb_grid)
        splitter.addWidget(left_w)

        right_w = QWidget()
        right_v = QVBoxLayout(right_w)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(6)

        prompt_group = QGroupBox("Style Prompts")
        pg_v = QVBoxLayout(prompt_group)
        prompt_hdr = QHBoxLayout()
        self._prompt_count_lbl = QLabel("0 prompts loaded")
        self._prompt_count_lbl.setObjectName("subtitle")
        edit_prompts_btn = QPushButton("Edit Prompts")
        edit_prompts_btn.setObjectName("small_btn")
        edit_prompts_btn.setFixedWidth(100)
        edit_prompts_btn.clicked.connect(self._open_prompt_editor)
        prompt_hdr.addWidget(self._prompt_count_lbl)
        prompt_hdr.addStretch()
        prompt_hdr.addWidget(edit_prompts_btn)
        pg_v.addLayout(prompt_hdr)
        self._prompt_list = QListWidget()
        self._prompt_list.setMaximumHeight(190)
        pg_v.addWidget(self._prompt_list)
        right_v.addWidget(prompt_group)

        log_group = QGroupBox("Processing Log")
        lg_v = QVBoxLayout(log_group)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        lg_v.addWidget(self._log_view)
        right_v.addWidget(log_group, stretch=1)

        splitter.addWidget(right_w)
        splitter.setSizes([620, 430])
        layout.addWidget(splitter, stretch=1)

        # Bottom — progress + controls
        bottom_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setFormat("%v / %m")
        self._progress.setValue(0)
        # Second, slimmer bar under the file counter: the sampler step of the
        # image being generated right now.
        self._step_bar = QProgressBar()
        self._step_bar.setFixedHeight(16)
        self._step_bar.setStyleSheet(
            "QProgressBar { height: 14px; font-size: 8pt; }"
            f"QProgressBar::chunk {{ background-color: {COLORS['accent']}; border-radius: 2px; }}")
        self._reset_step_bar()
        prog_col = QVBoxLayout()
        prog_col.setSpacing(3)
        prog_col.addWidget(self._progress)
        prog_col.addWidget(self._step_bar)
        bottom_row.addLayout(prog_col, stretch=1)

        shape_lbl = QLabel("Shape:")
        shape_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        bottom_row.addWidget(shape_lbl)
        self._shape_combo = QComboBox()
        self._shape_combo.addItem("Auto (follow image)", "auto")
        self._shape_combo.addItem("Portrait 2:3",        "portrait_2_3")
        self._shape_combo.addItem("Portrait 3:4",        "portrait_3_4")
        self._shape_combo.addItem("Square 1:1",          "square")
        self._shape_combo.addItem("Landscape 4:3",       "landscape_4_3")
        self._shape_combo.addItem("Landscape 3:2",       "landscape_3_2")
        self._shape_combo.setFixedHeight(28)
        self._shape_combo.setFixedWidth(150)
        self._shape_combo.setToolTip(
            "Shape of the generated image.\n"
            "Auto: the workflow sizes it from the input image (a side-by-side\n"
            "stitched pair therefore comes out wide).\n"
            "Portrait / Square / Landscape: forced, at the workflow's own pixel\n"
            "budget, whatever shape the input image has.")
        idx = self._shape_combo.findData(self._config.get("output_shape", "auto"))
        self._shape_combo.setCurrentIndex(max(0, idx))
        self._shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        bottom_row.addWidget(self._shape_combo)
        bottom_row.addSpacing(8)

        order_lbl = QLabel("Order:")
        order_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        bottom_row.addWidget(order_lbl)
        self._prompt_order_combo = QComboBox()
        self._prompt_order_combo.addItem("Evens → Odds", "evens_odds")
        self._prompt_order_combo.addItem("Random",      "random")
        self._prompt_order_combo.addItem("Sequential",  "sequential")
        self._prompt_order_combo.setFixedHeight(28)
        self._prompt_order_combo.setFixedWidth(130)
        self._prompt_order_combo.setToolTip(
            "Evens → Odds: even-numbered styles first, then odd\n"
            "Random: each image gets a random style\n"
            "Sequential: styles assigned in order (1, 2, 3…)"
        )
        bottom_row.addWidget(self._prompt_order_combo)
        bottom_row.addSpacing(8)

        self._start_btn = QPushButton("Start")
        self._start_btn.setMinimumWidth(100)
        self._start_btn.clicked.connect(lambda: self._start())
        bottom_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("cancel_btn")
        self._cancel_btn.setMinimumWidth(100)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel)
        bottom_row.addWidget(self._cancel_btn)

        layout.addLayout(bottom_row)

        # Auto run row
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
        self._stop_auto_btn.setStyleSheet(f"QPushButton {{ font-size: 9pt; padding: 4px 14px; }}")
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
        layout.addLayout(auto_row)

        return page

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        folder_lbl = QLabel("Output Folder:")
        folder_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._lib_folder_lbl = QLabel("—")
        self._lib_folder_lbl.setStyleSheet(f"color:{COLORS['fg_dim']}; font-size:9pt;")
        self._lib_folder_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._lib_sort_combo = QComboBox()
        self._lib_sort_combo.setFixedHeight(36)
        self._lib_sort_combo.setMinimumWidth(150)
        for label, *_ in SORT_OPTIONS:
            self._lib_sort_combo.addItem(label)
        self._lib_sort_combo.currentIndexChanged.connect(lambda _: self._populate_library(force=True))

        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(lambda: self._populate_library(force=True))

        self._lib_view_btn = QPushButton("👁  View")
        self._lib_view_btn.setFixedHeight(36)
        self._lib_view_btn.setEnabled(False)
        self._lib_view_btn.clicked.connect(self._view_selected)

        self._lib_reroll_btn = QPushButton("🎲  Re-roll")
        self._lib_reroll_btn.setFixedHeight(36)
        self._lib_reroll_btn.setEnabled(False)
        self._lib_reroll_btn.setToolTip("Re-process this image with a new random style (source must still be in the input folder)")
        self._lib_reroll_btn.clicked.connect(self._reroll_selected)

        self._lib_delete_btn = QPushButton("🗑  Delete")
        self._lib_delete_btn.setObjectName("cancel_btn")
        self._lib_delete_btn.setFixedHeight(36)
        self._lib_delete_btn.setEnabled(False)
        self._lib_delete_btn.clicked.connect(self._delete_selected)

        toolbar.addWidget(folder_lbl)
        toolbar.addWidget(self._lib_folder_lbl, stretch=1)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._lib_sort_combo)
        toolbar.addSpacing(4)
        toolbar.addWidget(refresh_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._lib_view_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._lib_reroll_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._lib_delete_btn)
        layout.addLayout(toolbar)

        # Grid
        lib_group = QGroupBox(
            "Output Images — double-click to view  |  Ctrl+click or Shift+click for multi-select"
        )
        lg_v = QVBoxLayout(lib_group)
        lg_v.setContentsMargins(6, 6, 6, 6)
        self._lib_grid = ThumbnailGrid(
            selection_mode=QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._lib_grid.itemDoubleClicked.connect(self._on_lib_double_clicked)
        self._lib_grid.itemSelectionChanged.connect(self._on_lib_selection_changed)
        lg_v.addWidget(self._lib_grid)
        layout.addWidget(lib_group, stretch=1)

        # Progress bar (thumbnail generation)
        self._lib_progress = QProgressBar()
        self._lib_progress.setFixedHeight(6)
        self._lib_progress.setTextVisible(False)
        self._lib_progress.setValue(0)
        self._lib_progress.hide()
        layout.addWidget(self._lib_progress)

        # Status
        self._lib_status_lbl = QLabel("Switch to the Randomizer tab to set an output folder")
        self._lib_status_lbl.setObjectName("subtitle")
        self._lib_status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lib_status_lbl)

        return page

    # ------------------------------------------------------------------ #
    # View switching
    # ------------------------------------------------------------------ #

    def _switch_view(self, index: int):
        self._randomizer_btn.setChecked(index == 0)
        self._library_btn.setChecked(index == 1)
        self._stack.setCurrentIndex(index)
        if index == 1:
            self._populate_library()

    # ------------------------------------------------------------------ #
    # Path handling
    # ------------------------------------------------------------------ #

    def _browse_input(self):
        path = QFileDialog.getExistingDirectory(self, "Select Input Folder", self._input_edit.text())
        if path:
            self._input_edit.setText(path)
            self._on_input_edited()

    def _on_input_edited(self):
        self._config.set("input_dir", self._input_edit.text())
        self._config.save()
        self._reload_images()

    def _on_shape_changed(self, *_):
        self._config.set("output_shape", self._shape_combo.currentData())
        self._config.save()

    def _browse_main_character(self):
        start = self._main_edit.text() or self._config.get("input_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Main Character Image", start,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._main_edit.setText(path)
            self._main_chk.setChecked(True)
            self._on_main_character_changed()

    def _on_main_character_changed(self, *_):
        self._config.set("main_character_enabled", self._main_chk.isChecked())
        self._config.set("main_character_path", self._main_edit.text().strip())
        self._config.set("main_character_mode", self._main_mode_combo.currentData())
        self._config.save()
        self._refresh_main_thumb()

    def _refresh_main_thumb(self):
        path = Path(self._main_edit.text().strip())
        pix = QPixmap(str(path)) if path.is_file() else QPixmap()
        if pix.isNull():
            self._main_thumb.clear()
            self._main_thumb.setStyleSheet(f"border: 1px dashed {COLORS['border']};")
            return
        self._main_thumb.setStyleSheet(f"border: 1px solid {COLORS['border']};")
        self._main_thumb.setPixmap(pix.scaled(
            34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _main_character_problem(self) -> str | None:
        """Why a run cannot start with the main character as set, or None."""
        if not self._config.get("main_character_enabled", False):
            return None
        path = Path(self._config.get("main_character_path", "") or "")
        if not path.is_file():
            return "Main character is ticked but its image was not found. Pick a photo or untick it."
        return None

    # ------------------------------------------------------------------ #
    # Data loading — main tab
    # ------------------------------------------------------------------ #

    def _load_initial_state(self):
        self._reload_images()
        self._reload_prompts()
        self._update_mode_label()
        self._update_status()
        self._update_auto_buttons()

    def _on_show_all_changed(self):
        self._reload_images()
        self._update_auto_buttons()

    def _existing_output_stems(self) -> set:
        output_dir = Path(self._config.get("output_dir", ""))
        if not output_dir.is_dir():
            return set()
        return {p.stem for p in output_dir.iterdir() if p.suffix.lower() in OUTPUT_EXTS}

    def _reload_images(self):
        input_dir = Path(self._config.get("input_dir", ""))
        if not input_dir.is_dir():
            return
        if self._loader:
            self._loader.cancel()
            self._loader.wait()
        self._thumb_grid.clear()
        self._img_count_lbl.setText("Loading…")
        show_all = self._show_all_chk.isChecked()
        processed = self._existing_output_stems()
        self._processed_count = len(processed)
        self._processed_set = set(processed)
        self._loader = ImageLoaderThread(input_dir, processed_stems=processed, show_all=show_all)
        self._loader.image_ready.connect(
            lambda img, key, lbl, is_proc: self._thumb_grid.add_item(
                img, key, lbl, is_proc, Path(key).stem in self._pinned
            )
        )
        self._loader.thumbnails_needed.connect(self._on_img_thumbs_needed)
        self._loader.gen_progress.connect(self._on_img_gen_progress)
        self._loader.progress.connect(self._on_img_load_progress)
        self._loader.finished_loading.connect(self._on_images_loaded)
        self._loader.start()

    def _on_img_thumbs_needed(self, count: int):
        self._progress.setMaximum(count)
        self._progress.setValue(0)
        self._img_count_lbl.setText(f"Generating thumbnails… 0 / {count}")

    def _on_img_gen_progress(self, current: int, total: int):
        self._progress.setValue(current)
        self._img_count_lbl.setText(f"Generating thumbnails… {current} / {total}")

    def _on_img_load_progress(self, current: int, total: int):
        self._progress.setMaximum(total)
        self._progress.setValue(current)
        self._img_count_lbl.setText(f"Loading… {current} / {total}")

    def _on_images_loaded(self, count: int):
        self._progress.setValue(0)
        self._progress.setMaximum(max(count, 1))
        done = self._processed_count
        if done > 0:
            self._img_count_lbl.setText(f"Remaining: {count}  |  Done: {done}")
        else:
            self._img_count_lbl.setText(f"Remaining: {count}")

    def _reload_prompts(self):
        prompts_file = Path(self._config.get("prompts_file", ""))
        if not prompts_file.is_file():
            return
        try:
            self._prompts = load_prompts(prompts_file)
        except Exception:
            self._prompts = []
        self._refresh_prompt_list()

    def _refresh_prompt_list(self):
        self._prompt_list.clear()
        for i, entry in enumerate(self._prompts):
            preview = entry.text.replace("\n", " ")[:90]
            label = f"{i+1}.  {preview}"
            if entry.weight != 1.0:
                label += f"   [{entry.weight:g}x]"
            item = QListWidgetItem(label)
            item.setToolTip(self._prompt_tooltip(entry.text))
            self._prompt_list.addItem(item)
        n = len(self._prompts)
        self._prompt_count_lbl.setText(f"{n} style prompt{'s' if n != 1 else ''} loaded")

    @staticmethod
    def _prompt_tooltip(text: str, width: int = 70) -> str:
        """Full prompt text for the hover tooltip. Qt does not wrap plain-text
        tooltips, so a long prompt would be one line running off the screen:
        wrap it ourselves, keeping the prompt's own line breaks."""
        lines = []
        for para in text.strip().splitlines():
            lines.extend(textwrap.wrap(para, width) or [""])
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Per-image prompt pinning
    # ------------------------------------------------------------------ #

    def _on_thumb_double_clicked(self, item: QListWidgetItem):
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        stem = Path(key).stem
        if not self._prompts:
            self._append_log("No prompts loaded — configure a prompts file before pinning.")
            return
        dlg = PinPromptDialog(Path(key).name, self._prompts, self._pinned.get(stem), self)
        if dlg.exec() and dlg.chosen is not None:
            if dlg.chosen == "":
                self._pinned.pop(stem, None)
            else:
                self._pinned[stem] = dlg.chosen
            self._reload_images()

    # ------------------------------------------------------------------ #
    # Data loading — library tab
    # ------------------------------------------------------------------ #

    def _populate_library(self, force: bool = False):
        output_dir = Path(self._config.get("output_dir", ""))
        self._lib_folder_lbl.setText(str(output_dir) if output_dir != Path("") else "—")

        if not force and str(output_dir) == self._last_lib_dir and self._lib_grid.count() > 0:
            return

        if self._lib_loader and self._lib_loader.isRunning():
            self._lib_loader.cancel()
            self._lib_loader.wait()

        self._last_lib_dir = str(output_dir)
        self._lib_grid.clear()
        self._lib_view_btn.setEnabled(False)
        self._lib_delete_btn.setEnabled(False)

        if not output_dir.is_dir():
            self._lib_status_lbl.setText("Output folder not set or not found — configure it in the Randomizer tab")
            return

        self._lib_status_lbl.setText("Loading…")
        self._lib_progress.hide()
        self._lib_progress.setValue(0)
        sort_idx = self._lib_sort_combo.currentIndex()
        self._lib_loader = LibraryLoaderThread(output_dir, sort_idx)
        self._lib_loader.image_ready.connect(
            lambda img, key, lbl: self._lib_grid.add_item(img, key, lbl)
        )
        self._lib_loader.thumbnails_needed.connect(self._on_lib_thumbs_needed)
        self._lib_loader.progress.connect(self._on_lib_gen_progress)
        self._lib_loader.finished_loading.connect(self._on_lib_loaded)
        self._lib_loader.start()

    def _on_lib_thumbs_needed(self, count: int):
        self._lib_progress.setMaximum(count)
        self._lib_progress.setValue(0)
        self._lib_progress.show()
        self._lib_status_lbl.setText(f"Generating thumbnails… 0 / {count}")

    def _on_lib_gen_progress(self, current: int, total: int):
        self._lib_progress.setValue(current)
        self._lib_status_lbl.setText(f"Generating thumbnails… {current} / {total}")

    def _on_lib_loaded(self, count: int):
        self._lib_progress.hide()
        self._lib_progress.setValue(0)
        if count == 0:
            self._lib_status_lbl.setText("No images in output folder")
        else:
            self._lib_status_lbl.setText(
                f"{count} image{'s' if count != 1 else ''} — double-click to view"
            )

    def _on_lib_selection_changed(self):
        keys = self._lib_grid.selected_keys()
        has_sel = bool(keys)
        self._lib_view_btn.setEnabled(has_sel)
        self._lib_delete_btn.setEnabled(has_sel)
        self._lib_reroll_btn.setEnabled(len(keys) == 1 and self._worker is None)
        total = self._lib_grid.count()
        if has_sel:
            n = len(keys)
            self._lib_status_lbl.setText(f"{n} of {total} selected")
        elif total > 0:
            self._lib_status_lbl.setText(
                f"{total} image{'s' if total != 1 else ''} — double-click to view"
            )

    def _on_lib_double_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            all_paths = [
                self._lib_grid.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._lib_grid.count())
            ]
            idx = all_paths.index(path) if path in all_paths else 0
            dlg = ImageViewerDialog(all_paths, idx, parent=self)
            dlg.exec()

    def _view_selected(self):
        keys = self._lib_grid.selected_keys()
        if not keys:
            return
        existing = [k for k in keys if Path(k).exists()]
        if not existing:
            return
        dlg = ImageViewerDialog(existing, 0, parent=self)
        dlg.exec()

    def _delete_selected(self):
        keys = self._lib_grid.selected_keys()
        if not keys:
            return
        n = len(keys)
        msg = (
            f"Permanently delete:\n{Path(keys[0]).name}?\n\nThis cannot be undone."
            if n == 1 else
            f"Permanently delete {n} images?\n\nThis cannot be undone."
        )
        reply = QMessageBox.question(
            self, "Delete Images", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for key in keys:
            try:
                p = Path(key)
                p.unlink()
                thumb = p.parent / "thumbnails" / (p.stem + ".jpg")
                if thumb.exists():
                    thumb.unlink()
            except OSError as e:
                errors.append(f"{Path(key).name}: {e}")
        if errors:
            QMessageBox.critical(self, "Error", "Some files could not be deleted:\n" + "\n".join(errors))
        for item in self._lib_grid.selectedItems():
            self._lib_grid.takeItem(self._lib_grid.row(item))
        self._lib_delete_btn.setEnabled(False)
        self._lib_view_btn.setEnabled(False)
        count = self._lib_grid.count()
        self._lib_status_lbl.setText(
            f"{count} image{'s' if count != 1 else ''} — double-click to view"
            if count > 0 else "No images in output folder"
        )

    # ------------------------------------------------------------------ #
    # Re-roll
    # ------------------------------------------------------------------ #

    def _last_prompt_index_for(self, image_name: str) -> int | None:
        output_dir = Path(self._config.get("output_dir", ""))
        log_path = output_dir / PROMPT_LOG_NAME
        if not log_path.is_file():
            return None
        last = None
        try:
            with open(log_path, "r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("image") == image_name:
                        last = row.get("prompt_index")
        except OSError:
            return None
        try:
            return int(last)
        except (TypeError, ValueError):
            return None

    def _reroll_selected(self):
        keys = self._lib_grid.selected_keys()
        if len(keys) != 1:
            return
        out_path = Path(keys[0])
        stem = out_path.stem
        input_dir = Path(self._config.get("input_dir", ""))
        source = next(
            (p for ext in IMAGE_EXTS if (p := input_dir / f"{stem}{ext}").is_file()),
            None,
        )
        if source is None:
            QMessageBox.warning(
                self, "Re-roll",
                f"Source image for '{out_path.name}' was not found in the input folder — cannot re-roll."
            )
            return
        if not self._prompts:
            QMessageBox.warning(self, "Re-roll", "No prompts loaded — configure a prompts file in Settings.")
            return

        if self._spend_limit_blocked():
            return

        reply = QMessageBox.question(
            self, "Re-roll",
            f"Re-process {out_path.name} with a new random style?\n\nThis will overwrite the current output.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        prev_idx = self._last_prompt_index_for(out_path.name)
        texts = [e.text for e in self._prompts]
        n = len(texts)
        if n == 1:
            idx = 0
        else:
            available = [i for i in range(n) if (i + 1) != prev_idx]
            weights = [self._prompts[i].weight for i in available]
            idx = random.choices(available, weights=weights, k=1)[0]
        new_prompt = texts[idx]

        reroll_config = self._config.get_all()
        reroll_config["skip_existing"] = False

        self._ensure_models(
            lambda: self._launch_reroll(reroll_config, source, new_prompt, out_path),
            on_drop=self._on_lib_selection_changed,
        )

    def _launch_reroll(self, reroll_config: dict, source: Path, new_prompt: str, out_path: Path):
        self._lib_reroll_btn.setEnabled(False)
        self._lib_delete_btn.setEnabled(False)
        self._lib_view_btn.setEnabled(False)
        self._lib_status_lbl.setText(f"Re-rolling {out_path.name}…")

        self._reroll_worker = BatchStyleWorker(
            config=reroll_config,
            prompts=self._prompts,
            image_paths=[source],
            fixed_prompt=new_prompt,
            prompt_mode="random",
            base_dir=self._base_dir,
        )
        self._reroll_worker.log.connect(self._append_log)
        self._reroll_worker.step.connect(self._on_step)
        self._reroll_worker.all_done.connect(self._on_reroll_done)
        self._reroll_worker.error.connect(self._on_reroll_error)
        self._reroll_worker.finished.connect(self._on_run_thread_finished)
        self._pod.cancel_idle_timer()
        self._reroll_worker.start()

    def _on_reroll_done(self):
        self._append_log("Re-roll complete.")
        self._reroll_worker = None
        self._populate_library(force=True)

    def _on_reroll_error(self, msg: str):
        self._append_log(f"Re-roll ERROR: {msg}")
        QMessageBox.critical(self, "Re-roll Error", msg)
        self._reroll_worker = None
        self._on_lib_selection_changed()

    # ------------------------------------------------------------------ #
    # Dialogs
    # ------------------------------------------------------------------ #

    def _open_prompt_editor(self):
        prompts_file = Path(self._config.get("prompts_file", ""))
        if not prompts_file.is_file():
            self._append_log("No prompts file set — configure it in ⚙ Settings.")
            return
        dlg = PromptEditorDialog(prompts_file, self._config, self)
        if dlg.exec():
            self._reload_prompts()

    def _open_settings(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._reload_prompts()
            self._update_mode_label()
            self._update_status()
            self._reload_images()  # output_dir may have changed; refresh processed stems

    # ------------------------------------------------------------------ #
    # Model check & sync (RunPod) - copied from the Video Creator
    # ------------------------------------------------------------------ #

    def _sync_log(self, msg: str):
        """Model check / sync lines go to the log pane AND logs/<today>.txt,
        so a transfer that misbehaves overnight leaves evidence."""
        self._append_log(msg)
        try:
            append_daily_log(self._base_dir, msg)
        except Exception:  # noqa: BLE001
            pass

    def _ensure_models(self, proceed, on_drop):
        """Run `proceed` once the workflow's model files are confirmed on the
        pod (copied there / back here if they were not). Local mode, the check
        switched off, or an already-confirmed (workflow, server) pair go
        straight through. `on_drop` runs when the user backs out."""
        cfg = self._config.get_all()
        if not (self._config.is_runpod() and model_sync.check_enabled(cfg)):
            proceed()
            return
        if self._model_check is not None or self._transfer is not None:
            return  # already checking - a second click must not stack another
        wf_path = Path(cfg.get("workflow_path", ""))
        key = (str(wf_path), self._config.server_url())
        if key == self._models_ok_key:
            proceed()
            return
        try:
            refs = model_sync.models_in_workflow(json.loads(wf_path.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            self._sync_log(f"Model check: couldn't read {wf_path.name} ({e}) - the run will report it")
            proceed()
            return
        if not refs:
            self._models_ok_key = key
            proceed()
            return
        self._pending = (proceed, on_drop, key)
        self._start_btn.setEnabled(False)
        self._auto_btn.setEnabled(False)
        self._pod.cancel_idle_timer()
        self._sync_log(f"Model check: comparing {len(refs)} model file(s) between the local "
                         "models folder and the pod volume…")
        self._model_check = model_sync.ModelCheckWorker(cfg, list(refs))
        self._model_check.done.connect(self._on_model_plan)
        self._model_check.finished.connect(self._model_check_finished)
        self._model_check.start()

    def _model_check_finished(self):
        self._model_check = None

    def _model_release(self):
        proceed, _drop, key = self._pending
        self._pending = None
        self._models_ok_key = key
        self._start_btn.setEnabled(True)
        self._update_auto_buttons()
        proceed()

    def _model_release_unchecked(self):
        """Run without the models confirmed: do not remember it, so the next
        run asks again."""
        proceed, _drop, _key = self._pending
        self._pending = None
        self._start_btn.setEnabled(True)
        self._update_auto_buttons()
        proceed()

    def _model_drop(self, why: str):
        _proceed, on_drop, _key = self._pending
        self._pending = None
        self._sync_log(f"Run not started - {why}")
        self._start_btn.setEnabled(True)
        self._update_auto_buttons()
        on_drop()

    def _model_check_dropped(self):
        """A batch (possibly an Auto Run) was backed out of before it began."""
        self._auto_mode = False
        self._auto_stop_requested = False
        self._auto_current_batch = []
        self._last_auto_prompt_idx = -1
        self._auto_prompt_cursor = 0
        self._update_auto_buttons()

    def _on_model_plan(self, plan: model_sync.SyncPlan):
        if plan.error:
            ans = QMessageBox.question(
                self, "Couldn't check the pod's models",
                f"The pod volume could not be listed:\n\n{plan.error}\n\n"
                "Start the run anyway? A model the pod lacks will fail on the server.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            self._sync_log(f"Model check failed: {plan.error}")
            if ans == QMessageBox.StandardButton.Yes:
                self._model_release_unchecked()
            else:
                self._model_drop("model check failed (see Settings > Models)")
            return
        for ref, actual in plan.case_mismatch.items():
            self._sync_log(f"Model check: {ref.rel} is spelled {actual} on disk — the Linux pod is case-sensitive")
        for ref, (lsize, rsize) in plan.size_mismatch.items():
            self._sync_log(f"Model check: {ref.rel} differs in size (local {model_sync.fmt_size(lsize)}, pod {model_sync.fmt_size(rsize)}) — not touched")

        # Models the pod has but this PC doesn't. The pod run is fine without
        # them, so say exactly that and offer the download for local use —
        # a 35 GB text encoder must never start pulling down unannounced.
        offered = [j for j in plan.optional_downloads if j.ref.rel not in self._pod_only_declined]
        if offered:
            total = sum(j.size for j in offered)
            names = "\n".join(f"    • {j.ref.kind}: {j.ref.rel}  ({model_sync.fmt_size(j.size)})" for j in offered)
            self._sync_log(f"Model check: {len(offered)} model(s) are on the pod but not on this PC ({model_sync.fmt_size(total)})")
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
                self._sync_log(f"Model check: downloading {len(offered)} pod-only model(s) to this PC first")
            elif box.clickedButton() is pod:
                for j in offered:
                    self._pod_only_declined.add(j.ref.rel)
                self._sync_log("Model check: running on the pod without the local copies (not asked again this session)")
            else:
                self._model_drop("cancelled at the missing-locally prompt")
                return

        if plan.clean and not plan.downloads:
            self._sync_log("Model check: every model file the run needs is on the pod")
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
            self._sync_log("Model check: " + ln.strip())

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
        self._transfer.log.connect(self._sync_log)
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
        self._sync_log("Model sync: every file verified - starting the run")
        self._model_release()

    def _transfer_finished(self):
        self._transfer = None

    # ------------------------------------------------------------------ #
    # Auto mode
    # ------------------------------------------------------------------ #

    def _get_next_auto_batch(self) -> list[Path]:
        count = self._thumb_grid.count()
        if count == 0:
            return []
        batch_size = min(self._auto_size_spin.value(), count)
        return [Path(self._thumb_grid.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(batch_size)]

    def _pick_next_auto_prompt(self) -> str:
        mode  = self._prompt_order_combo.currentData()
        texts = [e.text for e in self._prompts]
        n     = len(texts)

        if mode == "sequential":
            idx = self._auto_prompt_cursor % n
            self._auto_prompt_cursor += 1
            self._last_auto_prompt_idx = idx
            return texts[idx]

        if mode == "evens_odds":
            evens = texts[0::2]
            odds  = texts[1::2]
            seq   = evens + odds
            idx   = self._auto_prompt_cursor % len(seq)
            self._auto_prompt_cursor += 1
            self._last_auto_prompt_idx = idx
            return seq[idx]

        # weighted random — no consecutive repeat
        if n == 1:
            self._last_auto_prompt_idx = 0
        else:
            available = [i for i in range(n) if i != self._last_auto_prompt_idx]
            weights   = [self._prompts[i].weight for i in available]
            self._last_auto_prompt_idx = random.choices(available, weights=weights, k=1)[0]
        return texts[self._last_auto_prompt_idx]

    def _start_auto(self):
        batch = self._get_next_auto_batch()
        if not batch:
            QMessageBox.information(self, "Auto Run", "No images remaining in the grid.")
            return
        self._auto_mode = True
        self._auto_stop_requested = False
        self._auto_current_batch = batch
        self._update_auto_buttons()
        self._start(batch, clear_log=True, fixed_prompt=self._pick_next_auto_prompt())

    def _stop_auto_after_batch(self):
        self._auto_stop_requested = True
        self._stop_auto_btn.setEnabled(False)
        self._append_log("Stopping after current batch…")

    def _update_auto_buttons(self):
        show_all = self._show_all_chk.isChecked()
        self._auto_btn.setEnabled(not self._auto_mode and not show_all)
        self._auto_btn.setToolTip(
            "Disabled: uncheck 'Show all' before using Auto Run"
            if show_all else
            "Automatically process all images N at a time, no prompts between batches"
        )
        self._stop_auto_btn.setEnabled(self._auto_mode and not self._auto_stop_requested)

    # ------------------------------------------------------------------ #
    # Worker control
    # ------------------------------------------------------------------ #

    def _start(self, images: list[Path] | None = None, clear_log: bool = True,
               fixed_prompt: str | None = None):
        if self._spend_limit_blocked():
            return
        if clear_log:
            self._log_view.clear()
        if images is None:
            images = self._thumb_grid.all_paths()
        if not images:
            self._append_log("No images found. Select an input folder.")
            return
        if not self._prompts:
            self._append_log("No prompts loaded. Select a prompts file.")
            return
        if not Path(self._config.get("workflow_path", "")).is_file():
            self._append_log("No workflow JSON selected.")
            return
        if not self._config.get("output_dir", ""):
            self._append_log("No output folder selected.")
            return
        problem = self._main_character_problem()
        if problem:
            self._append_log(problem)
            return

        self._config.save()
        self._ensure_models(
            lambda: self._launch_batch(images, fixed_prompt),
            on_drop=self._model_check_dropped,
        )

    def _launch_batch(self, images: list[Path], fixed_prompt: str | None):
        self._progress.setValue(0)
        self._progress.setMaximum(len(images))
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        pinned = {p.stem: text for p, text in
                  ((p, self._pinned.get(p.stem)) for p in images) if text}

        self._worker = BatchStyleWorker(
            config=self._config.get_all(),
            prompts=self._prompts,
            image_paths=images,
            fixed_prompt=fixed_prompt,
            prompt_mode=self._prompt_order_combo.currentData(),
            pinned=pinned,
            base_dir=self._base_dir,
        )
        self._worker.progress.connect(lambda cur, _: self._progress.setValue(cur))
        self._worker.log.connect(self._append_log)
        self._worker.image_done.connect(self._on_image_done)
        self._worker.step.connect(self._on_step)
        self._worker.all_done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_run_thread_finished)
        self._pod.cancel_idle_timer()
        self._worker.start()

    def _cancel(self):
        if self._auto_mode:
            self._auto_mode = False
            self._auto_stop_requested = False
            self._auto_current_batch = []
            self._last_auto_prompt_idx = -1
            self._auto_prompt_cursor = 0
            self._update_auto_buttons()
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)
        # _on_done will fire from the worker after cancellation and refresh the grid

    def _on_step(self, value: int, maximum: int):
        """Sampler step of the current image: "Step 5 / 8"; (0, 0) = still
        preparing (uploading, loading models, encoding)."""
        if maximum <= 0:
            self._step_bar.setMaximum(1)
            self._step_bar.setValue(0)
            self._step_bar.setFormat("Preparing…")
        else:
            self._step_bar.setMaximum(maximum)
            self._step_bar.setValue(min(value, maximum))
            self._step_bar.setFormat("Step %v / %m")

    def _reset_step_bar(self):
        self._step_bar.setMaximum(1)
        self._step_bar.setValue(0)
        self._step_bar.setFormat("")

    def _on_image_done(self, stem: str, out_path: str):
        """One image has just been saved. Show it now instead of when the whole
        batch ends (or is cancelled): drop it from the grid (or tick it when
        "Show all" is on), refresh the Remaining/Done counts, and put the result
        in the Library."""
        if stem not in self._processed_set:
            self._processed_set.add(stem)
            self._processed_count += 1
        if self._show_all_chk.isChecked():
            self._thumb_grid.mark_processed(stem)
        else:
            self._thumb_grid.remove_items_by_stems({stem})
        self._img_count_lbl.setText(
            f"Remaining: {self._thumb_grid.count()}  |  Done: {self._processed_count}")

        self._last_lib_dir = ""   # opening the Library later reloads and includes this result
        if self._stack.currentIndex() == 1 and not (self._lib_loader and self._lib_loader.isRunning()):
            self._add_library_result(Path(out_path))

    def _add_library_result(self, out_path: Path):
        """Add one fresh result to the Library grid that is already on screen."""
        try:
            thumb_dir = out_path.parent / "thumbnails"
            thumb_dir.mkdir(exist_ok=True)
            thumb = thumb_dir / (out_path.stem + ".jpg")
            pil = ImageOps.exif_transpose(Image.open(out_path)).convert("RGB")
            pil.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            pil.save(thumb, "JPEG", quality=85)
            img = QImage(str(thumb))
        except Exception:
            return
        if img.isNull():
            return
        for i in range(self._lib_grid.count() - 1, -1, -1):      # a re-run overwrote an existing file
            key = self._lib_grid.item(i).data(Qt.ItemDataRole.UserRole)
            if key and Path(key) == out_path:
                self._lib_grid.takeItem(i)
        self._lib_grid.add_item(img, str(out_path), out_path.name)
        if self._lib_sort_combo.currentIndex() == 0:             # "Newest First": it belongs on top
            self._lib_grid.insertItem(0, self._lib_grid.takeItem(self._lib_grid.count() - 1))
        n = self._lib_grid.count()
        self._lib_status_lbl.setText(f"{n} image{'s' if n != 1 else ''} — double-click to view")

    def _on_done(self):
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._last_lib_dir = ""  # force library to reload next time it's opened

        if self._auto_mode:
            # Remove the batch we just finished from the grid
            processed_stems = {p.stem for p in self._auto_current_batch}
            if not self._show_all_chk.isChecked():
                self._thumb_grid.remove_items_by_stems(processed_stems)

            if not self._auto_stop_requested:
                next_batch = self._get_next_auto_batch()
                if next_batch:
                    self._auto_current_batch = next_batch
                    self._start(next_batch, clear_log=False,
                                fixed_prompt=self._pick_next_auto_prompt())
                    return
                # Grid exhausted
                self._append_log("Auto mode complete — no images remaining.")
                self._alert()
            else:
                self._append_log("Auto mode stopped after batch.")
                self._alert()

            self._auto_mode = False
            self._auto_stop_requested = False
            self._auto_current_batch = []
            self._last_auto_prompt_idx = -1
            self._auto_prompt_cursor = 0
            self._update_auto_buttons()
            self._reload_images()
            return

        if self._worker is None or not self._worker.cancelled:
            self._alert()
        self._reload_images()

    def _on_error(self, msg: str):
        self._append_log(f"ERROR: {msg}")
        self._auto_mode = False
        self._auto_stop_requested = False
        self._auto_current_batch = []
        self._last_auto_prompt_idx = -1
        self._update_auto_buttons()
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        # The run stopped itself because ComfyUI cannot make images (missing
        # model, rejected workflow...). Someone may be away from the desk.
        self._alert()
        self._reload_images()
        QMessageBox.critical(
            self, "Run stopped",
            f"The run was stopped - no more images will be attempted.\n\n{msg}")

    # ------------------------------------------------------------------ #
    # UI helpers
    # ------------------------------------------------------------------ #

    def _append_log(self, msg: str):
        now = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{now}] {msg}")

    def _generation_running(self) -> bool:
        """PodControl asks this: a running batch or re-roll means the pod is
        working, so a spend-limit stop waits and the idle countdown never arms."""
        return any(w is not None and w.isRunning()
                   for w in (self._worker, self._reroll_worker, self._transfer))

    def _on_server_changed(self):
        """A pod came up (or went away) and PodControl rewrote mode/runpod_url."""
        self._models_ok_key = None  # a different pod's volume may differ
        self._update_mode_label()
        self._update_status()

    def _on_run_thread_finished(self):
        """A worker thread has really ended (all_done fires while it is still
        winding down). A deferred spend-limit stop lands here, or the idle
        countdown arms - but not between Auto Run batches, where the next
        batch is already running."""
        if self._generation_running() or self._auto_mode:
            return
        self._reset_step_bar()
        self._pod.run_finished()
        self._pod.start_idle_timer()

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
        if self._auto_mode:
            self._auto_mode = False
            self._auto_stop_requested = False
            self._auto_current_batch = []
            self._last_auto_prompt_idx = -1
            self._auto_prompt_cursor = 0
            self._update_auto_buttons()
            self._reload_images()
        QMessageBox.warning(
            self, "Spend limit reached",
            f"This pod has hit the ${limit:.2f} session limit, so no new runs are "
            "being started. It will stop once the current run finishes.\n\n"
            "Raise the limit in Settings > RunPod to keep going.")
        return True

    def _update_mode_label(self):
        mode = self._config.get("mode", "local")
        if mode == "runpod":
            self._mode_lbl.setText("● RunPod")
            self._mode_lbl.setStyleSheet(f"color: {COLORS['warning']}; font-weight: bold;")
        else:
            self._mode_lbl.setText("● Local")
            self._mode_lbl.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")

    def _update_status(self):
        mode = self._config.get("mode", "local")
        url  = (self._config.get("runpod_url", "")
                if mode == "runpod"
                else self._config.get("comfyui_url", "http://127.0.0.1:8000"))
        self._status.showMessage(f"ComfyUI:  {url}")

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
        if self._loader:
            self._loader.cancel()
        if self._lib_loader and self._lib_loader.isRunning():
            self._lib_loader.cancel()
            self._lib_loader.wait(3000)
        if self._worker:
            self._worker.cancel()
        if self._reroll_worker:
            self._reroll_worker.cancel()
        if self._transfer is not None:
            self._transfer.cancel()
            self._transfer.wait(5000)
        if stop_pod:
            self._pod.shutdown()
        self._config.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        self._config.save()
        super().closeEvent(event)
