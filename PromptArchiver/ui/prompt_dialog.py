"""Add / Edit prompt dialog (one class, two modes).

Add mode:  stages files via picker (replaces staged list) or drag-drop (appends).
Edit mode: three-way file mode none/add/replace via buttons; drag-drop = add.
The dialog only collects data; the caller performs the archive operations.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from ui.theme import tag_chip_style

FILE_PICKER_FILTER = (
    "All Files (*);;"
    "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp);;"
    "Videos (*.mp4 *.avi *.mov *.wmv *.flv *.webm);;"
    "Text (*.txt *.md *.json)"
)


class DropZone(QFrame):
    """Dashed drop target; emits filesDropped(list[str]) with local paths."""

    filesDropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(64)

        layout = QVBoxLayout(self)
        self.label = QLabel("Drag & drop files here, or click 'Select Files'")
        self.label.setObjectName("dimLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

    def _set_active(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.label.setText("Drop files here…" if active
                           else "Drag & drop files here, or click 'Select Files'")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._set_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self._set_active(False)

    def dropEvent(self, event):
        self._set_active(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile() and Path(u.toLocalFile()).is_file()]
        if paths:
            self.filesDropped.emit(paths)
        event.acceptProposedAction()


class TagEditor(QWidget):
    """Line edit (Enter adds a deduped tag) + removable chips."""

    def __init__(self, tags: list[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._tags: list[str] = list(tags or [])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Add a tag and press Enter")
        self.input.returnPressed.connect(self._add_from_input)
        layout.addWidget(self.input)

        self._chip_row = QHBoxLayout()
        self._chip_row.setSpacing(4)
        layout.addLayout(self._chip_row)
        self._rebuild_chips()

    def tags(self) -> list[str]:
        return list(self._tags)

    def _add_from_input(self) -> None:
        tag = self.input.text().strip()
        if tag and tag not in self._tags:
            self._tags.append(tag)
            self._rebuild_chips()
        self.input.clear()

    def _remove(self, tag: str) -> None:
        self._tags.remove(tag)
        self._rebuild_chips()

    def _rebuild_chips(self) -> None:
        while self._chip_row.count():
            item = self._chip_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for tag in self._tags:
            chip = QPushButton(f"{tag}  ✕")
            chip.setStyleSheet(tag_chip_style())
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, t=tag: self._remove(t))
            self._chip_row.addWidget(chip)
        self._chip_row.addStretch()


class PromptDialog(QDialog):
    """mode='add' or 'edit'. Read results via data(), file_mode(), staged_files()."""

    def __init__(self, mode: str = "add", prompt: dict | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = mode
        self._prompt = prompt or {}
        self._staged: list[str] = []
        self._file_mode = "none"  # edit mode: none | add | replace

        self.setWindowTitle("Add New Prompt" if mode == "add" else "Edit Prompt")
        self.setMinimumSize(680, 640)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if mode == "edit":
            info = QLabel(
                f"Type: {self._prompt.get('type', '')} • "
                f"Created: {self._prompt.get('timestamp', '')}")
            info.setObjectName("dimLabel")
            layout.addWidget(info)

        # title with live counter
        title_row = QHBoxLayout()
        self.title_edit = QLineEdit(self._prompt.get("title", ""))
        self.title_edit.setMaxLength(40)
        self.title_edit.setPlaceholderText("Title (optional)")
        title_row.addWidget(self.title_edit)
        self.title_counter = QLabel("0/40")
        self.title_counter.setObjectName("dimLabel")
        title_row.addWidget(self.title_counter)
        layout.addLayout(title_row)
        self.title_edit.textChanged.connect(
            lambda text: self.title_counter.setText(f"{len(text)}/40"))
        self.title_counter.setText(f"{len(self.title_edit.text())}/40")

        prompt_label = QLabel("Prompt *")
        prompt_label.setObjectName("sectionLabel")
        layout.addWidget(prompt_label)
        self.prompt_edit = QPlainTextEdit(self._prompt.get("prompt", ""))
        self.prompt_edit.setPlaceholderText("Enter your prompt text (required)")
        self.prompt_edit.setMinimumHeight(110)
        layout.addWidget(self.prompt_edit)

        if mode == "add":
            type_row = QHBoxLayout()
            type_row.addWidget(QLabel("Type:"))
            self.type_combo = QComboBox()
            for label, value in [("Text", "text"), ("Image", "image"),
                                 ("Video", "video")]:
                self.type_combo.addItem(label, value)
            type_row.addWidget(self.type_combo, stretch=1)
            layout.addLayout(type_row)

        # model metadata (two rows of two)
        meta_row1 = QHBoxLayout()
        self.ai_source = QLineEdit(self._prompt.get("aiSource", ""))
        self.ai_source.setPlaceholderText("AI Source (e.g. ComfyUI, ChatGPT)")
        meta_row1.addWidget(self.ai_source)
        self.model_name = QLineEdit(self._prompt.get("modelName", ""))
        self.model_name.setPlaceholderText("Model Name (e.g. Flux Dev, GPT-4)")
        meta_row1.addWidget(self.model_name)
        layout.addLayout(meta_row1)

        meta_row2 = QHBoxLayout()
        self.model_type = QLineEdit(self._prompt.get("modelType", ""))
        self.model_type.setPlaceholderText("Model Type (e.g. Image Generation)")
        meta_row2.addWidget(self.model_type)
        self.base_model = QLineEdit(self._prompt.get("baseModel", ""))
        self.base_model.setPlaceholderText("Base Model (e.g. SDXL, WAN 2.1)")
        meta_row2.addWidget(self.base_model)
        layout.addLayout(meta_row2)

        neg_label = QLabel("Negative Prompt")
        neg_label.setObjectName("sectionLabel")
        layout.addWidget(neg_label)
        self.negative_edit = QPlainTextEdit(self._prompt.get("negativePrompt", ""))
        self.negative_edit.setPlaceholderText(
            "Negative prompt (optional, for image/video generation)")
        self.negative_edit.setMaximumHeight(70)
        layout.addWidget(self.negative_edit)

        self.tag_editor = TagEditor(self._prompt.get("tags"))
        layout.addWidget(self.tag_editor)

        # ---- files section ----
        files_label = QLabel("Output Files")
        files_label.setObjectName("sectionLabel")
        layout.addWidget(files_label)

        btn_row = QHBoxLayout()
        if mode == "add":
            select_btn = QPushButton("Select Files")
            select_btn.clicked.connect(self._pick_replace_staged)
            btn_row.addWidget(select_btn)
        else:
            add_btn = QPushButton("Add More Files")
            add_btn.clicked.connect(lambda: self._pick_files("add"))
            btn_row.addWidget(add_btn)
            replace_btn = QPushButton("Replace All Files")
            replace_btn.clicked.connect(lambda: self._pick_files("replace"))
            btn_row.addWidget(replace_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.file_note = QLabel("")
        self.file_note.setObjectName("infoNote")
        self.file_note.setWordWrap(True)
        layout.addWidget(self.file_note)

        self.drop_zone = DropZone()
        self.drop_zone.filesDropped.connect(self._on_drop)
        layout.addWidget(self.drop_zone)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(110)
        layout.addWidget(self.file_list)

        # ---- actions ----
        action_row = QHBoxLayout()
        action_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        action_row.addWidget(cancel)
        self.save_btn = QPushButton("Save Prompt" if mode == "add" else "Save Changes")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.clicked.connect(self.accept)
        action_row.addWidget(self.save_btn)
        layout.addLayout(action_row)

        self.prompt_edit.textChanged.connect(self._update_save_enabled)
        self._update_save_enabled()
        self._refresh_files_ui()

    # ---- results ------------------------------------------------------------

    def data(self) -> dict:
        result = {
            "title": self.title_edit.text().strip(),
            "prompt": self.prompt_edit.toPlainText().strip(),
            "tags": self.tag_editor.tags(),
            "aiSource": self.ai_source.text().strip(),
            "modelName": self.model_name.text().strip(),
            "modelType": self.model_type.text().strip(),
            "baseModel": self.base_model.text().strip(),
            "negativePrompt": self.negative_edit.toPlainText().strip(),
        }
        if self._mode == "add":
            result["type"] = self.type_combo.currentData()
            result["outputFiles"] = list(self._staged)
        return result

    def file_mode(self) -> str:
        return self._file_mode

    def staged_files(self) -> list[str]:
        return list(self._staged)

    # ---- file handling ----------------------------------------------------------

    def _pick_replace_staged(self) -> None:
        """Add mode: picker replaces the staged list (parity with v1.x)."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Files", "", FILE_PICKER_FILTER)
        if paths:
            self._staged = list(paths)
            self._refresh_files_ui()

    def _pick_files(self, mode: str) -> None:
        """Edit mode: picker appends (add) or restages (replace)."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Files", "", FILE_PICKER_FILTER)
        if not paths:
            return
        if self._file_mode != mode:
            self._staged = []
        self._file_mode = mode
        self._staged.extend(p for p in paths if p not in self._staged)
        self._refresh_files_ui()

    def _on_drop(self, paths: list[str]) -> None:
        if self._mode == "edit" and self._file_mode == "none":
            self._file_mode = "add"
        elif self._mode == "edit" and self._file_mode == "replace":
            pass  # keep replace mode; dropped files join the replacement set
        self._staged.extend(p for p in paths if p not in self._staged)
        self._refresh_files_ui()

    def _remove_staged(self, path: str) -> None:
        self._staged.remove(path)
        if self._mode == "edit" and not self._staged:
            self._file_mode = "none"
        self._refresh_files_ui()

    def _refresh_files_ui(self) -> None:
        self.file_list.clear()
        for path in self._staged:
            item = QListWidgetItem()
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)
            name = QLabel(Path(path).name)
            name.setToolTip(path)
            row_layout.addWidget(name, stretch=1)
            remove = QPushButton("✕ Remove")
            remove.clicked.connect(lambda _=False, p=path: self._remove_staged(p))
            row_layout.addWidget(remove)
            item.setSizeHint(row.sizeHint())
            self.file_list.addItem(item)
            self.file_list.setItemWidget(item, row)
        self.file_list.setVisible(bool(self._staged))

        if self._mode == "add":
            self.file_note.setVisible(False)
            return

        current = self._prompt.get("outputFiles") or []
        if self._file_mode == "replace":
            self.file_note.setText(
                "⚠ These files will REPLACE all existing output files when you save.")
            self.file_note.setObjectName("warnNote")
        elif self._file_mode == "add":
            self.file_note.setText("These files will be added to the prompt.")
            self.file_note.setObjectName("infoNote")
        elif current:
            self.file_note.setText(
                "Current files: " + ", ".join(current)
                + "\nDrag & drop or use the buttons above to add/replace files.")
            self.file_note.setObjectName("infoNote")
        else:
            self.file_note.setText("No output files yet — add some above.")
            self.file_note.setObjectName("infoNote")
        # re-polish so the objectName-based style applies
        self.file_note.style().unpolish(self.file_note)
        self.file_note.style().polish(self.file_note)
        self.file_note.setVisible(True)

    def _update_save_enabled(self) -> None:
        self.save_btn.setEnabled(bool(self.prompt_edit.toPlainText().strip()))
