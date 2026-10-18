import os
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeView, QFileSystemModel, QMenu, QApplication,
)
from PySide6.QtCore import Signal, QDir, Qt

_NAV_KEYS = {
    Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
    Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown,
    Qt.Key_Return, Qt.Key_Enter,
}


class _NavigableTreeView(QTreeView):
    """QTreeView that reports its current index only after a real key press.

    QFileSystemModel/QTreeView can change the "current" index on their own
    (e.g. defaulting to the process's working-directory drive once the drive
    list finishes populating), which would otherwise be indistinguishable
    from a genuine user selection via currentChanged.
    """

    def __init__(self, on_navigate):
        super().__init__()
        self._on_navigate = on_navigate

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)
        if event.key() in _NAV_KEYS:
            self._on_navigate(self.currentIndex())


class FolderTreePanel(QWidget):
    folderSelected = Signal(str)

    def __init__(self):
        super().__init__()
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.model = QFileSystemModel()
        self.model.setRootPath("")
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)

        self.tree = _NavigableTreeView(self._emit_for_index)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(""))
        self.tree.setHeaderHidden(True)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.setAnimated(True)
        self.tree.clicked.connect(self._emit_for_index)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree)

    def _emit_for_index(self, index) -> None:
        if self._syncing or not index.isValid():
            return
        path = self.model.filePath(index)
        if path:
            self.folderSelected.emit(path)

    def _show_context_menu(self, pos) -> None:
        # Act on the folder under the cursor, not the highlighted one, so a
        # right-click never needs a left-click first (and never reloads the list).
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        path = os.path.normpath(self.model.filePath(index))
        menu = QMenu(self)
        open_action = menu.addAction("Open in Explorer")
        copy_action = menu.addAction("Copy Folder Path")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == open_action:
            self._open_in_explorer(path)
        elif chosen == copy_action:
            QApplication.clipboard().setText(path)

    @staticmethod
    def _open_in_explorer(path: str) -> None:
        if os.path.isdir(path):
            subprocess.Popen(["explorer", path])

    def highlighted_folder(self) -> str:
        """Path of the folder currently highlighted in the tree ('' if none)."""
        index = self.tree.currentIndex()
        if not index.isValid():
            return ""
        return self.model.filePath(index)

    def set_current_folder(self, path: str) -> None:
        if not path:
            return
        index = self.model.index(path)
        if not index.isValid():
            return

        self._syncing = True
        try:
            parent = index.parent()
            while parent.isValid():
                self.tree.expand(parent)
                parent = parent.parent()
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)
        finally:
            self._syncing = False
