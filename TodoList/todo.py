"""
TodoList — a simple desktop todo app.

Python 3.x + PyQt6. Tasks persist to todos.json next to the script (or the
frozen EXE), so your list survives restarts.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QLineEdit, QVBoxLayout, QHBoxLayout, QFrame,
    QMessageBox, QInputDialog,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

APP_VERSION = "1.0.1"

# Own taskbar identity: without this Windows groups the window under
# python.exe and shows its icon instead of ours.
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TodoList.App.1")
except Exception:
    pass

# ── Data persistence ────────────────────────────────────────────────────────

def resource_path(name: str) -> Path:
    """Locate a bundled read-only resource: PyInstaller's unpack folder when
    frozen (--add-data lands there), else next to this script."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parent) / name


def data_dir() -> Path:
    """Where the todo data lives — next to the EXE when frozen, else the
    folder this script is in."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    base.mkdir(parents=True, exist_ok=True)
    return base


DATA_FILE = data_dir() / "todos.json"


def load_tasks() -> list:
    """Read the task list from disk. Returns [] on missing/corrupt file."""
    if not DATA_FILE.exists():
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        if not isinstance(tasks, list):
            return []
        return tasks
    except (json.JSONDecodeError, OSError):
        return []


def save_tasks(tasks: list) -> None:
    """Write the task list to disk."""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)
    except OSError as e:
        QMessageBox.warning(None, "Save Failed", f"Could not save tasks:\n{e}")


# ── Styling ─────────────────────────────────────────────────────────────────

COLORS = {
    "bg":         "#1a1a2e",
    "bg_mid":     "#16213e",
    "card":       "#0f3460",
    "card_done":  "#22304f",
    "fg":         "#e0d7ff",
    "fg_dim":     "#9a93b8",
    "accent":     "#7b2fff",
    "accent2":    "#c77dff",
    "ok":         "#2ecc71",
    "danger":     "#e74c3c",
    "border":     "#7b2fff",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['fg']};
    font-family: Helvetica;
}}
QLabel#title {{
    font-size: 20pt;
    font-weight: bold;
    color: {COLORS['accent2']};
}}
QLabel#subtitle {{
    font-size: 10pt;
    color: {COLORS['fg_dim']};
}}
QLabel#count {{
    font-size: 10pt;
    font-weight: bold;
    color: {COLORS['fg_dim']};
}}
QPushButton {{
    background-color: {COLORS['accent']};
    color: #ffffff;
    font-size: 11pt;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 8px 14px;
}}
QPushButton:hover {{ background-color: #9d4edd; }}
QPushButton:disabled {{ background-color: #333355; color: #666688; }}
QPushButton#danger {{ background-color: {COLORS['danger']}; }}
QPushButton#danger:hover {{ background-color: #ff6b5b; }}
QPushButton#ghost {{
    background-color: transparent;
    color: {COLORS['fg_dim']};
    font-size: 9pt;
    font-weight: normal;
    padding: 4px 6px;
    border: 1px solid #333355;
    border-radius: 4px;
}}
QPushButton#ghost:hover {{ background-color: {COLORS['bg_mid']}; color: {COLORS['fg']}; }}
QLineEdit {{
    background-color: {COLORS['card']};
    color: {COLORS['fg']};
    font-size: 11pt;
    padding: 8px 10px;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
}}
QComboBox {{
    background-color: {COLORS['card']};
    color: {COLORS['fg']};
    font-size: 11pt;
    padding: 7px 10px;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    min-width: 90px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_mid']};
    color: {COLORS['fg']};
    selection-background-color: {COLORS['accent']};
    border: 1px solid {COLORS['border']};
}}
QFrame#task_card {{
    background-color: {COLORS['card']};
    border: 1px solid #2a2a4a;
    border-left: 4px solid {COLORS['accent']};
    border-radius: 6px;
    padding: 6px 8px;
}}
QFrame#task_card_done {{
    background-color: {COLORS['card_done']};
    border: 1px solid #2a2a4a;
    border-left: 4px solid {COLORS['fg_dim']};
    border-radius: 6px;
    padding: 6px 8px;
}}
QLabel#task_text {{
    font-size: 11pt;
    font-weight: bold;
}}
QLabel#task_text_done {{
    font-size: 11pt;
    font-weight: normal;
    color: {COLORS['fg_dim']};
}}
QLabel#task_meta {{
    font-size: 8pt;
    color: {COLORS['fg_dim']};
}}
"""


# ── Task row ────────────────────────────────────────────────────────────────

class TaskCard(QFrame):
    """A single todo row: toggle checkbox, text, priority/created badge, edit,
    and delete. Callbacks handle state changes and persistence."""

    def __init__(self, task: dict, on_toggle, on_delete, on_edit):
        super().__init__()
        self.task = task
        self._apply_style()

        done = task.get("done", False)

        # Toggle (styled checkbox)
        self.toggle = QPushButton("✓" if done else "☐")
        self.toggle.setFixedSize(28, 28)
        self.toggle.setStyleSheet(self._toggle_style(done))
        self.toggle.setToolTip("Mark complete" if not done else "Mark incomplete")
        self.toggle.clicked.connect(lambda: on_toggle(task["id"]))

        # Text + meta
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.text_label = QLabel(task.get("text", ""))
        self.text_label.setObjectName("task_text_done" if done else "task_text")
        if done:
            self.text_label.setStyleSheet(
                f"text-decoration: line-through; color: {COLORS['fg_dim']};"
            )
        self.text_label.setWordWrap(True)

        meta = f"{task.get('priority', 'Medium')} priority"
        created = task.get("created")
        if created:
            try:
                dt = datetime.fromisoformat(created)
                meta += "  ·  " + dt.strftime("%b %d, %I:%M %p")
            except (ValueError, TypeError):
                pass
        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("task_meta")

        text_col.addWidget(self.text_label)
        text_col.addWidget(self.meta_label)

        # Edit + delete
        self.edit_btn = QPushButton("✎")
        self.edit_btn.setObjectName("ghost")
        self.edit_btn.setFixedSize(28, 28)
        self.edit_btn.setToolTip("Edit")
        self.edit_btn.clicked.connect(lambda: on_edit(task["id"]))

        self.del_btn = QPushButton("✕")
        self.del_btn.setObjectName("ghost")
        self.del_btn.setFixedSize(28, 28)
        self.del_btn.setToolTip("Delete")
        self.del_btn.setStyleSheet(
            "background-color: transparent; color: #ff8a80; font-size: 10pt; "
            "padding: 0px; border: 1px solid #4a2a2a; border-radius: 4px;"
        )
        self.del_btn.clicked.connect(lambda: on_delete(task["id"]))

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)
        root.addWidget(self.toggle)
        root.addLayout(text_col)
        root.addStretch(1)
        root.addWidget(self.edit_btn)
        root.addWidget(self.del_btn)

    def _toggle_style(self, done: bool) -> str:
        color = "#2ecc71" if done else "#7b2fff"
        return (
            "background-color: transparent; color: #ffffff; font-size: 14pt; "
            f"font-weight: bold; padding: 0px; border: 2px solid {color}; "
            "border-radius: 6px;"
        )

    def _apply_style(self):
        self.setObjectName("task_card_done" if self.task.get("done") else "task_card")


# ── Main window ─────────────────────────────────────────────────────────────

class TodoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TodoList v{APP_VERSION}")
        self.setMinimumSize(480, 640)
        self.resize(520, 700)
        self.setStyleSheet(STYLESHEET)
        self.tasks: list = load_tasks()
        self._build_ui()
        self._rebuild_list()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # Header
        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel("To-Do List")
        title.setObjectName("title")
        self.count_label = QLabel("")
        self.count_label.setObjectName("count")
        head.addWidget(title)
        head.addWidget(self.count_label)
        outer.addLayout(head)

        # Add-task row
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.prio_box = QComboBox()
        self.prio_box.addItems(["Low", "Medium", "High"])
        self.prio_box.setCurrentText("Medium")
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("What needs doing?  (press Enter)")
        self.add_edit.returnPressed.connect(self._add_task)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_task)
        add_row.addWidget(self.prio_box)
        add_row.addWidget(self.add_edit)
        add_row.addWidget(self.add_btn)
        outer.addLayout(add_row)

        # Clear-completed
        self.clear_btn = QPushButton("Clear Completed")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.clicked.connect(self._clear_completed)
        outer.addWidget(self.clear_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # Task list (newest on top)
        self.list_frame = QFrame()
        self.list_layout = QVBoxLayout(self.list_frame)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        outer.addWidget(self.list_frame)

        # Empty / all-done state
        self.empty_label = QLabel("No tasks yet — add one above.")
        self.empty_label.setObjectName("subtitle")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(1)
        outer.addWidget(self.empty_label)

    # ── List rendering ─────────────────────────────────────────────────────

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_list(self):
        self._clear_layout(self.list_layout)
        for task in reversed(self.tasks):
            card = TaskCard(task, self._on_toggle, self._on_delete, self._on_edit)
            self.list_layout.addWidget(card)
        self._update_empty_state()
        self._update_count()

    def _update_empty_state(self):
        if self.tasks and all(t.get("done") for t in self.tasks):
            self.empty_label.setText("All done — nice work! 🎉")
        else:
            self.empty_label.setText("No tasks yet — add one above.")

    def _update_count(self):
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.get("done"))
        self.count_label.setText(f"{done} of {total} completed" if total else "0 tasks")

    # ── Actions ────────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        return max((t.get("id", 0) for t in self.tasks), default=0) + 1

    def _add_task(self):
        text = self.add_edit.text().strip()
        if not text:
            return
        self.tasks.append({
            "id": self._next_id(),
            "text": text,
            "priority": self.prio_box.currentText(),
            "done": False,
            "created": datetime.now().isoformat(),
        })
        self.add_edit.clear()
        self.add_edit.setFocus()
        save_tasks(self.tasks)
        self._rebuild_list()

    def _on_toggle(self, task_id: int):
        for t in self.tasks:
            if t["id"] == task_id:
                t["done"] = not t.get("done", False)
                break
        save_tasks(self.tasks)
        self._rebuild_list()

    def _on_delete(self, task_id: int):
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        save_tasks(self.tasks)
        self._rebuild_list()

    def _on_edit(self, task_id: int):
        task = next((t for t in self.tasks if t["id"] == task_id), None)
        if not task:
            return
        new_text, ok = QInputDialog.getText(
            self, "Edit task", "Task:", QLineEdit.EchoMode.Normal, task.get("text", "")
        )
        if ok and new_text.strip():
            task["text"] = new_text.strip()
            save_tasks(self.tasks)
            self._rebuild_list()

    def _clear_completed(self):
        remaining = [t for t in self.tasks if not t.get("done")]
        removed = len(self.tasks) - len(remaining)
        if removed == 0:
            return
        ans = QMessageBox.question(
            self, "Clear Completed",
            f"Remove {removed} completed task(s)?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.tasks = remaining
        save_tasks(self.tasks)
        self._rebuild_list()

    def closeEvent(self, event):
        save_tasks(self.tasks)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    # App-level icon covers the taskbar and every dialog (edit, confirm,
    # save-failed); the window icon is set too for the title bar.
    icon_path = resource_path("app_icon.ico")
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    app.setWindowIcon(icon)
    window = TodoWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
