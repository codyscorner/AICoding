import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from config import ConfigManager
from profiles import ProfileManager
from ui.main_window import MainWindow
from ui.styles import STYLESHEET

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
VERSION = "1.1.1"


def main() -> None:
    # Own taskbar identity so Windows doesn't group us under python.exe.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FolderSync.App.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("FolderSync")
    app.setStyleSheet(STYLESHEET)

    # The icon is bundled read-only data: PyInstaller's unpack folder when
    # frozen (settings stay next to the EXE via BASE_DIR), else the source dir.
    icon_path = Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config = ConfigManager(BASE_DIR / "foldersync_config.json")
    profiles = ProfileManager(BASE_DIR / "sync_profiles.json")
    window = MainWindow(config, profiles, BASE_DIR, VERSION)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
