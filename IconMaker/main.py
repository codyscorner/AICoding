"""
IconMaker GUI — PyQt6 wrapper around make_icons.py
"""

import json
import random
import shutil
import sys
import threading
from pathlib import Path

import make_icons

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QSpinBox, QTextEdit,
    QVBoxLayout, QWidget,
)

VERSION = "1.1.2"

BG_DARK      = "#0d0d1a"
BG_MID       = "#12122a"
BG_PANEL     = "#1a1a30"
ACCENT       = "#5e4bdb"
ACCENT_HOVER = "#7a68f0"
TEXT_BRIGHT  = "#d4d0f5"
TEXT_DIM     = "#8880cc"
BORDER       = "#2d2a5a"
SUCCESS      = "#39d353"
ERROR_COL    = "#e05c5c"
WARNING_COL  = "#e0a020"

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_BRIGHT};
    font-family: "Segoe UI";
    font-size: 9pt;
}}
QLabel {{
    background-color: transparent;
    color: {TEXT_DIM};
}}
QLabel#title {{
    font-size: 13pt;
    font-weight: bold;
    color: {TEXT_BRIGHT};
}}
QLabel#version {{
    font-size: 8pt;
    color: {TEXT_DIM};
}}
QLabel#progress {{
    font-size: 9pt;
    color: {TEXT_BRIGHT};
}}
QLineEdit {{
    background-color: {BG_PANEL};
    color: {TEXT_BRIGHT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 5px;
    font-size: 9pt;
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}
QPushButton {{
    background-color: {ACCENT};
    color: {TEXT_BRIGHT};
    font-weight: bold;
    border: none;
    border-radius: 3px;
    padding: 6px 14px;
    font-size: 9pt;
}}
QPushButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#secondary {{
    background-color: {BG_PANEL};
    font-weight: normal;
}}
QPushButton#secondary:hover {{
    background-color: {BORDER};
}}
QListWidget {{
    background-color: {BG_PANEL};
    color: {TEXT_BRIGHT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    font-size: 9pt;
}}
QListWidget::item:selected {{
    background-color: {ACCENT};
}}
QTextEdit {{
    background-color: {BG_MID};
    color: {TEXT_BRIGHT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    font-family: Consolas;
    font-size: 8pt;
}}
"""


class IconWorker(QThread):
    log_line     = pyqtSignal(str, str)   # (message, color)
    progress     = pyqtSignal(int, int, str)  # (current, total, name)
    request_pick = pyqtSignal(str, list)  # (app name, candidate png paths) — blocks until resolve_pick()
    finished     = pyqtSignal()

    def __init__(self, apps: list, comfy_url: str, output_path: str,
                 num_candidates: int = 1, padding_pct: int = 0, corner_radius_pct: int = 0):
        super().__init__()
        self.apps              = apps
        self.comfy_url         = comfy_url
        self.output_path       = Path(output_path)
        self.num_candidates    = max(1, num_candidates)
        self.padding_pct       = padding_pct
        self.corner_radius_pct = corner_radius_pct
        self._pick_event       = threading.Event()
        self._pick_result      = 0

    def resolve_pick(self, index: int):
        """Called from the main thread once the user has chosen a candidate."""
        self._pick_result = index
        self._pick_event.set()

    def run(self):
        # Override module-level globals so helper functions use user config
        make_icons.COMFY_URL    = self.comfy_url
        make_icons.COMFY_OUTPUT = self.output_path

        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        projects_root = Path(__file__).parent.parent

        try:
            base_workflow = make_icons.load_workflow()
        except Exception as e:
            self.log_line.emit(f"ERROR loading workflow: {e}", ERROR_COL)
            self.finished.emit()
            return

        total = len(self.apps)
        for idx, app in enumerate(self.apps, 1):
            name           = app["name"]
            project_folder = projects_root / app["project_folder"]
            self.progress.emit(idx, total, name)

            self.log_line.emit(f"\n[{idx}/{total}] {name}", ACCENT)
            self.log_line.emit("-" * 40, TEXT_DIM)

            candidates = []  # list of (png_path, seed)
            for c in range(self.num_candidates):
                seed = random.randint(1, 2**31)
                workflow = json.loads(json.dumps(base_workflow))
                workflow["91"]["inputs"]["value"]             = app["prompt"]
                workflow["86:3"]["inputs"]["seed"]            = seed
                workflow["86:58"]["inputs"]["width"]          = 512
                workflow["86:58"]["inputs"]["height"]         = 512
                workflow["60"]["inputs"]["filename_prefix"]   = f"icon_{name}_{c + 1}"

                try:
                    prompt_id = make_icons.submit_prompt(workflow)
                except Exception as e:
                    self.log_line.emit(f"  ERROR submitting prompt (candidate {c + 1}): {e}", ERROR_COL)
                    continue

                self.log_line.emit(
                    f"  Waiting for ComfyUI… (candidate {c + 1}/{self.num_candidates})", TEXT_DIM
                )
                if not make_icons.wait_for_completion(prompt_id):
                    self.log_line.emit(f"  SKIPPED candidate {c + 1} — timed out", WARNING_COL)
                    continue

                filename = make_icons.get_output_filename(prompt_id)
                if not filename:
                    self.log_line.emit(f"  SKIPPED candidate {c + 1} — no output filename found", WARNING_COL)
                    continue

                src_png = self.output_path / filename
                cand_png = output_dir / f"{name}_candidate_{c + 1}.png"
                try:
                    shutil.copy2(src_png, cand_png)
                    candidates.append((cand_png, seed))
                except Exception as e:
                    self.log_line.emit(f"  ERROR copying candidate {c + 1}: {e}", ERROR_COL)

            if not candidates:
                self.log_line.emit("  SKIPPED — no candidates generated", WARNING_COL)
                continue

            if len(candidates) > 1:
                self.log_line.emit("  Pick a candidate to continue…", TEXT_DIM)
                self._pick_event.clear()
                self.request_pick.emit(name, [str(p) for p, _ in candidates])
                self._pick_event.wait()
                chosen_idx = min(self._pick_result, len(candidates) - 1)
            else:
                chosen_idx = 0

            chosen_png, chosen_seed = candidates[chosen_idx]
            dst_png = output_dir / f"{name}.png"
            try:
                shutil.copy2(chosen_png, dst_png)
                self.log_line.emit(f"  PNG  -> {dst_png.name} (candidate {chosen_idx + 1})", SUCCESS)
            except Exception as e:
                self.log_line.emit(f"  ERROR copying chosen PNG: {e}", ERROR_COL)
                continue

            for p, _ in candidates:
                if p != dst_png:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass

            ico_path = output_dir / f"{name}.ico"
            try:
                make_icons.convert_to_ico(dst_png, ico_path, self.padding_pct, self.corner_radius_pct)
                self.log_line.emit(f"  ICO  -> {ico_path.name}", SUCCESS)
            except Exception as e:
                self.log_line.emit(f"  ERROR converting ICO: {e}", ERROR_COL)
                continue

            if project_folder.exists():
                project_ico = project_folder / "app_icon.ico"
                shutil.copy2(ico_path, project_ico)
                self.log_line.emit(f"  COPY -> {project_folder.name}/app_icon.ico", SUCCESS)
            else:
                self.log_line.emit(f"  WARN — project folder not found: {project_folder}", WARNING_COL)

            make_icons.append_prompt_history(name, app["prompt"], chosen_seed)

        self.log_line.emit(f"\n{'=' * 40}", TEXT_DIM)
        self.log_line.emit(f"Done! {total} icon(s) generated.", ACCENT)
        self.finished.emit()


class CandidatePickerDialog(QDialog):
    """Modal grid of generated candidate PNGs — pick one to keep."""

    def __init__(self, app_name: str, candidate_paths: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Pick an icon for {app_name}")
        self.setMinimumSize(420, 320)
        self.selected_index = 0

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Choose the best candidate for {app_name}:"))

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(128, 128))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        for i, path in enumerate(candidate_paths):
            item = QListWidgetItem(QIcon(path), f"#{i + 1}")
            self.list.addItem(item)
        if candidate_paths:
            self.list.setCurrentRow(0)
        layout.addWidget(self.list)

        btn = QPushButton("Use Selected")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

    def accept(self):
        self.selected_index = max(0, self.list.currentRow())
        super().accept()


class IconMakerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"IconMaker  v{VERSION}")
        self.setMinimumSize(700, 600)
        self.setStyleSheet(STYLESHEET)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Title bar
        title_row = QHBoxLayout()
        lbl_title = QLabel("🎨  IconMaker")
        lbl_title.setObjectName("title")
        lbl_ver = QLabel(f"v{VERSION}")
        lbl_ver.setObjectName("version")
        title_row.addWidget(lbl_title)
        title_row.addWidget(lbl_ver)
        title_row.addStretch()
        layout.addLayout(title_row)

        # App list label + Select All / Deselect All
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Apps to generate icons for:"))
        list_header.addStretch()
        btn_all = QPushButton("Select All")
        btn_all.setObjectName("secondary")
        btn_all.setFixedWidth(90)
        btn_none = QPushButton("Deselect All")
        btn_none.setObjectName("secondary")
        btn_none.setFixedWidth(90)
        btn_history = QPushButton("View History")
        btn_history.setObjectName("secondary")
        btn_history.setFixedWidth(90)
        btn_history.clicked.connect(self._view_history)
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._deselect_all)
        list_header.addWidget(btn_all)
        list_header.addWidget(btn_none)
        list_header.addWidget(btn_history)
        layout.addLayout(list_header)

        # App list
        self.app_list = QListWidget()
        self.app_list.setFixedHeight(180)
        for app in make_icons.APPS:
            item = QListWidgetItem(app["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.app_list.addItem(item)
        layout.addWidget(self.app_list)

        # Config row
        cfg_layout = QHBoxLayout()
        cfg_layout.addWidget(QLabel("ComfyUI URL:"))
        self.url_edit = QLineEdit(make_icons.COMFY_URL)
        cfg_layout.addWidget(self.url_edit, 2)
        cfg_layout.addWidget(QLabel("Output Folder:"))
        self.output_edit = QLineEdit(str(make_icons.COMFY_OUTPUT))
        cfg_layout.addWidget(self.output_edit, 3)
        layout.addLayout(cfg_layout)

        # Generation options row
        opts_layout = QHBoxLayout()
        opts_layout.addWidget(QLabel("Candidates per app:"))
        self.candidates_spin = QSpinBox()
        self.candidates_spin.setRange(1, 4)
        self.candidates_spin.setValue(1)
        opts_layout.addWidget(self.candidates_spin)
        opts_layout.addSpacing(12)
        opts_layout.addWidget(QLabel("Padding %:"))
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 40)
        self.padding_spin.setValue(0)
        opts_layout.addWidget(self.padding_spin)
        opts_layout.addSpacing(12)
        opts_layout.addWidget(QLabel("Corner Radius %:"))
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(0, 50)
        self.radius_spin.setValue(0)
        opts_layout.addWidget(self.radius_spin)
        opts_layout.addStretch()
        btn_scan = QPushButton("Scan for Missing Icons")
        btn_scan.setObjectName("secondary")
        btn_scan.clicked.connect(self._scan_missing_icons)
        opts_layout.addWidget(btn_scan)
        layout.addLayout(opts_layout)

        # Generate button + progress label
        gen_row = QHBoxLayout()
        self.btn_generate = QPushButton("Generate Icons")
        self.btn_generate.setFixedWidth(150)
        self.btn_generate.clicked.connect(self._start_generation)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("progress")
        gen_row.addWidget(self.btn_generate)
        gen_row.addWidget(self.lbl_progress)
        gen_row.addStretch()
        layout.addLayout(gen_row)

        # Log
        layout.addWidget(QLabel("Log:"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box, 1)

    def _select_all(self):
        for i in range(self.app_list.count()):
            self.app_list.item(i).setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self):
        for i in range(self.app_list.count()):
            self.app_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _log(self, message: str, color: str = TEXT_BRIGHT):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.log_box.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(message + "\n", fmt)
        self.log_box.setTextCursor(cursor)
        self.log_box.ensureCursorVisible()

    def _on_progress(self, current: int, total: int, name: str):
        self.lbl_progress.setText(f"Processing {current} / {total}: {name}…")

    def _on_finished(self):
        self.btn_generate.setEnabled(True)
        self.lbl_progress.setText("Done.")

    def _on_request_pick(self, app_name: str, candidate_paths: list):
        dlg = CandidatePickerDialog(app_name, candidate_paths, self)
        dlg.exec()
        self._worker.resolve_pick(dlg.selected_index)

    def _view_history(self):
        item = self.app_list.currentItem()
        if item is None:
            self._log("Select an app in the list first.", WARNING_COL)
            return
        name = item.text()
        history = make_icons.load_prompt_history().get(name, [])
        if not history:
            self._log(f"No prompt history for {name}.", TEXT_DIM)
            return
        self._log(f"\nHistory for {name}:", ACCENT)
        for entry in history:
            self._log(f"  [{entry['timestamp']}] seed={entry['seed']}  {entry['prompt']}", TEXT_DIM)

    def _scan_missing_icons(self):
        missing = make_icons.find_projects_missing_icon()
        if not missing:
            self._log("\nNo projects found missing an app_icon.ico.", SUCCESS)
            return
        self._log(f"\n{len(missing)} project(s) missing an app_icon.ico:", WARNING_COL)
        for name in missing:
            self._log(f"  - {name}", TEXT_DIM)

    def _start_generation(self):
        selected = []
        for i in range(self.app_list.count()):
            item = self.app_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(make_icons.APPS[i])

        if not selected:
            self._log("No apps selected.", WARNING_COL)
            return

        self.btn_generate.setEnabled(False)
        self.lbl_progress.setText(f"Starting…")
        self.log_box.clear()

        comfy_url   = self.url_edit.text().strip() or make_icons.COMFY_URL
        output_path = self.output_edit.text().strip() or str(make_icons.COMFY_OUTPUT)

        self._worker = IconWorker(
            selected, comfy_url, output_path,
            num_candidates=self.candidates_spin.value(),
            padding_pct=self.padding_spin.value(),
            corner_radius_pct=self.radius_spin.value(),
        )
        self._worker.log_line.connect(self._log)
        self._worker.progress.connect(self._on_progress)
        self._worker.request_pick.connect(self._on_request_pick)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()


def main():
    from pathlib import Path

    # Own taskbar identity so Windows doesn't group us under python.exe.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IconMaker.App.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = base / "app_icon.ico"
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    app.setWindowIcon(icon)
    window = IconMakerApp()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
