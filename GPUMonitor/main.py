"""GPU Monitor — live RTX 3090 monitoring plus power-limit and core-clock-cap control."""

import sys

VERSION = "1.0.2"
APP_ID = "CodyLab.GPUMonitor"


def resource_path(name):
    import os
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def run_gui():
    import ctypes

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from ui import theme
    from ui.main_window import MainWindow

    try:  # own taskbar identity so Windows uses our icon instead of python.exe's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("app_icon.ico")))
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    try:
        win = MainWindow(VERSION)
    except Exception as e:  # no NVIDIA driver / NVML missing
        QMessageBox.critical(None, "GPU Monitor", f"Could not talk to the NVIDIA driver:\n{e}")
        return 1
    win.show()
    return app.exec()


if __name__ == "__main__":
    if "--apply" in sys.argv:
        import apply_cli
        sys.exit(apply_cli.main(sys.argv[1:]))
    sys.exit(run_gui())
