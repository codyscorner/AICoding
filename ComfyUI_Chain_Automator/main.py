"""
ComfyUI Workflow Chain Automator
Version: 3.12.0
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer

from config import ConfigManager
from ui.main_window import MainWindow

VERSION = "3.12.0"

# Windows taskbar icon fix — must be called before QApplication
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "ComfyUI.ChainAutomator.2"
    )
except Exception:
    pass


def _force_foreground(window):
    """raise_()/activateWindow() alone often get silently ignored - Windows
    blocks a background process from stealing focus unless it looks like the
    user just pressed a key. A harmless Alt tap satisfies that check so a
    Stream-Deck-launched (or otherwise unfocused-parent) start actually comes
    to the front instead of just flashing in the taskbar. (Same helper as
    ComfyUI Video Creator.)"""
    try:
        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        user32.keybd_event(0x12, 0, 0, 0)   # VK_MENU (Alt) down
        user32.keybd_event(0x12, 0, 2, 0)   # VK_MENU up (KEYEVENTF_KEYUP)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    window.raise_()
    window.activateWindow()


def get_script_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _find_icon() -> Path | None:
    """Look for app_icon.ico next to the EXE, then in the bundled _MEIPASS dir."""
    script_dir = get_script_dir()
    candidate = script_dir / "app_icon.ico"
    if candidate.exists():
        return candidate
    if getattr(sys, 'frozen', False):
        bundled = Path(sys._MEIPASS) / "app_icon.ico"
        if bundled.exists():
            return bundled
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ComfyUI Workflow Chain Automator")

    icon_path = _find_icon()
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))

    script_dir = get_script_dir()

    config_file = script_dir / "main_config.json"
    config_manager = ConfigManager(config_file)
    config_manager.set("_base_dir", str(script_dir))

    window = MainWindow(config_manager, VERSION)
    window.show()
    _force_foreground(window)
    # Re-assert once the first paint has settled, and again after the startup
    # pod prompt / chain-validation dialogs (queued at 0-200 ms from showEvent)
    # have had a chance to grab focus, so the app never sits behind other windows.
    for delay in (200, 800):
        QTimer.singleShot(delay, lambda: _force_foreground(window))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
