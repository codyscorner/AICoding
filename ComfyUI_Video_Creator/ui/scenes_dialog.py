"""Manage the scene snippet library: tags, their snippets, import and reset.

Edits go straight into the shared SceneLibrary (saved on every change), so there
is no Apply/Cancel — closing the window just closes it.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from scenes import SceneLibrary
from ui.styles import COLORS


class PasteImportDialog(QDialog):
    """Paste an AI reply with several titled scenarios; each becomes a snippet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import from Paste")
        self.resize(760, 560)
        self.setStyleSheet(parent.window().styleSheet() if parent else "")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Paste an AI reply with numbered, titled scenarios (1. Title …). "
                             "Each one becomes a snippet; the titles become its name."))
        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("Paste here…")
        lay.addWidget(self._edit, stretch=1)
        row = QHBoxLayout()
        paste = QPushButton("📋 Paste from Clipboard")
        paste.setObjectName("secondary_btn")
        paste.clicked.connect(lambda: self._edit.setPlainText(QApplication.clipboard().text()))
        row.addWidget(paste)
        row.addStretch()
        ok = QPushButton("Import")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondary_btn")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def text(self) -> str:
        return self._edit.toPlainText()


class ScenesDialog(QDialog):
    def __init__(self, lib: SceneLibrary, start_tag: str = "", parent=None):
        super().__init__(parent)
        self._lib = lib
        self._sid = ""              # snippet being edited
        self._loading = False
        self.setWindowTitle("Scenes")
        self.setMinimumSize(980, 560)
        self.resize(1180, 700)
        self.setStyleSheet(parent.window().styleSheet() if parent else "")

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        # tags
        left = QVBoxLayout()
        left.addWidget(self._bold("Tags"))
        self._tag_list = QListWidget()
        self._tag_list.setFixedWidth(190)
        self._tag_list.currentRowChanged.connect(self._fill_snippets)
        left.addWidget(self._tag_list, stretch=1)
        for text, fn in (("＋ Add Tag", self._add_tag), ("Delete Tag", self._delete_tag)):
            b = QPushButton(text)
            b.setObjectName("secondary_btn")
            b.clicked.connect(fn)
            left.addWidget(b)
        root.addLayout(left)

        # snippets
        mid = QVBoxLayout()
        self._snip_title = self._bold("Snippets")
        mid.addWidget(self._snip_title)
        self._snip_list = QListWidget()
        self._snip_list.setMinimumWidth(300)
        self._snip_list.currentRowChanged.connect(self._load_snippet)
        mid.addWidget(self._snip_list, stretch=1)
        row = QHBoxLayout()
        for text, fn in (("＋ Add", self._add_snippet), ("Delete", self._delete_snippet)):
            b = QPushButton(text)
            b.setObjectName("secondary_btn")
            b.clicked.connect(fn)
            row.addWidget(b)
        mid.addLayout(row)
        for text, fn in (("📥 Import from Paste…", self._import_paste),
                         ("📂 Import Placeholder data.json…", self._import_placeholder),
                         ("↺ Reset used marks (this tag)", self._reset_used)):
            b = QPushButton(text)
            b.setObjectName("secondary_btn")
            b.clicked.connect(fn)
            mid.addWidget(b)
        root.addLayout(mid)

        # editor
        right = QVBoxLayout()
        right.addWidget(self._bold("Name (optional — only for finding it in the list, never sent)"))
        self._name = QLineEdit()
        self._name.textEdited.connect(self._save_snippet)
        right.addWidget(self._name)
        right.addWidget(self._bold("Text that replaces {{tag}}"))
        self._text = QPlainTextEdit()
        self._text.textChanged.connect(self._save_snippet)
        right.addWidget(self._text, stretch=1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        right.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        root.addLayout(right, stretch=1)

        self._fill_tags(start_tag)

    @staticmethod
    def _bold(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['fg_secondary']}; font-weight: bold;")
        return lbl

    # ------------------------------------------------------------------ tags
    def _tag(self) -> str:
        it = self._tag_list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else ""

    def _fill_tags(self, select: str = ""):
        self._tag_list.blockSignals(True)
        self._tag_list.clear()
        for tag in self._lib.tags():
            it = QListWidgetItem(f"{{{{{tag}}}}}  ({len(self._lib.snippets(tag))})")
            it.setData(Qt.ItemDataRole.UserRole, tag)
            self._tag_list.addItem(it)
        self._tag_list.blockSignals(False)
        names = self._lib.tags()
        self._tag_list.setCurrentRow(names.index(select) if select in names else (0 if names else -1))
        self._fill_snippets()

    def _add_tag(self):
        name, ok = QInputDialog.getText(self, "Add Tag", "Tag name (letters, digits, _ or -):")
        if not ok:
            return
        if not self._lib.add_tag(name):
            QMessageBox.information(self, "Add Tag", "That name is invalid or already exists.")
            return
        self._fill_tags(name.strip())

    def _delete_tag(self):
        tag = self._tag()
        if tag and QMessageBox.question(
                self, "Delete Tag", f"Delete {{{{{tag}}}}} and all {len(self._lib.snippets(tag))} of its snippets?"
        ) == QMessageBox.StandardButton.Yes:
            self._lib.delete_tag(tag)
            self._fill_tags()

    # -------------------------------------------------------------- snippets
    def _fill_snippets(self, *_):
        tag = self._tag()
        self._snip_title.setText(f"Snippets for {{{{{tag}}}}}" if tag else "Snippets")
        self._snip_list.blockSignals(True)
        self._snip_list.clear()
        for i, s in enumerate(self._lib.snippets(tag) if tag else []):
            label = s["name"] or " ".join(s["text"].split())[:60]
            mark = "✓ " if self._lib.is_used(tag, s["id"]) else ""
            it = QListWidgetItem(f"{mark}{i + 1}. {label}")
            it.setData(Qt.ItemDataRole.UserRole, s["id"])
            self._snip_list.addItem(it)
        self._snip_list.blockSignals(False)
        self._snip_list.setCurrentRow(0 if self._snip_list.count() else -1)
        self._load_snippet(self._snip_list.currentRow())

    def _refresh_tag_counts(self):
        row = self._tag_list.currentRow()
        for i in range(self._tag_list.count()):
            it = self._tag_list.item(i)
            tag = it.data(Qt.ItemDataRole.UserRole)
            it.setText(f"{{{{{tag}}}}}  ({len(self._lib.snippets(tag))})")
        self._tag_list.setCurrentRow(row)

    def _load_snippet(self, row: int):
        tag = self._tag()
        items = self._lib.snippets(tag) if tag else []
        self._loading = True
        if 0 <= row < len(items):
            self._sid = items[row]["id"]
            self._name.setText(items[row]["name"])
            self._text.setPlainText(items[row]["text"])
        else:
            self._sid = ""
            self._name.clear()
            self._text.clear()
        self._loading = False
        self._name.setEnabled(bool(self._sid))
        self._text.setEnabled(bool(self._sid))

    def _save_snippet(self, *_):
        tag = self._tag()
        if self._loading or not tag or not self._sid:
            return
        self._lib.update_snippet(tag, self._sid, self._name.text().strip(), self._text.toPlainText().strip())
        it = self._snip_list.currentItem()
        if it is not None:
            i = self._snip_list.currentRow()
            label = self._name.text().strip() or " ".join(self._text.toPlainText().split())[:60]
            mark = "✓ " if self._lib.is_used(tag, self._sid) else ""
            it.setText(f"{mark}{i + 1}. {label}")

    def _add_snippet(self):
        tag = self._tag()
        if not tag:
            QMessageBox.information(self, "Add snippet", "Add a tag first.")
            return
        self._lib.add_snippet(tag, "", "New scene — type its text here")
        self._fill_snippets()
        self._snip_list.setCurrentRow(self._snip_list.count() - 1)
        self._refresh_tag_counts()
        self._text.setFocus()
        self._text.selectAll()

    def _delete_snippet(self):
        tag = self._tag()
        if tag and self._sid:
            row = self._snip_list.currentRow()
            self._lib.delete_snippet(tag, self._sid)
            self._fill_snippets()
            self._snip_list.setCurrentRow(min(row, self._snip_list.count() - 1))
            self._refresh_tag_counts()

    def _import_paste(self):
        tag = self._tag()
        if not tag:
            QMessageBox.information(self, "Import", "Add or select a tag first.")
            return
        dlg = PasteImportDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        n = self._lib.import_paste(tag, dlg.text())
        if not n:
            QMessageBox.information(self, "Import", "Nothing to import — the pasted text was empty.")
            return
        self._fill_snippets()
        self._refresh_tag_counts()
        QMessageBox.information(self, "Import", f"Added {n} snippet{'s' if n != 1 else ''} to {{{{{tag}}}}}.")

    def _import_placeholder(self):
        start = Path(__file__).resolve().parents[2] / "Document Update Placeholder"
        path, _ = QFileDialog.getOpenFileName(
            self, "Document Update Placeholder data.json", str(start if start.exists() else Path.home()),
            "JSON (*.json)")
        if not path:
            return
        try:
            tags, added = self._lib.import_placeholder(Path(path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import", f"Could not read that file:\n{e}")
            return
        self._fill_tags(self._tag())
        QMessageBox.information(self, "Import", f"Added {added} snippet{'s' if added != 1 else ''} "
                                                f"across {tags} tag{'s' if tags != 1 else ''} "
                                                "(snippets already here were skipped).")

    def _reset_used(self):
        tag = self._tag()
        if tag:
            self._lib.reset_used(tag)
            row = self._snip_list.currentRow()
            self._fill_snippets()
            self._snip_list.setCurrentRow(row)
