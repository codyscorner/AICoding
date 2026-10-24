"""File Hash Dedupe - Main Entry Point"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from config import ConfigManager
from ui.main_window import MainWindow

VERSION = "1.5.0"


def get_config_file() -> Path:
    if getattr(sys, 'frozen', False):
        exe_name = Path(sys.executable).stem
        return Path(sys.executable).parent / f"{exe_name}_config.json"
    return Path(__file__).parent / f"{Path(__file__).stem}_config.json"


def main():
    app = QApplication(sys.argv)
    config_manager = ConfigManager(get_config_file())
    window = MainWindow(config_manager, VERSION)
    icon_path = Path(__file__).parent / "app_icon.ico"
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
