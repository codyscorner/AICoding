"""Queue viewer: what's running now and what's lined up behind it.

ComfyUI runs one prompt at a time, so every tab shares a single queue. Pile a
few runs on while switching between Image → Video and Text → Video and the
count alone ("3 queued") stops being enough to tell whether the thing you're
about to click is already in there — this lists each waiting run with the
frame it starts from, its workflow, source, prompt and settings, and lets rows
be reordered or dropped.
"""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ui.styles import COLORS

COLS = ["#", "Start frame", "Tab", "Workflow", "Source", "Prompt"]
THUMB = QSize(112, 63)      # 16:9, big enough to tell two takes of one prompt apart

# The app stylesheet dresses QListWidget but nothing else uses a tree, so the
# queue view brings its own rows/header rules rather than widening the global
# sheet for one dialog.
TREE_CSS = """
QTreeWidget {{
    background-color: {bg_medium};
    alternate-background-color: {bg_input};
    color: {fg_primary};
    border: 1px solid {border};
    border-radius: 3px;
}}
QTreeWidget::item {{
    padding: 5px 4px;
    border-bottom: 1px solid {bg_dark};
}}
QTreeWidget::item:selected {{
    background-color: {accent};
    color: white;
}}
QHeaderView::section {{
    background-color: {bg_light};
    color: {fg_secondary};
    padding: 5px 6px;
    border: none;
    border-right: 1px solid {border};
    font-weight: bold;
}}
"""
RUNNING_ROW = -1          # Qt.UserRole marker for the "running now" row


class QueueDialog(QDialog):
    remove_requested = pyqtSignal(int)        # index into the pending queue
    move_requested = pyqtSignal(int, int)     # index, delta (-1 up / +1 down)
    next_requested = pyqtSignal(int)          # index to pull to the front of the queue
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run Queue")
        # Non-modal on purpose: leave it open on a second monitor (or beside
        # the window) while setting up the next run.
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet((parent.styleSheet() if parent else "") + TREE_CSS.format(**COLORS))
        # Tall enough for ~5 rows of start-frame thumbnails, short enough to
        # sit on a 1080p screen with the main window behind it.
        self.resize(1240, 640)
        self.setMinimumSize(820, 340)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self._heading = QLabel("")
        self._heading.setObjectName("header")
        lay.addWidget(self._heading)

        hint = QLabel("ComfyUI runs one prompt at a time — everything below waits its turn, "
                      "whichever tab it was started from.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(COLS))
        self._tree.setHeaderLabels(COLS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setIconSize(THUMB)
        # The thumbnail makes every row ~4 text lines tall, so the prompt is
        # wrapped rather than elided after one line — an H3 prompt's opening
        # sentence rarely says which take this is.
        self._tree.setWordWrap(True)
        # One prompt reused across several source images looks identical in
        # every text column, so the starting frame is what actually tells the
        # queued runs apart. Decoded pixmaps are cached (path + mtime) because
        # every queue change rebuilds all the rows.
        self._thumbs: dict[tuple[str, float], QPixmap] = {}
        self._tree.itemSelectionChanged.connect(self._sync_buttons)
        header = self._tree.header()
        for i, mode in enumerate([
            QHeaderView.ResizeMode.ResizeToContents,   # #
            QHeaderView.ResizeMode.Fixed,              # Start frame
            QHeaderView.ResizeMode.ResizeToContents,   # Tab
            QHeaderView.ResizeMode.ResizeToContents,   # Workflow
            QHeaderView.ResizeMode.Interactive,        # Source
            QHeaderView.ResizeMode.Stretch,            # Prompt
        ]):
            header.setSectionResizeMode(i, mode)
        self._tree.setColumnWidth(1, THUMB.width() + 12)
        self._tree.setColumnWidth(4, 280)
        lay.addWidget(self._tree, stretch=1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._up_btn = QPushButton("↑ Move Up")
        self._down_btn = QPushButton("↓ Move Down")
        self._next_btn = QPushButton("⤒ Move to Next")
        self._next_btn.setToolTip("Make this run the next one to start, ahead of everything else waiting")
        self._remove_btn = QPushButton("✕ Remove")
        self._clear_btn = QPushButton("✕ Clear All")
        for b in (self._up_btn, self._down_btn, self._next_btn, self._remove_btn, self._clear_btn):
            b.setObjectName("secondary_btn")
            btns.addWidget(b)
        self._up_btn.clicked.connect(lambda: self._emit_move(-1))
        self._down_btn.clicked.connect(lambda: self._emit_move(1))
        self._next_btn.clicked.connect(self._emit_next)
        self._remove_btn.clicked.connect(self._emit_remove)
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        btns.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary_btn")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

    # ------------------------------------------------------------------ #

    def set_items(self, running, queued: list):
        """running: the RunRequest in progress (or None); queued: the ones
        waiting, in the order they'll run."""
        keep = self._selected_index()
        self._tree.clear()

        if running is not None:
            item = self._make_item("▶", running, "running now")
            font = item.font(0)
            font.setBold(True)
            for col in range(len(COLS)):
                item.setForeground(col, QBrush(QColor(COLORS['warning'])))
                item.setBackground(col, QBrush(QColor(COLORS['bg_light'])))
                item.setFont(col, font)
            item.setData(0, Qt.ItemDataRole.UserRole, RUNNING_ROW)
            self._tree.addTopLevelItem(item)

        for i, req in enumerate(queued):
            item = self._make_item(str(i + 1), req, f"queue position {i + 1}")
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)

        n = len(queued)
        if running is not None:
            self._heading.setText(f"1 running  ·  {n} waiting" if n else "1 running  ·  queue empty")
        else:
            self._heading.setText(f"Nothing running  ·  {n} waiting" if n else "Queue is empty")
        self._clear_btn.setEnabled(n > 0)

        if keep is not None and keep >= 0 and n:
            self._select_index(min(keep, n - 1))
        self._sync_buttons()

    def select_position(self, index: int):
        """Keeps a moved row selected so Move Up/Down can be clicked again."""
        self._select_index(index)

    def _make_item(self, number: str, req, position: str) -> QTreeWidgetItem:
        prompt = " ".join((req.prompt_preview or "").split())
        item = QTreeWidgetItem([
            number,
            "",
            req.tab_label,
            req.workflow_label,
            req.source_name,
            prompt,
        ])
        icon = self._thumb_icon(req.thumb_path)
        if icon is not None:
            item.setIcon(1, icon)
        frame = ("the source image" if req.source_kind == "image"
                 else "nothing — text to video, the prompt is the whole input")
        tip = (f"{position}\n\nWorkflow: {req.workflow_label}\n"
               f"Source: {req.source_path if req.source_path is not None else req.source_name}\n"
               f"Starts from: {frame}\n"
               f"{req.settings_summary}\n\nPrompt:\n{req.prompt_preview or '(none)'}")
        for col in range(len(COLS)):
            item.setToolTip(col, tip)
        return item

    def _thumb_icon(self, path) -> QIcon | None:
        if path is None:
            return None
        try:
            key = (str(path), Path(path).stat().st_mtime)
        except OSError:      # deleted since it was queued
            return None
        pix = self._thumbs.get(key)
        if pix is None:
            pix = QPixmap(str(path))
            if pix.isNull():
                return None
            pix = pix.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            self._thumbs[key] = pix
        return QIcon(pix)

    # ------------------------------------------------------------------ #

    def _selected_index(self) -> int | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def _select_index(self, index: int):
        for row in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole) == index:
                self._tree.setCurrentItem(item)
                return

    def _sync_buttons(self):
        index = self._selected_index()
        # The running row can't be reordered or dropped — cancel it from the
        # tab that owns it, where the log and progress bar are.
        pending = index is not None and index >= 0
        last = self._tree.topLevelItemCount() - (2 if self._has_running() else 1)
        self._remove_btn.setEnabled(pending)
        self._up_btn.setEnabled(pending and index > 0)
        self._down_btn.setEnabled(pending and index < last)
        self._next_btn.setEnabled(pending and index > 0)

    def _has_running(self) -> bool:
        return (self._tree.topLevelItemCount() > 0
                and self._tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == RUNNING_ROW)

    def _emit_remove(self):
        index = self._selected_index()
        if index is not None and index >= 0:
            self.remove_requested.emit(index)

    def _emit_next(self):
        index = self._selected_index()
        if index is not None and index > 0:
            self.next_requested.emit(index)

    def _emit_move(self, delta: int):
        index = self._selected_index()
        if index is not None and index >= 0:
            self.move_requested.emit(index, delta)
