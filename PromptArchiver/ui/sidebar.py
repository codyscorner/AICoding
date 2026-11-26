"""Sidebar: search, type/rating filters, prompt list, export selection."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from ui.star_rating import StarRating
from ui.theme import tag_chip_style, type_badge_style

RATING_FILTERS = [
    ("All Ratings", "all"),
    ("★★★★★  (5)", 5),
    ("★★★★  4+", 4),
    ("★★★  3+", 3),
    ("★★  2+", 2),
    ("★  1+", 1),
    ("Unrated", 0),
]


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


class PromptListItem(QWidget):
    """One row: checkbox + badge/date, title, preview, stars, tags, file count."""

    exportToggled = pyqtSignal(str, bool)  # folderName, checked

    def __init__(self, prompt: dict, checked: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.prompt = prompt
        # let the QListWidget item's selection/hover color show through
        self.setStyleSheet("background: transparent;")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.toggled.connect(
            lambda on: self.exportToggled.emit(prompt["folderName"], on)
        )
        outer.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(2)

        top = QHBoxLayout()
        badge = QLabel(prompt.get("type", "").upper())
        badge.setStyleSheet(type_badge_style(prompt.get("type", "")))
        top.addWidget(badge)
        date = QLabel(_fmt_date(prompt.get("timestamp", "")))
        date.setObjectName("dimLabel")
        top.addWidget(date)
        top.addStretch()
        body.addLayout(top)

        title_text = prompt.get("title") or _truncate(prompt.get("prompt", ""), 40)
        title = QLabel(_truncate(title_text, 40))
        title.setStyleSheet("font-weight: bold; background: transparent;")
        title.setWordWrap(True)
        body.addWidget(title)

        preview = QLabel(_truncate(prompt.get("prompt", ""), 100))
        preview.setObjectName("dimLabel")
        preview.setWordWrap(True)
        body.addWidget(preview)

        body.addWidget(StarRating(prompt.get("rating", 0), readonly=True, size="small"))

        tags = prompt.get("tags") or []
        if tags:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(3)
            for tag in tags[:6]:
                chip = QLabel(tag)
                chip.setStyleSheet(tag_chip_style())
                tag_row.addWidget(chip)
            tag_row.addStretch()
            body.addLayout(tag_row)

        files = prompt.get("outputFiles") or []
        if files:
            count = QLabel(f"{len(files)} output file{'s' if len(files) != 1 else ''}")
            count.setObjectName("dimLabel")
            body.addWidget(count)

        outer.addLayout(body, stretch=1)


class Sidebar(QWidget):
    """Owns filtering + export-selection state; shows the filtered list."""

    promptSelected = pyqtSignal(dict)
    exportRequested = pyqtSignal(list)   # list of prompt dicts
    settingsRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._prompts: list[dict] = []
        self._filtered: list[dict] = []
        self._export_set: set[str] = set()
        self._selected_folder: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        heading = QLabel("Prompts")
        heading.setStyleSheet("font-size: 12pt; font-weight: bold;")
        header.addWidget(heading)
        header.addStretch()
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(lambda: self.settingsRequested.emit())
        header.addWidget(settings_btn)
        layout.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search prompts...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        layout.addWidget(self.search)

        self.type_filter = QComboBox()
        for label, value in [("All Types", "all"), ("Text", "text"),
                             ("Image", "image"), ("Video", "video")]:
            self.type_filter.addItem(label, value)
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.type_filter)

        self.rating_filter = QComboBox()
        for label, value in RATING_FILTERS:
            self.rating_filter.addItem(label, value)
        self.rating_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.rating_filter)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        layout.addWidget(self.select_all_btn)

        self.export_btn = QPushButton("Export Selected (0)")
        self.export_btn.setObjectName("primaryBtn")
        self.export_btn.clicked.connect(self._export_clicked)
        self.export_btn.hide()
        layout.addWidget(self.export_btn)

        self.list = QListWidget()
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list, stretch=1)

        self.empty_label = QLabel("No prompts found")
        self.empty_label.setObjectName("dimLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

    # ---- public API --------------------------------------------------------

    def set_prompts(self, prompts: list[dict]) -> None:
        self._prompts = prompts
        valid = {p["folderName"] for p in prompts}
        self._export_set &= valid
        self._apply_filters()

    def filtered_count(self) -> int:
        return len(self._filtered)

    def select_folder(self, folder_name: str) -> None:
        """Programmatically re-select a prompt (after reload/update)."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == folder_name:
                self.list.setCurrentItem(item)
                return

    # ---- filtering ---------------------------------------------------------

    def _apply_filters(self) -> None:
        term = self.search.text().strip().lower()
        ptype = self.type_filter.currentData()
        rating = self.rating_filter.currentData()

        def matches(p: dict) -> bool:
            if ptype != "all" and p.get("type") != ptype:
                return False
            r = p.get("rating", 0) or 0
            if rating != "all":
                if rating == 0:
                    if r != 0:
                        return False
                elif r < rating:
                    return False
            if term:
                haystacks = [p.get("prompt", ""), p.get("title", "")]
                haystacks += p.get("tags") or []
                if not any(term in (h or "").lower() for h in haystacks):
                    return False
            return True

        self._filtered = [p for p in self._prompts if matches(p)]
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for prompt in self._filtered:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, prompt["folderName"])
            widget = PromptListItem(
                prompt, checked=prompt["folderName"] in self._export_set
            )
            widget.exportToggled.connect(self._on_export_toggled)
            item.setSizeHint(widget.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)
        self.list.blockSignals(False)

        self.empty_label.setVisible(not self._filtered)
        self.list.setVisible(bool(self._filtered))
        self.select_all_btn.setVisible(bool(self._prompts))
        self._update_export_controls()

        if self._selected_folder:
            self.select_folder(self._selected_folder)

    # ---- selection / export --------------------------------------------------

    def _on_current_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            return
        folder = current.data(Qt.ItemDataRole.UserRole)
        self._selected_folder = folder
        for p in self._filtered:
            if p["folderName"] == folder:
                self.promptSelected.emit(p)
                return

    def _on_export_toggled(self, folder_name: str, checked: bool) -> None:
        if checked:
            self._export_set.add(folder_name)
        else:
            self._export_set.discard(folder_name)
        self._update_export_controls()

    def _toggle_select_all(self) -> None:
        visible = {p["folderName"] for p in self._filtered}
        if visible and visible <= self._export_set:
            self._export_set -= visible
        else:
            self._export_set |= visible
        self._rebuild_list()

    def _update_export_controls(self) -> None:
        n = len(self._export_set)
        self.export_btn.setText(f"Export Selected ({n})")
        self.export_btn.setVisible(n > 0)
        visible = {p["folderName"] for p in self._filtered}
        all_checked = bool(visible) and visible <= self._export_set
        self.select_all_btn.setText("Deselect All" if all_checked else "Select All")

    def _export_clicked(self) -> None:
        selected = [p for p in self._prompts if p["folderName"] in self._export_set]
        if selected:
            self.exportRequested.emit(selected)

    def clear_export_selection(self) -> None:
        self._export_set.clear()
        self._rebuild_list()


def _fmt_date(iso: str) -> str:
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%m/%d/%Y")
    except (ValueError, AttributeError):
        return iso or ""
