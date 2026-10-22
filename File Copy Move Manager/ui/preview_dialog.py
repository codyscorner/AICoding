"""Preview dialog — the plan for a copy/move, side by side with what is at the destination now.

Each row compares what *will* be at the destination (Pre-Destination: the path after
the folder structure, date folders and duplicate numbering are applied, and the date
the copy will carry) with what *is* there now (Current Destination). The list opens
with the rows where the two do not already match — the files that need copying — and
a checkbox adds the files that need nothing, so you can see exactly what exists.
"""

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QStyledItemDelegate, QTableView, QVBoxLayout,
)

from copy_plan import Action, Plan
from file_operations import format_file_size
from ui.styles import get_stylesheet
from ui.verbs import mode_verbs

# action -> (label, status-dot colour, what it means)
ACTION_INFO = {
    Action.NEW: (
        "New", "#4CAF50",
        "Not at the destination yet — it will be copied there."),
    Action.NUMBERED: (
        "New (numbered)", "#FFB300",
        "A different file already uses this name — one that is at the destination now (shown under "
        "Current Destination) or another file in this same copy — so this one is saved with a "
        "number (name_001, name_002 …)."),
    Action.REFRESH: (
        "Update (newer source)", "#42A5F5",
        "A file with this name is at the destination, but this source has a newer modified date — "
        "it changed, so it will be copied over the older copy."),
    Action.UP_TO_DATE: (
        "Up to date", "#9E9E9E",
        "The destination already has this file (same size and date). Nothing to do."),
    Action.SAME_CONTENT: (
        "Same content", "#78909C",
        "The destination has an identical file (checked byte for byte); only its date differs. Nothing to do."),
    Action.DUPLICATE_SOURCE: (
        "Same as another source", "#9E9E9E",
        "Another source file is the same image and is being copied to this destination — it is copied once."),
    Action.OLDER: (
        "Skipped — file is older", "#A1887F",
        "The destination already has a newer version of this file name (compared by modified date), "
        "so this older one is not copied. Nothing is overwritten."),
    Action.NAME_TAKEN: (
        "Skipped — name in use", "#E57373",
        "A different file already uses this name and nothing may be overwritten (Incremental is off "
        "and “Number duplicate files” is off), so this file is not copied."),
}
_ACTION_ORDER = {action: n for n, action in enumerate(ACTION_INFO)}

HEADERS = [
    "Filename", "Source Size", "Source Path",
    "Pre-Destination Path", "Pre-Destination Date/Time",
    "Current Destination Path", "Current Size", "Current Date/Time",
    "Action",
]
(COL_NAME, COL_SIZE, COL_SOURCE, COL_PRE_PATH, COL_PRE_DT,
 COL_CUR_PATH, COL_CUR_SIZE, COL_CUR_DT, COL_ACTION) = range(9)


def format_dt(timestamp) -> str:
    """Local date/time as shown in the table; '—' when there is no file."""
    if timestamp is None:
        return "—"
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return "?"


def _short_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def _dot_icon(colour: str, size: int = 16) -> QIcon:
    """A small coloured status dot (solid light text + a dot reads better than tinted text)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawEllipse(3, 3, size - 6, size - 6)
    painter.end()
    return QIcon(pixmap)


def summary_lines(plan: Plan, verb: str) -> list:
    """The two breakdown lines shown above the table (empty groups are left out)."""
    c = plan.counts

    def join(pairs):
        return "  ·  ".join(f"{label} {c[a]:,}" for a, label in pairs if c[a])

    todo = join([(Action.NEW, "New"),
                 (Action.NUMBERED, "New, numbered (name in use)"),
                 (Action.REFRESH, "Update (newer source copied over the older copy)")])
    done = join([(Action.UP_TO_DATE, "Up to date"),
                 (Action.SAME_CONTENT, "Same content, date differs"),
                 (Action.DUPLICATE_SOURCE, "Same image as another source"),
                 (Action.OLDER, "Skipped, file is older"),
                 (Action.NAME_TAKEN, "Skipped, name in use")])
    lines = []
    if todo:
        lines.append(f"To {verb.lower()}:  {todo}")
    if done:
        lines.append(f"Nothing to do:  {done}")
    return lines


class _ElideLeftDelegate(QStyledItemDelegate):
    """Destination paths all start with the same root folder; what differs is the end
    (date folder + file name), so when a path is too long cut the *left* side."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideLeft


class PlanTableModel(QAbstractTableModel):
    """Virtual table over PlanItems — only the rows on screen are ever formatted.

    The model sorts itself (Python's sorted() with one key per row). Sorting through a
    QSortFilterProxyModel instead costs ~9 million Python callbacks on 255K rows
    (8–18 s); this takes well under a second.
    """

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._base = items                   # natural (copy) order
        self._items = items                  # what is shown: _base, sorted by the current column
        self._sort = (-1, Qt.SortOrder.AscendingOrder)
        self._icons = {a: _dot_icon(info[1]) for a, info in ACTION_INFO.items()}

    def set_items(self, items) -> None:
        self.beginResetModel()
        self._base = items
        self._items = self._sorted(items)
        self.endResetModel()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder) -> None:
        """Called by the view when a header is clicked (column -1 = back to copy order)."""
        self.beginResetModel()
        self._sort = (column, order)
        self._items = self._sorted(self._base)
        self.endResetModel()

    def _sorted(self, items):
        column, order = self._sort
        if column < 0:
            return items
        return sorted(items, key=lambda item: self._sort_value(item, column),
                      reverse=order == Qt.SortOrder.DescendingOrder)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(item, col)
        if role == Qt.ItemDataRole.UserRole:              # what the column sorts by
            return self._sort_value(item, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(item, col)
        if role == Qt.ItemDataRole.DecorationRole and col == COL_ACTION:
            return self._icons[item.action]
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_SIZE, COL_CUR_SIZE):
            return (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter).value
        return None

    @staticmethod
    def _display(item, col) -> str:
        if col == COL_NAME:
            return os.path.basename(item.source_path)
        if col == COL_SIZE:
            return _short_size(item.size)
        if col == COL_SOURCE:
            return item.source_path
        if col == COL_PRE_PATH:
            return item.pre_dest
        if col == COL_PRE_DT:
            return format_dt(item.src_mtime)
        if col == COL_CUR_PATH:
            return item.cur_dest or "—"
        if col == COL_CUR_SIZE:
            return "—" if item.cur_size is None else _short_size(item.cur_size)
        if col == COL_CUR_DT:
            return format_dt(item.cur_mtime)
        return ACTION_INFO[item.action][0]

    @staticmethod
    def _sort_value(item, col):
        if col == COL_NAME:
            return os.path.basename(item.source_path).lower()
        if col == COL_SIZE:
            return item.size
        if col == COL_SOURCE:
            return item.source_path.lower()
        if col == COL_PRE_PATH:
            return item.pre_dest.lower()
        if col == COL_PRE_DT:
            return item.src_mtime
        if col == COL_CUR_PATH:
            return (item.cur_dest or "").lower()
        if col == COL_CUR_SIZE:
            return -1 if item.cur_size is None else item.cur_size
        if col == COL_CUR_DT:
            return item.cur_mtime or 0.0
        return _ACTION_ORDER[item.action]

    @staticmethod
    def _tooltip(item, col) -> str:
        if col == COL_ACTION:
            text = ACTION_INFO[item.action][2]
            if item.ref and item.action is Action.DUPLICATE_SOURCE:
                text += f"\nCopied on its behalf: {item.ref}"
            elif item.ref and item.action is Action.OLDER:
                text += f"\nThe newer version is: {item.ref}"
            elif item.ref:
                text += f"\nThe plain name is taken by this file in the same copy: {item.ref}"
            return text
        if col == COL_SIZE or col == COL_CUR_SIZE:
            text = f"Source: {item.size:,} bytes"
            if item.cur_size is not None:
                text += f"\nAt the destination now: {item.cur_size:,} bytes"
            return text
        if col == COL_SOURCE or col == COL_NAME:
            return item.source_path
        if col == COL_PRE_PATH:
            return item.pre_dest
        if col == COL_CUR_PATH:
            if not item.cur_dest:
                return "Nothing is there now."
            return f"{item.cur_dest}\n{item.cur_size:,} bytes"
        if col == COL_PRE_DT or col == COL_CUR_DT:
            return "Modified date (not the created date)"
        return ""


class PreviewDialog(QDialog):
    """Shows the plan and lets the user confirm it."""

    def __init__(self, plan: Plan, options: dict, parent=None):
        """
        Args:
            plan:    the Plan the copier will execute if the user presses Proceed
            options: the options dict for the run (only the mode is used here)
        """
        super().__init__(parent)
        self._plan = plan
        mode = options.get('operation_mode', 'copy')
        verb, past = mode_verbs(mode)
        self.setWindowTitle(f"Preview — Files to {verb}")
        self.setMinimumSize(1100, 520)
        width, height = 1750, 780
        screen = QGuiApplication.primaryScreen()
        if screen is not None:                               # always fit the screen (1080p minimum)
            available = screen.availableGeometry()
            width, height = min(width, available.width() - 40), min(height, available.height() - 60)
        self.resize(width, height)
        self.setStyleSheet(get_stylesheet(mode))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(8)

        count = plan.copy_count
        taken = plan.counts[Action.NAME_TAKEN]
        if count:
            heading = (f"{count:,} file{'s' if count != 1 else ''} to {verb.lower()}"
                       f"  ·  {format_file_size(plan.bytes_to_copy)}")
        elif taken:
            # Not "everything is already there": those images are NOT at the destination.
            heading = f"Nothing to {verb.lower()} with the current settings"
        else:
            heading = f"Nothing to {verb.lower()} — everything is already at the destination"
        title = QLabel(heading)
        title.setObjectName("section_label")
        layout.addWidget(title)

        for line in summary_lines(plan, verb):
            layout.addWidget(QLabel(line))

        if taken:
            banner = QLabel(
                f'<span style="color:{ACTION_INFO[Action.NAME_TAKEN][1]};">●</span>&nbsp; '
                f"{taken:,} file{'s were' if taken != 1 else ' was'} skipped because a different file "
                f"already uses the same name and “Number duplicate files” is off. Turn it on to keep "
                f"them as name_001, name_002 … (nothing is ever overwritten)."
            )
            banner.setTextFormat(Qt.TextFormat.RichText)
            banner.setWordWrap(True)
            layout.addWidget(banner)

        self._show_all = QCheckBox(
            f"Also show the {plan.skipped_count:,} file{'s' if plan.skipped_count != 1 else ''} that will not be "
            f"{past.lower()} (already there, same content, skipped)"
        )
        self._show_all.setVisible(plan.skipped_count > 0)
        self._show_all.toggled.connect(self._on_show_all)
        layout.addWidget(self._show_all)

        self._model = PlanTableModel(plan.to_copy)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)   # start in copy order
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setResizeContentsPrecision(100)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)    # drag a border to resize
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(60)
        self._elide_left = _ElideLeftDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_PRE_PATH, self._elide_left)
        self.table.setItemDelegateForColumn(COL_CUR_PATH, self._elide_left)
        self._columns_fitted = False
        layout.addWidget(self.table, stretch=1)

        self._total = QLabel()
        self._total.setObjectName("dim_label")
        layout.addWidget(self._total)
        self._update_total()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel" if count else "Close")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        if count:
            self.proceed_btn = QPushButton(f"Proceed to {verb}")
            self.proceed_btn.clicked.connect(self.accept)
            btn_row.addSpacing(10)
            btn_row.addWidget(self.proceed_btn)
        layout.addLayout(btn_row)

        if not count:
            # Nothing left to copy is exactly when you want to *see* what is there.
            self._show_all.setChecked(True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._columns_fitted:
            self._columns_fitted = True
            QTimer.singleShot(0, self._fit_columns)       # once the layout has its final width

    def _fit_columns(self) -> None:
        """Sensible starting widths: fixed ones for the short columns, the rest shared by the three paths."""
        fixed = {COL_NAME: 170, COL_SIZE: 110, COL_PRE_DT: 190, COL_CUR_SIZE: 115, COL_CUR_DT: 150, COL_ACTION: 200}
        for col, width in fixed.items():
            self.table.setColumnWidth(col, width)
        spare = max(self.table.viewport().width() - sum(fixed.values()), 3 * 200)
        weights = ((COL_SOURCE, 1.0), (COL_PRE_PATH, 1.1), (COL_CUR_PATH, 1.1))
        total = sum(w for _col, w in weights)
        for col, weight in weights:
            self.table.setColumnWidth(col, int(spare * weight / total))

    def _on_show_all(self, checked: bool) -> None:
        self._model.set_items(self._plan.items if checked else self._plan.to_copy)
        self._update_total()

    def _update_total(self) -> None:
        shown = self._model.rowCount()
        total = len(self._plan.items)
        self._total.setText(
            f"Showing {shown:,} of {total:,} matching files"
            + ("" if shown == total else "  ·  tick the box above to show the rest")
        )
