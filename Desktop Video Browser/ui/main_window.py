import os
import base64
from PySide6.QtWidgets import QMainWindow, QSplitter
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from ui.file_list_panel import FileListPanel
from ui.folder_tree_panel import FolderTreePanel
from ui.video_player_panel import VideoPlayerPanel
from core.settings import AppSettings
from core.paths import get_app_dir, resource_path
from version import VERSION

SETTINGS_PATH = os.path.join(get_app_dir(), "settings.json")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Desktop Video Browser v{VERSION}")
        self.resize(1450, 750)
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.folder_tree_panel = FolderTreePanel()
        self.file_list_panel = FileListPanel()
        self.video_player_panel = VideoPlayerPanel()

        self.folder_tree_panel.folderSelected.connect(self._on_tree_folder_selected)
        self.file_list_panel.fileSelected.connect(self.video_player_panel.load_video)
        self.file_list_panel.start_folder_provider = self.folder_tree_panel.highlighted_folder
        self.file_list_panel.folderOpened.connect(self._on_folder_opened)
        self.file_list_panel.sortModeChanged.connect(self._on_sort_mode_changed)
        self.file_list_panel.fileAboutToBeDeleted.connect(self._on_file_about_to_be_deleted)
        self.video_player_panel.navigateRequested.connect(self.file_list_panel.navigate)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.folder_tree_panel)
        self.splitter.addWidget(self.file_list_panel)
        self.splitter.addWidget(self.video_player_panel)
        self.splitter.setSizes([220, 280, 950])

        self.setCentralWidget(self.splitter)
        self._load_settings()

    def _load_settings(self):
        self.settings = AppSettings.load(SETTINGS_PATH)

        if self.settings.geometry:
            self.restoreGeometry(base64.b64decode(self.settings.geometry))

        if self.settings.sort_mode:
            self.file_list_panel.set_sort_mode(self.settings.sort_mode)

        if self.settings.last_opened_folder and os.path.isdir(self.settings.last_opened_folder):
            self.file_list_panel.load_folder(self.settings.last_opened_folder)
            self.folder_tree_panel.set_current_folder(self.settings.last_opened_folder)

    def _on_tree_folder_selected(self, folder: str) -> None:
        self.file_list_panel.load_folder(folder)
        self._on_folder_opened(folder)

    def _on_folder_opened(self, folder: str):
        self.video_player_panel.release()
        self.settings.last_opened_folder = folder
        self.folder_tree_panel.set_current_folder(folder)

    def _on_sort_mode_changed(self, mode: str) -> None:
        self.settings.sort_mode = mode

    def _on_file_about_to_be_deleted(self, path: str) -> None:
        if self.video_player_panel.current_path == path:
            self.video_player_panel.release()

    def closeEvent(self, event):
        self.settings.geometry = base64.b64encode(self.saveGeometry().data()).decode("ascii")
        self.settings.save(SETTINGS_PATH)
        super().closeEvent(event)
