"""Thumbnail grid + background loaders + the folder browser panel used by
both tabs (images on tab 1, videos on tab 2).

Thumbnail caches use the same layout as the Chain Automator
(``<folder>/thumbnails/<stem>_<crc>.jpg`` for images, ``<stem>.jpg`` for
videos) so the two apps can share a cache when pointed at the same folder.
"""

from __future__ import annotations

import os
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps
from PyQt6.QtCore import QEvent, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from extend_marks import superseded_clips
from file_ops import delete_paths, thumbnail_caches
from media_tools import IMAGE_EXTS, VIDEO_EXTS, extract_last_frame, extract_thumbnail
from ui.styles import COLORS

THUMB_SIZE = 200
THUMBNAIL_WORKERS = 6   # 16c/32t host — plenty of headroom to spare

SORT_OPTIONS = ["Name A→Z", "Name Z→A", "Newest First", "Oldest First"]

_MISSING = object()   # sentinel: file vanished mid-scan, decrement total


def sort_params(option: str):
    if option == "Name Z→A":
        return (lambda p: p.name.lower()), True
    if option == "Newest First":
        return (lambda p: p.stat().st_mtime), True
    if option == "Oldest First":
        return (lambda p: p.stat().st_mtime), False
    return (lambda p: p.name.lower()), False


# --------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------- #

class ElidedLabel(QLabel):
    """Single-line label that elides its text to the available width and
    shows the full text as a tooltip."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFullText(text)

    def setFullText(self, text: str):
        self._full = text or ""
        self.setToolTip(self._full)
        self._refresh()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        width = max(self.width() - 4, 40)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width))


# --------------------------------------------------------------------- #
# Grid
# --------------------------------------------------------------------- #

class FilterComboBox(QComboBox):
    """Combo that filters as you type, matching anywhere in the entry.

    Qt's stock completer only matches from the start, which is useless for a
    list of workflows where the part you remember ("makeout", "cumshot") sits
    in the middle of `Video_MiniMax_Makeout on Bed/workflow_segment_01.json`.

    `strict` decides what happens to text that matches nothing: the workflow
    picker snaps back to its current entry, the LoRA pickers keep it (a LoRA
    can live on the server without being in the local folder).
    """

    def __init__(self, parent=None, strict: bool = True, placeholder: str = "Type to filter…"):
        super().__init__(parent)
        self._strict = strict
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter(self.model(), self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(20)
        self.setCompleter(completer)
        self.lineEdit().setPlaceholderText(placeholder)
        self.lineEdit().installEventFilter(self)
        # A line edit scrolls to the caret; long workflow paths would show
        # their tail. Keep the start of the name in view instead.
        self.currentIndexChanged.connect(lambda _i: self.lineEdit().setCursorPosition(0))

    def eventFilter(self, obj, event):
        # A click in the box selects everything, so typing replaces the entry
        # instead of landing in the middle of it.
        if obj is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            QTimer.singleShot(0, self.lineEdit().selectAll)
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if not self._strict:
            return
        idx = self.findText(self.currentText().strip(), Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            self.setEditText(self.itemText(self.currentIndex()))

    def wheelEvent(self, event):
        # Sitting in a scrollable panel, this box would otherwise steal the
        # scroll wheel and silently change the selected LoRA/workflow
        # whenever the cursor happens to pass over it — including right
        # after you clicked into it once, since it then keeps focus
        # indefinitely. A combo box should only change by opening its
        # dropdown (click, or Enter/F4) and picking or typing, never by
        # scrolling over it, so the wheel always passes through untouched.
        event.ignore()

    def keyPressEvent(self, event):
        # Same reasoning as wheelEvent: Up/Down shouldn't silently change
        # the value just because this box happens to have focus. Only let
        # them through once a popup — this combo's own, or the filter
        # completer's — is actually open to navigate.
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not _combo_popup_open(self):
            event.ignore()
            return
        super().keyPressEvent(event)


def _combo_popup_open(combo: QComboBox) -> bool:
    if combo.view().isVisible():
        return True
    completer = combo.completer()
    return bool(completer and completer.popup() and completer.popup().isVisible())


class NoScrollComboBox(QComboBox):
    """Plain (non-editable) combo box with the same wheel/arrow-key guard
    as FilterComboBox — see its wheelEvent for why. Use this instead of a
    bare QComboBox anywhere it can sit in a scrollable panel or list."""

    def wheelEvent(self, event):
        event.ignore()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not _combo_popup_open(self):
            event.ignore()
            return
        super().keyPressEvent(event)


PROCESSED_ROLE = Qt.ItemDataRole.UserRole + 1     # True on a tile that already has a finished video
CLIP_ROLE = Qt.ItemDataRole.UserRole + 2          # True on a short extension clip whose complete video exists


class ThumbnailGrid(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self.setGridSize(QSize(THUMB_SIZE + 14, THUMB_SIZE + 30))
        self.setSpacing(4)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWrapping(True)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setStyleSheet(
            f"QListWidget {{ background-color: {COLORS['bg_medium']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 3px;"
            f" font-family: 'Segoe UI'; font-size: 8.5pt; padding-right: 12px; }}"
            f"QListWidget::item {{ border: 2px solid transparent; border-radius: 4px; color: {COLORS['fg_secondary']}; }}"
            f"QListWidget::item:selected {{ background-color: {COLORS['accent_dark']};"
            f" border: 2px solid {COLORS['accent_hover']}; border-radius: 4px; color: white; }}"
            f"QListWidget::item:hover:!selected {{ border: 2px solid {COLORS['border']}; }}"
        )

    def add_item(self, img: QImage, key: str, label: str):
        pix = QPixmap.fromImage(img)
        canvas = QPixmap(THUMB_SIZE, THUMB_SIZE)
        canvas.fill(Qt.GlobalColor.black)
        painter = QPainter(canvas)
        painter.drawPixmap((THUMB_SIZE - pix.width()) // 2, (THUMB_SIZE - pix.height()) // 2, pix)
        painter.end()
        item = QListWidgetItem(QIcon(canvas), label)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setToolTip(key)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.addItem(item)

    def selected_key(self) -> str | None:
        items = self.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def select_key(self, key: str) -> bool:
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                # Asked for by name (Send to Extend, Reuse Settings), so it
                # shows even while finished sources are hidden.
                if item.data(PROCESSED_ROLE) or item.data(CLIP_ROLE):
                    item.setHidden(False)
                    item.setData(PROCESSED_ROLE, False)
                    item.setData(CLIP_ROLE, False)
                self.setCurrentItem(item)
                self.scrollToItem(item)
                return True
        return False


# --------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------- #

class ImageLoaderThread(QThread):
    item_ready = pyqtSignal(QImage, str, str)   # image, absolute path, label
    progress = pyqtSignal(int, int)
    finished_loading = pyqtSignal(int)

    def __init__(self, folder: Path, sort_option: str):
        super().__init__()
        self._folder = folder
        self._sort_key, self._reverse = sort_params(sort_option)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _thumb_name(self, img_path: Path) -> str:
        rel = str(img_path.relative_to(self._folder))
        return f"{img_path.stem}_{zlib.crc32(rel.lower().encode()):08x}.jpg"

    def _process_image(self, img_path: Path, thumb_dir: Path | None):
        """Decode/cache one thumbnail. Runs on a pool worker — must not touch Qt widgets."""
        if not img_path.exists():   # deleted while this scan was running
            return _MISSING
        img = QImage()
        thumb_path = thumb_dir / self._thumb_name(img_path) if thumb_dir else None
        try:
            if (thumb_path and thumb_path.exists()
                    and thumb_path.stat().st_mtime >= img_path.stat().st_mtime):
                img = QImage(str(thumb_path))
        except OSError:
            pass
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
                img = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888).copy()
            except Exception:
                img = QImage(str(img_path))
                if not img.isNull():
                    img = img.scaled(THUMB_SIZE, THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        if img.isNull():
            return None
        rel = img_path.relative_to(self._folder)
        label = str(rel) if rel.parent != Path(".") else img_path.name
        return img, str(img_path), label

    def run(self):
        thumb_dir = self._folder / "thumbnails"
        try:
            thumb_dir.mkdir(exist_ok=True)
        except OSError:
            thumb_dir = None

        try:
            images = sorted(
                (p for p in self._folder.rglob("*")
                 if p.suffix.lower() in IMAGE_EXTS
                 and (thumb_dir is None or thumb_dir not in p.parents)),
                key=self._sort_key, reverse=self._reverse,
            )
        except OSError:
            images = []

        total = len(images)
        loaded = 0
        # executor.map keeps results in input order while decoding/resizing
        # `THUMBNAIL_WORKERS` files at once — emission below still happens
        # only on this thread, in order, so the grid fills the same as before.
        with ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS) as executor:
            for result in executor.map(lambda p: self._process_image(p, thumb_dir), images):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                if result is _MISSING:
                    total -= 1
                    continue
                if result is None:
                    continue
                img, path_str, label = result
                loaded += 1
                self.item_ready.emit(img, path_str, label)
                self.progress.emit(loaded, total)
        self.finished_loading.emit(loaded)


class VideoLoaderThread(QThread):
    item_ready = pyqtSignal(QImage, str, str)
    progress = pyqtSignal(int, int)
    finished_loading = pyqtSignal(int)

    def __init__(self, folder: Path, ffmpeg: str, sort_option: str, last_frame: bool = True,
                 recursive: bool = False):
        super().__init__()
        self._folder = folder
        self._ffmpeg = ffmpeg
        self._sort_key, self._reverse = sort_params(sort_option)
        self._last_frame = last_frame
        self._recursive = recursive
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _process_video(self, vid: Path):
        """Extract/cache one thumbnail frame. Runs on a pool worker — must not touch Qt widgets."""
        if not vid.exists():        # deleted while this scan was running
            return _MISSING
        # Each folder keeps its own cache, so a video's thumbnail is found
        # whether its folder or a parent of it is the one being browsed.
        thumb_dir = vid.parent / "thumbnails"
        try:
            thumb_dir.mkdir(exist_ok=True)
        except OSError:
            pass
        # The Extend tab shows each video's LAST frame — that's the
        # starting point of the extension. Cached under its own name so
        # it never collides with the Chain Automator's first-frame cache.
        thumb = thumb_dir / (vid.stem + ("_last.jpg" if self._last_frame else ".jpg"))
        try:
            stale = thumb.exists() and thumb.stat().st_mtime < vid.stat().st_mtime
        except OSError:
            stale = False
        if not thumb.exists() or stale:
            if self._last_frame:
                try:
                    extract_last_frame(self._ffmpeg, vid, thumb)
                except Exception:
                    extract_thumbnail(self._ffmpeg, vid, thumb)
            else:
                extract_thumbnail(self._ffmpeg, vid, thumb)
        if not vid.exists():
            return _MISSING
        img = QImage(str(thumb)) if thumb.exists() else QImage()
        if img.isNull():
            img = QImage(THUMB_SIZE, THUMB_SIZE, QImage.Format.Format_RGB32)
            img.fill(QColor(COLORS['bg_light']))
        else:
            img = img.scaled(THUMB_SIZE, THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        return img, str(vid), vid.name

    def _find_videos(self) -> list[Path]:
        if not self._recursive:
            return [p for p in self._folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        return [p for p in self._folder.rglob("*")
                if p.suffix.lower() in VIDEO_EXTS and p.is_file()
                and not any(part.lower() == "thumbnails" for part in p.relative_to(self._folder).parts[:-1])]

    def run(self):
        try:
            videos = sorted(self._find_videos(), key=self._sort_key, reverse=self._reverse)
        except OSError:
            videos = []

        total = len(videos)
        loaded = 0
        # Each frame extraction shells out to ffmpeg — running several at
        # once overlaps those external processes instead of waiting on them
        # one at a time. executor.map keeps results in the original sorted
        # order; emission still happens only here, so the grid fills the same.
        with ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS) as executor:
            for result in executor.map(self._process_video, videos):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                if result is _MISSING:
                    total -= 1
                    continue
                img, path_str, label = result
                loaded += 1
                self.item_ready.emit(img, path_str, label)
                self.progress.emit(loaded, total)
        self.finished_loading.emit(loaded)


# --------------------------------------------------------------------- #
# Browser panel
# --------------------------------------------------------------------- #

class MediaBrowser(QWidget):
    """Folder row + sort + thumbnail grid for one media kind."""
    selection_changed = pyqtSignal(object)   # Path | None (the first selected, in grid order)
    selection_paths_changed = pyqtSignal(list)  # every selected Path, in grid order
    activated = pyqtSignal(object)           # Path (double-click)
    folder_changed = pyqtSignal(str)
    sort_changed = pyqtSignal(str)
    deleting = pyqtSignal(list)              # list[Path] about to be deleted (close players!)
    deleted = pyqtSignal(list)               # list[Path] removed from the folder
    loaded = pyqtSignal(int)                 # a refresh() scan finished, n items in the grid
    # Extend tools (extend_tools=True): the main window decides what these do
    hide_requested = pyqtSignal(list)        # list[Path] to hide from the picker
    unhide_requested = pyqtSignal(list)      # list[Path] to bring back
    send_to_library_requested = pyqtSignal(list)
    hide_clips_changed = pyqtSignal(bool)

    def __init__(self, kind: str, folder: str, sort_option: str, ffmpeg_getter, parent=None,
                 multi: bool = False, last_frame: bool = True, title: str | None = None, hint: str = "",
                 show_delete: bool = True, processed_provider=None, recursive: bool = False,
                 extend_tools: bool = False, hide_clips: bool = True):
        super().__init__(parent)
        self.kind = kind                      # "image" | "video"
        # Videos only (images always include subfolders): also list the videos
        # in every subfolder, which is where per-workflow output ends up.
        self._recursive = recursive
        self.missing_text: str | None = None  # status shown when the folder does not exist (yet)
        # Returns the lower-cased file names that already have a finished
        # video in the Library; those tiles are hidden unless "Show all" is
        # ticked. None = no such filter (the Library itself).
        self._processed_provider = processed_provider
        self._processed: set[str] = set()
        # Short extension clips whose complete (stitched) video sits beside them
        self._superseded: set[str] = set()
        self._loading = False
        self._folder = folder
        self._ffmpeg_getter = ffmpeg_getter
        self._last_frame = last_frame
        self._loader: QThread | None = None
        self._retired: list[QThread] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        noun = "Image" if kind == "image" else "Video"
        lbl = QLabel(f"{title or noun} Folder:")
        lbl.setStyleSheet(f"color: {COLORS['accent_hover']}; font-weight: bold;")
        row.addWidget(lbl)
        self._path_edit = QLineEdit(folder)
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText(f"Pick the folder that holds your {noun.lower()}s…")
        row.addWidget(self._path_edit, stretch=1)
        browse = QPushButton("…")
        browse.setObjectName("small_btn")
        browse.setFixedWidth(36)
        browse.setToolTip("Choose folder")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        refresh = QPushButton("↻")
        refresh.setObjectName("small_btn")
        refresh.setFixedWidth(36)
        refresh.setToolTip("Rescan folder")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        open_btn = QPushButton("📂")
        open_btn.setObjectName("small_btn")
        open_btn.setFixedWidth(40)
        open_btn.setToolTip("Open folder in Explorer")
        open_btn.clicked.connect(self._open_folder)
        row.addWidget(open_btn)
        self._del_btn = QPushButton("🗑")
        self._del_btn.setObjectName("small_btn")
        self._del_btn.setFixedWidth(40)
        self._del_btn.setToolTip(
            f"Delete the selected {kind} — goes to the Recycle Bin (Del)")
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self.delete_selected)
        self._del_btn.setVisible(show_delete)     # the Library has its own labelled button
        row.addWidget(self._del_btn)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Sort:"))
        self._sort_combo = NoScrollComboBox()
        self._sort_combo.addItems(SORT_OPTIONS)
        if sort_option in SORT_OPTIONS:
            self._sort_combo.setCurrentText(sort_option)
        self._sort_combo.currentTextChanged.connect(self._on_sort)
        row2.addWidget(self._sort_combo)
        self._show_all = QCheckBox("Show all")
        self._show_all.setToolTip(
            f"Off: {noun.lower()}s that already have a finished video in the Library are hidden.\n"
            "On: every file in the folder is shown. Not remembered between launches.")
        self._show_all.setVisible(processed_provider is not None)
        self._show_all.toggled.connect(lambda _on: self._apply_processed_filter())
        row2.addSpacing(8)
        row2.addWidget(self._show_all)
        row2.addStretch()
        self._status = QLabel("")
        self._status.setObjectName("status_dim")
        row2.addWidget(self._status)
        layout.addLayout(row2)

        if extend_tools:
            # One set of extensions at a time: send the complete videos on to
            # the Library, hide what has been extended, drop the short clips.
            row3 = QHBoxLayout()
            row3.setSpacing(6)
            self._send_btn = QPushButton("📚 Send to Library")
            self._send_btn.setObjectName("secondary_btn")
            self._send_btn.setToolTip("Move the selected video(s) into the Library folder "
                                      "(inside the active workflow's folder)")
            self._send_btn.clicked.connect(lambda: self._emit_selected(self.send_to_library_requested))
            row3.addWidget(self._send_btn)
            self._hide_btn = QPushButton("Hide")
            self._hide_btn.setObjectName("secondary_btn")
            self._hide_btn.setToolTip("Hide the selected video(s) from this list — already extended, "
                                      "or not wanted. They come back with Show all, or Unhide.")
            self._hide_btn.clicked.connect(lambda: self._emit_selected(self.hide_requested))
            row3.addWidget(self._hide_btn)
            self._unhide_btn = QPushButton("Unhide")
            self._unhide_btn.setObjectName("secondary_btn")
            self._unhide_btn.setToolTip("Bring the selected video(s) back (tick Show all to see and select them)")
            self._unhide_btn.clicked.connect(lambda: self._emit_selected(self.unhide_requested))
            row3.addWidget(self._unhide_btn)
            row3.addSpacing(8)
            self._clips_chk = QCheckBox("Hide short clips")
            self._clips_chk.setToolTip(
                "An extension saves the new short clip AND the complete video.\n"
                "On: the short clip is hidden once its complete video is beside it.\n"
                "A clip with no complete video (Append off) is always shown.")
            self._clips_chk.setChecked(hide_clips)
            self._clips_chk.toggled.connect(self._on_hide_clips)
            row3.addWidget(self._clips_chk)
            row3.addStretch()
            layout.addLayout(row3)
            self._extend_btns = (self._send_btn, self._hide_btn, self._unhide_btn)
            for btn in self._extend_btns:
                btn.setEnabled(False)
        else:
            self._clips_chk = None
            self._extend_btns = ()
        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setObjectName("status_dim")
            hint_lbl.setWordWrap(True)
            layout.addWidget(hint_lbl)

        self.grid = ThumbnailGrid()
        if multi:
            self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.itemSelectionChanged.connect(self._on_selection)
        self.grid.itemDoubleClicked.connect(lambda it: self.activated.emit(Path(it.data(Qt.ItemDataRole.UserRole))))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.grid)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(self.delete_selected)
        layout.addWidget(self.grid, stretch=1)

    # ------------------------------------------------------------------ #

    @property
    def folder(self) -> str:
        return self._folder

    def set_folder(self, folder: str, recursive: bool | None = None):
        self._folder = folder or ""
        if recursive is not None:
            self._recursive = recursive
        self._path_edit.setText(self._folder)
        self.refresh()

    def selected_path(self) -> Path | None:
        paths = self.selected_paths()
        return paths[0] if paths else None

    def selected_paths(self) -> list[Path]:
        """In grid order (the sort on screen), not click order — so a
        multi-select queues top-left to bottom-right, predictably."""
        items = sorted((it for it in self.grid.selectedItems() if not it.isHidden()), key=self.grid.row)
        return [Path(it.data(Qt.ItemDataRole.UserRole)) for it in items]

    def _browse(self):
        start = self._folder if self._folder and Path(self._folder).is_dir() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, f"Select {self.kind} folder", start)
        if not folder:
            return
        if Path(folder).name.lower() == "thumbnails":
            folder = str(Path(folder).parent)
        self._folder = folder
        self._path_edit.setText(folder)
        self.folder_changed.emit(folder)
        self.refresh()

    def _open_folder(self):
        if self._folder and Path(self._folder).is_dir():
            os.startfile(self._folder)

    def _on_sort(self, text: str):
        self.sort_changed.emit(text)
        self.refresh()

    def _on_selection(self):
        self._del_btn.setEnabled(bool(self.grid.selectedItems()))
        paths = self.selected_paths()
        for btn in self._extend_btns:
            btn.setEnabled(bool(paths))
        self.selection_changed.emit(paths[0] if paths else None)
        self.selection_paths_changed.emit(paths)
        self._update_status()

    def _grid_menu(self, pos):
        item = self.grid.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.grid.setCurrentItem(item)
        menu = QMenu(self.grid)
        menu.addAction("Open containing folder", self._open_folder)
        if self._extend_btns:
            menu.addSeparator()
            menu.addAction("📚 Send to Library", lambda: self._emit_selected(self.send_to_library_requested))
            menu.addAction("Hide", lambda: self._emit_selected(self.hide_requested))
            menu.addAction("Unhide", lambda: self._emit_selected(self.unhide_requested))
        menu.addSeparator()
        n = len(self.grid.selectedItems())
        menu.addAction(f"Delete {n} file{'s' if n != 1 else ''} (Recycle Bin)", self.delete_selected)
        menu.exec(self.grid.mapToGlobal(pos))

    def delete_selected(self):
        items = self.grid.selectedItems()
        paths = [Path(it.data(Qt.ItemDataRole.UserRole)) for it in items]
        if not paths:
            return
        names = "\n".join(p.name for p in paths[:8]) + ("\n…" if len(paths) > 8 else "")
        ans = QMessageBox.question(
            self, "Delete " + (self.kind if len(paths) == 1 else f"{len(paths)} files"),
            f"Send {'this file' if len(paths) == 1 else f'these {len(paths)} files'} to the "
            f"Recycle Bin?\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.deleting.emit(paths)
        root = Path(self._folder) if self._folder else None
        caches: list[Path] = []
        for p in paths:
            caches += thumbnail_caches(p, root)
        _n, errors, _recycled = delete_paths(paths + caches)
        for it in items:
            if not Path(it.data(Qt.ItemDataRole.UserRole)).exists():
                self.grid.takeItem(self.grid.row(it))
        gone = [p for p in paths if not p.exists()]
        self._on_selection()
        if errors:
            QMessageBox.warning(self, "Delete", "Some files could not be deleted:\n" + "\n".join(errors))
        if gone:
            self.deleted.emit(gone)

    def _release_loader(self):
        """Let go of the running scan before starting another one.

        Disconnecting first is the whole point: a loader that is midway
        through an ffmpeg extraction can't be stopped on the spot, and while
        it lived on it kept emitting into the grid — so a rescan was refilled
        with the previous listing, deleted files included, and the view looked
        stuck. The thread is also parked until it really ends, because a
        QThread collected while still running takes the app down with it."""
        loader, self._loader = self._loader, None
        if loader is None:
            return
        for sig in (loader.item_ready, loader.progress, loader.finished_loading):
            try:
                sig.disconnect()
            except TypeError:
                pass
        if loader.isRunning():
            loader.cancel()
            self._retired.append(loader)
            loader.finished.connect(lambda: self._retire_done(loader))

    def _retire_done(self, loader):
        if loader in self._retired:
            self._retired.remove(loader)

    def refresh(self):
        previous = self.grid.selected_key()
        self._release_loader()
        self.grid.clear()
        self.selection_changed.emit(None)
        folder = Path(self._folder) if self._folder else None
        if not folder or not folder.is_dir():
            self._loading = False
            self._status.setText(self.missing_text if self.missing_text and self._folder
                                 else "No folder selected" if not self._folder else "Folder not found")
            return
        self._loading = True
        self._status.setText("Loading…")
        self._load_processed()
        sort_option = self._sort_combo.currentText()
        if self.kind == "image":
            self._loader = ImageLoaderThread(folder, sort_option)
        else:
            self._loader = VideoLoaderThread(folder, self._ffmpeg_getter(), sort_option,
                                             last_frame=self._last_frame, recursive=self._recursive)
        self._loader.item_ready.connect(self._add_item)
        self._loader.progress.connect(lambda c, t: self._status.setText(f"Loading {c}/{t}…"))
        self._loader.finished_loading.connect(lambda n: self._on_loaded(n, previous))
        self._loader.start()

    def _on_loaded(self, n: int, previous: str | None):
        self._loading = False
        if self._clips_chk is not None:
            self._apply_processed_filter()      # the clip check needs the whole listing
        self._update_status()
        if previous:
            self.grid.select_key(previous)
        self.loaded.emit(n)

    # -- finished-source filter ------------------------------------------ #

    def _load_processed(self):
        try:
            self._processed = set(self._processed_provider()) if self._processed_provider else set()
        except Exception:  # noqa: BLE001 - a bad sidecar must never blank the grid
            self._processed = set()

    def _add_item(self, img, key: str, label: str):
        self.grid.add_item(img, key, label)
        self._mark_processed(self.grid.item(self.grid.count() - 1))

    def _mark_processed(self, item):
        """Hide a tile that already has a finished video, unless Show all is on."""
        key = item.data(Qt.ItemDataRole.UserRole)
        done = Path(key).name.lower() in self._processed
        item.setData(PROCESSED_ROLE, done)
        clip = bool(self._clips_chk is not None and self._clips_chk.isChecked() and key in self._superseded)
        item.setData(CLIP_ROLE, clip)
        hide = (done and not self._show_all.isChecked()) or clip
        if hide and item.isSelected():
            item.setSelected(False)
        item.setHidden(hide)

    def _apply_processed_filter(self):
        if self._clips_chk is not None and not self._loading:
            self._superseded = superseded_clips(
                [self.grid.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.grid.count())])
        for i in range(self.grid.count()):
            self._mark_processed(self.grid.item(i))
        self._on_selection()

    def _emit_selected(self, signal):
        paths = self.selected_paths()
        if paths:
            signal.emit(paths)

    def _on_hide_clips(self, on: bool):
        self.hide_clips_changed.emit(bool(on))
        self._apply_processed_filter()

    def refresh_processed(self):
        """A run just finished: recompute what has a result and re-hide,
        without rescanning the folder."""
        if self._processed_provider is None:
            return
        self._load_processed()
        self._apply_processed_filter()

    def _update_status(self):
        """'181 images · 57 done hidden · 3 selected'."""
        if self._loading:
            return
        noun = "image" if self.kind == "image" else "video"
        items = [self.grid.item(i) for i in range(self.grid.count())]
        clips = sum(1 for it in items if it.data(CLIP_ROLE))
        hidden = sum(1 for it in items if it.data(PROCESSED_ROLE) and it.isHidden() and not it.data(CLIP_ROLE))
        shown = len(items) - hidden - clips
        text = f"{shown} {noun}{'s' if shown != 1 else ''}"
        if hidden:
            text += f" · {hidden} done hidden"
        if clips:
            text += f" · {clips} short clip{'s' if clips != 1 else ''} hidden"
        selected = len(self.selected_paths())
        if selected:
            text += f" · {selected} selected"
        self._status.setText(text)

    def remove_paths(self, paths: list[Path]):
        """Drop rows for files another view just deleted, without a rescan."""
        gone = {str(Path(p)) for p in paths}
        for i in range(self.grid.count() - 1, -1, -1):
            if self.grid.item(i).data(Qt.ItemDataRole.UserRole) in gone:
                self.grid.takeItem(i)
        self._on_selection()

    def shutdown(self):
        self._release_loader()
        for loader in [*self._retired]:
            loader.cancel()
            loader.wait(3000)
