"""Content area: detail card + output-file tabs for the selected prompt."""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QTabBar, QVBoxLayout, QWidget,
)

from archive import ArchiveError, PromptArchive
from ui.media_viewer import MediaViewer
from ui.star_rating import StarRating
from ui.theme import tag_chip_style, type_badge_style

META_FIELDS = [
    ("AI Source", "aiSource"),
    ("Model", "modelName"),
    ("Type", "modelType"),
    ("Base Model", "baseModel"),
]


class ContentArea(QWidget):
    """Shows selected prompt; performs rating/clone/type-change/delete."""

    statusMessage = pyqtSignal(str)
    # emitted after any change; arg = folderName to re-select ("" = clear selection)
    mutated = pyqtSignal(str)
    editRequested = pyqtSignal(dict)

    def __init__(self, archive_getter, parent: QWidget | None = None):
        super().__init__(parent)
        self._get_archive = archive_getter  # callable -> PromptArchive | None
        self._prompt: dict | None = None
        self._viewer: MediaViewer | None = None

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)

        self._empty = QLabel("Select a prompt to view details")
        self._empty.setObjectName("dimLabel")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._outer.addWidget(self._empty)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._outer.addWidget(self._scroll)
        self._scroll.hide()

    # ---- public ------------------------------------------------------------

    def show_prompt(self, prompt: dict | None) -> None:
        self._teardown_viewer()
        self._prompt = prompt
        if prompt is None:
            self._scroll.hide()
            self._scroll.takeWidget()
            self._empty.show()
            return
        self._empty.hide()
        self._scroll.takeWidget()
        self._scroll.setWidget(self._build_detail(prompt))
        self._scroll.show()

    def _teardown_viewer(self) -> None:
        if self._viewer is not None:
            self._viewer.stop_playback()
            self._viewer = None

    # ---- detail construction -------------------------------------------------

    def _build_detail(self, prompt: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        layout.addWidget(self._build_details_card(prompt))
        layout.addWidget(self._build_files_card(prompt), stretch=1)
        return page

    def _build_details_card(self, prompt: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # header: badge + created + actions menu
        header = QHBoxLayout()
        badge = QLabel(prompt.get("type", "").upper())
        badge.setStyleSheet(type_badge_style(prompt.get("type", "")))
        header.addWidget(badge)
        created = QLabel(f"Created: {_fmt_datetime(prompt.get('timestamp', ''))}")
        created.setObjectName("dimLabel")
        header.addWidget(created)
        header.addStretch()
        menu_btn = QPushButton("⋮ Actions")
        menu_btn.clicked.connect(lambda: self._show_actions_menu(menu_btn))
        header.addWidget(menu_btn)
        layout.addLayout(header)

        if prompt.get("title"):
            title = QLabel(prompt["title"])
            title.setObjectName("titleLabel")
            title.setWordWrap(True)
            layout.addWidget(title)

        # rating
        rating_row = QHBoxLayout()
        rating_label = QLabel("Rating:")
        rating_label.setObjectName("sectionLabel")
        rating_row.addWidget(rating_label)
        stars = StarRating(prompt.get("rating", 0), readonly=False, size="medium")
        stars.ratingChanged.connect(self._on_rating_changed)
        rating_row.addWidget(stars)
        rating_row.addStretch()
        layout.addLayout(rating_row)

        # metadata grid (only non-empty fields)
        meta = [(label, prompt.get(key, "")) for label, key in META_FIELDS
                if prompt.get(key)]
        if meta:
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            for col, (label, value) in enumerate(meta):
                cap = QLabel(label)
                cap.setObjectName("dimLabel")
                grid.addWidget(cap, 0, col)
                val = QLabel(value)
                val.setWordWrap(True)
                grid.addWidget(val, 1, col)
            layout.addLayout(grid)

        # tags
        tags = prompt.get("tags") or []
        if tags:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(4)
            for tag in tags:
                chip = QLabel(tag)
                chip.setStyleSheet(tag_chip_style())
                tag_row.addWidget(chip)
            tag_row.addStretch()
            layout.addLayout(tag_row)

        # prompt text + copy
        layout.addLayout(self._text_section(
            "Prompt", prompt.get("prompt", ""), "promptBox"))

        if prompt.get("hasNegativePrompt") and prompt.get("negativePrompt"):
            layout.addLayout(self._text_section(
                "Negative Prompt", prompt["negativePrompt"], "negativePromptBox"))

        return card

    def _text_section(self, heading: str, text: str, object_name: str) -> QVBoxLayout:
        section = QVBoxLayout()
        head = QHBoxLayout()
        label = QLabel(heading)
        label.setObjectName("sectionLabel")
        head.addWidget(label)
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(60)
        copy_btn.clicked.connect(lambda: self._copy_text(text, heading))
        head.addWidget(copy_btn)
        head.addStretch()
        section.addLayout(head)

        box = QPlainTextEdit(text)
        box.setObjectName(object_name)
        box.setReadOnly(True)
        box.setMinimumHeight(70)
        box.setMaximumHeight(180)
        section.addWidget(box)
        return section

    def _copy_text(self, text: str, what: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusMessage.emit(f"{what} copied to clipboard")

    def _build_files_card(self, prompt: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)

        files = prompt.get("outputFiles") or []
        if not files:
            note = QLabel("No output files available")
            note.setObjectName("dimLabel")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            note.setMinimumHeight(60)
            layout.addWidget(note)
            return card

        tabs = QTabBar()
        tabs.setUsesScrollButtons(True)
        for name in files:
            tabs.addTab(name)
        layout.addWidget(tabs)

        holder = QVBoxLayout()
        layout.addLayout(holder, stretch=1)

        def show_tab(index: int) -> None:
            self._teardown_viewer()
            while holder.count():
                item = holder.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            file_path = str(Path(prompt["path"]) / files[index])
            self._viewer = MediaViewer(file_path, prompt.get("type", ""))
            self._viewer.setMinimumHeight(360)
            holder.addWidget(self._viewer)

        tabs.currentChanged.connect(show_tab)
        show_tab(0)
        return card

    # ---- actions ---------------------------------------------------------------

    def _show_actions_menu(self, anchor: QWidget) -> None:
        menu = QMenu(self)
        menu.addAction("Edit Prompt", self._edit)
        menu.addAction("Clone Prompt", self._clone)
        menu.addAction("Change Type", self._change_type)
        menu.addAction("Delete Prompt", self._delete)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _archive(self) -> PromptArchive | None:
        return self._get_archive()

    def _on_rating_changed(self, rating: int) -> None:
        archive = self._archive()
        if archive is None or self._prompt is None:
            return
        try:
            archive.update_rating(self._prompt["path"], rating)
        except OSError as exc:
            self.statusMessage.emit(f"Error updating rating: {exc}")
            return
        self.statusMessage.emit("Rating updated")
        self.mutated.emit(self._prompt["folderName"])

    def _edit(self) -> None:
        if self._prompt is not None:
            self.editRequested.emit(self._prompt)

    def _clone(self) -> None:
        archive = self._archive()
        if archive is None or self._prompt is None:
            return
        try:
            archive.clone_prompt(self._prompt["path"])
        except (OSError, KeyError) as exc:
            self.statusMessage.emit(f"Error cloning prompt: {exc}")
            return
        self.statusMessage.emit("Prompt cloned successfully")
        self.mutated.emit(self._prompt["folderName"])

    def _change_type(self) -> None:
        if self._prompt is None:
            return
        dialog = ChangeTypeDialog(self._prompt.get("type", "text"), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_type = dialog.selected_type()
        archive = self._archive()
        if archive is None or new_type == self._prompt.get("type"):
            return
        try:
            archive.change_type(self._prompt["path"], new_type)
        except (ArchiveError, OSError) as exc:
            QMessageBox.warning(self, "Change Type", str(exc))
            return
        self.statusMessage.emit(
            f"Prompt moved from {self._prompt.get('type')} to {new_type}")
        self.mutated.emit(self._prompt["folderName"])

    def _delete(self) -> None:
        if self._prompt is None:
            return
        if not DeleteConfirmDialog(self._prompt, self).exec():
            return
        archive = self._archive()
        if archive is None:
            return
        archive.delete_prompt(self._prompt["path"])
        self.statusMessage.emit("Prompt deleted")
        self.show_prompt(None)
        self.mutated.emit("")


class ChangeTypeDialog(QDialog):
    def __init__(self, current_type: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Change Prompt Type")
        self._current = current_type

        layout = QVBoxLayout(self)
        note = QLabel("This will move the prompt and all its files to the new type folder.")
        note.setObjectName("infoNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.combo = QComboBox()
        for label, value in [("Text", "text"), ("Image", "image"), ("Video", "video")]:
            self.combo.addItem(label, value)
        self.combo.setCurrentIndex(self.combo.findData(current_type))
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.combo.currentIndexChanged.connect(self._update_ok)
        self._update_ok()

    def _update_ok(self) -> None:
        self._ok.setEnabled(self.combo.currentData() != self._current)

    def selected_type(self) -> str:
        return self.combo.currentData()


class DeleteConfirmDialog(QDialog):
    def __init__(self, prompt: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Delete Prompt")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        warn = QLabel("This action cannot be undone. All files in this prompt "
                      "will be permanently deleted.")
        warn.setObjectName("warnNote")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        layout.addWidget(QLabel("Are you sure you want to delete this prompt?"))

        preview_text = prompt.get("prompt", "")
        if len(preview_text) > 220:
            preview_text = preview_text[:220] + "…"
        preview = QLabel(
            f"{prompt.get('type', '').upper()} Prompt\n{preview_text}")
        preview.setObjectName("infoNote")
        preview.setWordWrap(True)
        layout.addWidget(preview)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        delete = QPushButton("Delete Permanently")
        delete.setObjectName("dangerBtn")
        delete.clicked.connect(self.accept)
        row.addWidget(delete)
        layout.addLayout(row)


def _fmt_datetime(iso: str) -> str:
    try:
        from datetime import datetime
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")).astimezone().strftime("%m/%d/%Y %I:%M %p")
    except (ValueError, AttributeError):
        return iso or ""
