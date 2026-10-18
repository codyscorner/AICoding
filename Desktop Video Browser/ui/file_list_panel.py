import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QFileDialog, QLabel, QComboBox, QMenu, QApplication, QMessageBox,
)
from PySide6.QtCore import Signal, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from core.file_loader import list_video_files

SORT_MODES = [
    ("name_asc", "Name (A-Z)"),
    ("name_desc", "Name (Z-A)"),
    ("date_newest", "Date Modified (Newest)"),
    ("date_oldest", "Date Modified (Oldest)"),
    ("size_largest", "Size (Largest)"),
    ("size_smallest", "Size (Smallest)"),
]
_DEFAULT_SORT_MODE = "name_asc"


class FileListPanel(QWidget):
    fileSelected = Signal(str)
    folderOpened = Signal(str)
    sortModeChanged = Signal(str)
    fileAboutToBeDeleted = Signal(str)

    def __init__(self):
        super().__init__()
        self._current_folder: str = ""
        self._files: list[str] = []
        self._sort_mode: str = _DEFAULT_SORT_MODE
        # Callable returning the folder highlighted in the tree (set by MainWindow).
        self.start_folder_provider = None
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        btn_row = QHBoxLayout()

        self.open_button = QPushButton("Open Folder...")
        self.open_button.clicked.connect(self._browse_folder)
        btn_row.addWidget(self.open_button)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh)
        btn_row.addWidget(self.refresh_button)

        layout.addLayout(btn_row)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        for mode_id, mode_label in SORT_MODES:
            self.sort_combo.addItem(mode_label, mode_id)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self.sort_combo, 1)
        layout.addLayout(sort_row)

        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

        self.path_label = QLabel("No folder selected")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color: #888; font-size: 11px; padding: 2px;")
        self.path_label.setCursor(Qt.PointingHandCursor)
        self.path_label.setToolTip("Click to copy folder path")
        self.path_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.path_label.mousePressEvent = self._on_path_label_clicked
        self.path_label.customContextMenuRequested.connect(self._show_path_label_menu)
        layout.addWidget(self.path_label)

    def load_folder(self, path: str) -> None:
        self._current_folder = path
        self.path_label.setText(path)
        self._files = list_video_files(path)
        self._populate()

    def set_sort_mode(self, mode: str) -> None:
        if mode not in dict(SORT_MODES):
            return
        self._sort_mode = mode
        index = self.sort_combo.findData(mode)
        if index >= 0:
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(index)
            self.sort_combo.blockSignals(False)

    def _on_sort_changed(self, index: int) -> None:
        mode = self.sort_combo.itemData(index)
        if not mode:
            return
        self._sort_mode = mode
        self._populate()
        self.sortModeChanged.emit(mode)

    def _sorted_files(self) -> list[str]:
        files = list(self._files)
        if self._sort_mode == "name_desc":
            files.sort(key=lambda p: os.path.basename(p).lower(), reverse=True)
        elif self._sort_mode == "date_newest":
            files.sort(key=self._safe_mtime, reverse=True)
        elif self._sort_mode == "date_oldest":
            files.sort(key=self._safe_mtime, reverse=False)
        elif self._sort_mode == "size_largest":
            files.sort(key=self._safe_size, reverse=True)
        elif self._sort_mode == "size_smallest":
            files.sort(key=self._safe_size, reverse=False)
        else:
            files.sort(key=lambda p: os.path.basename(p).lower(), reverse=False)
        return files

    @staticmethod
    def _safe_mtime(path: str) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    @staticmethod
    def _safe_size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _populate(self) -> None:
        self.list_widget.clear()
        for full_path in self._sorted_files():
            item = QListWidgetItem(os.path.basename(full_path))
            item.setData(Qt.UserRole, full_path)
            self.list_widget.addItem(item)

    def _refresh(self) -> None:
        if self._current_folder:
            self.load_folder(self._current_folder)

    def _browse_folder(self):
        # Always start the dialog in the folder highlighted in the tree. With no
        # start dir Windows falls back to the process's working directory, which
        # in the built EXE is the EXE's own folder.
        start = self.start_folder_provider() if self.start_folder_provider else ""
        if not start or not os.path.isdir(start):
            start = self._current_folder
        if not start or not os.path.isdir(start):
            start = ""
        folder = QFileDialog.getExistingDirectory(
            self, "Open Folder", os.path.normpath(start) if start else ""
        )
        if folder:
            self.load_folder(folder)
            self.folderOpened.emit(folder)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.fileSelected.emit(item.data(Qt.UserRole))

    def navigate(self, delta: int) -> None:
        count = self.list_widget.count()
        if count == 0:
            return
        current = self.list_widget.currentRow()
        new_row = max(0, min(count - 1, current + delta))
        if new_row != current:
            self.list_widget.setCurrentRow(new_row)

    def _on_row_changed(self, row: int) -> None:
        item = self.list_widget.item(row)
        if item:
            self.fileSelected.emit(item.data(Qt.UserRole))

    # ------------------------------------------------------------------
    # Copy path / context menus
    # ------------------------------------------------------------------

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _on_path_label_clicked(self, event) -> None:
        if self._current_folder:
            self._copy_to_clipboard(self._current_folder)
            self._flash_path_label("Copied!")

    def _show_path_label_menu(self, pos) -> None:
        if not self._current_folder:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Copy Folder Path")
        chosen = menu.exec(self.path_label.mapToGlobal(pos))
        if chosen == copy_action:
            self._copy_to_clipboard(self._current_folder)
            self._flash_path_label("Copied!")

    def _flash_path_label(self, message: str) -> None:
        original = self._current_folder
        self.path_label.setText(message)
        QTimer.singleShot(900, lambda: self.path_label.setText(original))

    def _show_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        full_path = item.data(Qt.UserRole)

        menu = QMenu(self)
        copy_path_action = menu.addAction("Copy Full Path")
        copy_name_action = menu.addAction("Copy File Name")
        menu.addSeparator()
        show_in_explorer_action = menu.addAction("Show in Explorer")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen == copy_path_action:
            self._copy_to_clipboard(full_path)
        elif chosen == copy_name_action:
            self._copy_to_clipboard(os.path.basename(full_path))
        elif chosen == show_in_explorer_action:
            self._show_in_explorer(full_path)
        elif chosen == delete_action:
            self._delete_file(item, full_path)

    def _delete_file(self, item: QListWidgetItem, full_path: str) -> None:
        name = os.path.basename(full_path)
        answer = QMessageBox.question(
            self,
            "Delete File",
            f'Delete "{name}"?\n\nThis will permanently delete the file from disk. '
            f"This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.fileAboutToBeDeleted.emit(full_path)
        try:
            os.remove(full_path)
        except OSError as exc:
            QMessageBox.critical(self, "Delete Failed", f'Could not delete "{name}":\n{exc}')
            return

        if full_path in self._files:
            self._files.remove(full_path)
        row = self.list_widget.row(item)
        self.list_widget.takeItem(row)

    @staticmethod
    def _show_in_explorer(full_path: str) -> None:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", os.path.normpath(full_path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(full_path)))

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.load_folder(path)
                self.folderOpened.emit(path)
                break
