import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow

# Own taskbar identity: without this Windows groups the window under
# python.exe and shows its icon instead of ours.
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("S3Browser.App.1")
except Exception:
    pass


def resource_path(name: str) -> Path:
    """Locate a bundled read-only resource: PyInstaller's unpack folder when
    frozen (datas land there), else the project root next to run.py."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parent.parent) / name


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("S3 Browser")
    # App-level icon covers the taskbar and every dialog; the window icon is
    # set too for the title bar.
    icon_path = resource_path("app_icon.ico")
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    app.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
