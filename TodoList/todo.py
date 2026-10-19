"""
TodoList — a simple desktop todo app.

Python 3.x + PyQt6. Tasks persist to todos.json next to the script (or the
frozen EXE), so your list survives restarts. Nothing is ever erased by accident:
finished/removed tasks move to History (with their closing comment) and are only
destroyed by "Delete forever" there.
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QLineEdit, QVBoxLayout, QHBoxLayout, QFrame,
    QMessageBox, QInputDialog, QScrollArea, QDialog, QPlainTextEdit,
    QDialogButtonBox, QButtonGroup, QSizePolicy,
)
from PyQt6.QtGui import QIcon, QShortcut, QKeySequence
from PyQt6.QtCore import Qt

APP_VERSION = "1.1.1"

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
    """Read the task list from disk. A missing file gives []. A corrupt file is
    copied to todos.json.bak-<time> first, so it is never silently overwritten."""
    if not DATA_FILE.exists():
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        if not isinstance(tasks, list):
            raise ValueError("todos.json is not a list")
    except (json.JSONDecodeError, ValueError, OSError):
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(DATA_FILE, DATA_FILE.with_name(f"todos.json.bak-{stamp}"))
        except OSError:
            pass
        return []
    tasks = [t for t in tasks if isinstance(t, dict)]
    # Hand-edited or very old files may lack ids; every task needs a unique one.
    used = {t["id"] for t in tasks if isinstance(t.get("id"), int)}
    nxt = max(used, default=0) + 1
    for t in tasks:
        if not isinstance(t.get("id"), int):
            t["id"] = nxt
            nxt += 1
    return tasks


def save_tasks(tasks: list) -> None:
    """Write the task list atomically: a crash mid-write leaves the previous
    file intact instead of a truncated one."""
    tmp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)
        os.replace(tmp, DATA_FILE)
    except OSError as e:
        QMessageBox.warning(None, "Save Failed", f"Could not save tasks:\n{e}")


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %I:%M %p")
    except (ValueError, TypeError):
        return ""


# ── Styling ─────────────────────────────────────────────────────────────────

COLORS = {
    "bg":         "#0a1428",
    "bg_mid":     "#0e1d38",
    "card":       "#132a4d",
    "card_done":  "#0f2140",
    "fg":         "#e3ecff",
    "fg_dim":     "#8ea3c8",
    "accent":     "#2f6fed",
    "accent_hi":  "#4d88ff",
    "accent2":    "#7fb3ff",
    "ok":         "#2ecc71",
    "danger":     "#ff8a80",
    "border":     "#2a5298",
    "line":       "#1d3a6b",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['fg']};
    font-family: "Segoe UI";
}}
QLabel {{ background: transparent; }}
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
QPushButton:hover {{ background-color: {COLORS['accent_hi']}; }}
QPushButton:disabled {{ background-color: #1b2a47; color: #5d7094; }}
QPushButton#ghost {{
    background-color: transparent;
    color: {COLORS['fg_dim']};
    font-size: 9pt;
    font-weight: normal;
    padding: 4px 6px;
    border: 1px solid {COLORS['line']};
    border-radius: 4px;
}}
QPushButton#ghost:hover {{ background-color: {COLORS['bg_mid']}; color: {COLORS['fg']}; }}
QPushButton#icon_btn {{
    background-color: transparent;
    color: {COLORS['fg_dim']};
    font-family: "Segoe UI Symbol";
    font-size: 12pt;
    font-weight: normal;
    padding: 0px;
    border: 1px solid {COLORS['line']};
    border-radius: 4px;
}}
QPushButton#icon_btn:hover {{ background-color: {COLORS['bg_mid']}; color: {COLORS['fg']}; }}
QPushButton#danger_ghost {{
    background-color: transparent;
    color: {COLORS['danger']};
    font-family: "Segoe UI Symbol";
    font-size: 11pt;
    font-weight: normal;
    padding: 0px;
    border: 1px solid #5a2f3a;
    border-radius: 4px;
}}
QPushButton#danger_ghost:hover {{ background-color: #3a1d2a; }}
QPushButton#tab {{
    background-color: transparent;
    color: {COLORS['fg_dim']};
    font-size: 10pt;
    padding: 5px 14px;
    border: 1px solid {COLORS['line']};
    border-radius: 12px;
}}
QPushButton#tab:hover {{ color: {COLORS['fg']}; }}
QPushButton#tab:checked {{
    background-color: {COLORS['accent']};
    color: #ffffff;
    border: 1px solid {COLORS['accent']};
}}
QPushButton#check {{
    background-color: transparent;
    color: {COLORS['accent2']};
    font-family: "Segoe UI Symbol";
    font-size: 19pt;
    font-weight: normal;
    padding: 0px;
    border: none;
}}
QPushButton#check:hover {{ color: #ffffff; }}
QPushButton#check_done {{
    background-color: transparent;
    color: {COLORS['ok']};
    font-family: "Segoe UI Symbol";
    font-size: 19pt;
    font-weight: normal;
    padding: 0px;
    border: none;
}}
QPushButton#check_done:hover {{ color: #7dffb0; }}
QLineEdit, QPlainTextEdit {{
    background-color: {COLORS['card']};
    color: {COLORS['fg']};
    font-size: 11pt;
    padding: 8px 10px;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    selection-background-color: {COLORS['accent']};
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
QScrollArea#scroll {{ border: none; background: transparent; }}
QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QWidget#list_content {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['line']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {COLORS['border']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QFrame#task_card {{
    background-color: {COLORS['card']};
    border: 1px solid {COLORS['line']};
    border-left: 4px solid {COLORS['accent']};
    border-radius: 6px;
}}
QFrame#task_card_done {{
    background-color: {COLORS['card_done']};
    border: 1px solid {COLORS['line']};
    border-left: 4px solid {COLORS['ok']};
    border-radius: 6px;
}}
QFrame#task_card_gone {{
    background-color: {COLORS['card_done']};
    border: 1px solid {COLORS['line']};
    border-left: 4px solid {COLORS['fg_dim']};
    border-radius: 6px;
}}
QLabel#task_text {{
    font-size: 11pt;
    font-weight: 600;
}}
QLabel#task_text_done {{
    font-size: 11pt;
    font-weight: normal;
    color: {COLORS['fg_dim']};
}}
QLabel#task_comment {{
    font-size: 10pt;
    font-style: italic;
    color: {COLORS['accent2']};
}}
QLabel#task_meta {{
    font-size: 8pt;
    color: {COLORS['fg_dim']};
}}
"""


# ── Closing-comment dialog ──────────────────────────────────────────────────

class CompleteDialog(QDialog):
    """Asks for an optional closing comment when a task is completed.
    Complete with an empty box is fine; Cancel leaves the task open."""

    def __init__(self, parent, task_text: str, previous: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Complete task")
        self.setMinimumWidth(420)

        heading = QLabel(task_text)
        heading.setObjectName("task_text")
        heading.setWordWrap(True)
        hint = QLabel("Closing comment (optional)")
        hint.setObjectName("task_meta")

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("How did it go? Anything worth remembering…")
        self.edit.setPlainText(previous)
        self.edit.setFixedHeight(100)

        buttons = QDialogButtonBox()
        done_btn = buttons.addButton("Complete", QDialogButtonBox.ButtonRole.AcceptRole)
        done_btn.setDefault(False)
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.accept)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.addWidget(heading)
        lay.addWidget(hint)
        lay.addWidget(self.edit)
        lay.addWidget(buttons)
        self.edit.setFocus()

    def comment(self) -> str:
        return self.edit.toPlainText().strip()


# ── Task row ────────────────────────────────────────────────────────────────

class TaskCard(QFrame):
    """A single todo row. In the active list: checkbox, text, edit, archive.
    In History: status glyph, text, restore, delete-forever. The text column
    takes all spare width and wraps as the window is resized."""

    def __init__(self, task: dict, history: bool, on_toggle, on_delete, on_edit,
                 on_restore, on_purge):
        super().__init__()
        self.task = task
        done = bool(task.get("done"))
        if history:
            self.setObjectName("task_card_done" if done else "task_card_gone")
        else:
            self.setObjectName("task_card_done" if done else "task_card")

        # Checkbox: bare glyph, no frame. Static (non-interactive) in History.
        self.toggle = QPushButton("☑" if done else "☐")
        self.toggle.setObjectName("check_done" if done else "check")
        self.toggle.setFixedSize(32, 32)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        if history:
            self.toggle.setText("☑" if done else "—")
            self.toggle.setEnabled(False)
            self.toggle.setToolTip("Completed" if done else "Removed without completing")
        else:
            self.toggle.setToolTip("Mark incomplete" if done else "Mark complete")
            self.toggle.clicked.connect(lambda: on_toggle(task["id"]))

        # Text + closing comment + meta
        self.text_label = QLabel(task.get("text", ""))
        self.text_label.setObjectName("task_text_done" if done else "task_text")
        self.text_label.setWordWrap(True)
        self.text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if done:
            self.text_label.setStyleSheet("text-decoration: line-through;")

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)
        text_col.addWidget(self.text_label)

        comment = (task.get("closing_comment") or "").strip()
        if done and comment:
            self.comment_label = QLabel(f"“{comment}”")
            self.comment_label.setObjectName("task_comment")
            self.comment_label.setWordWrap(True)
            self.comment_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            text_col.addWidget(self.comment_label)

        meta = f"{task.get('priority', 'Medium')} priority"
        if fmt_time(task.get("created", "")):
            meta += f"  ·  Created {fmt_time(task['created'])}"
        if done and fmt_time(task.get("completed", "")):
            meta += f"  ·  Completed {fmt_time(task['completed'])}"
        if history:
            what = "Cleared" if task.get("archived_reason") == "cleared" else "Deleted"
            if fmt_time(task.get("archived_at", "")):
                meta += f"  ·  {what} {fmt_time(task['archived_at'])}"
        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("task_meta")
        self.meta_label.setWordWrap(True)
        self.meta_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_col.addWidget(self.meta_label)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)
        root.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(text_col, 1)

        if history:
            self.restore_btn = QPushButton("↩")
            self.restore_btn.setObjectName("icon_btn")
            self.restore_btn.setFixedSize(28, 28)
            self.restore_btn.setToolTip("Restore to the active list")
            self.restore_btn.clicked.connect(lambda: on_restore(task["id"]))
            self.purge_btn = QPushButton("✕")
            self.purge_btn.setObjectName("danger_ghost")
            self.purge_btn.setFixedSize(28, 28)
            self.purge_btn.setToolTip("Delete forever")
            self.purge_btn.clicked.connect(lambda: on_purge(task["id"]))
            root.addWidget(self.restore_btn, 0, Qt.AlignmentFlag.AlignTop)
            root.addWidget(self.purge_btn, 0, Qt.AlignmentFlag.AlignTop)
        else:
            self.edit_btn = QPushButton("✎")
            self.edit_btn.setObjectName("icon_btn")
            self.edit_btn.setFixedSize(28, 28)
            self.edit_btn.setToolTip("Edit")
            self.edit_btn.clicked.connect(lambda: on_edit(task["id"]))
            self.del_btn = QPushButton("✕")
            self.del_btn.setObjectName("danger_ghost")
            self.del_btn.setFixedSize(28, 28)
            self.del_btn.setToolTip("Remove (kept in History)")
            self.del_btn.clicked.connect(lambda: on_delete(task["id"]))
            root.addWidget(self.edit_btn, 0, Qt.AlignmentFlag.AlignTop)
            root.addWidget(self.del_btn, 0, Qt.AlignmentFlag.AlignTop)


# ── Main window ─────────────────────────────────────────────────────────────

class TodoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TodoList v{APP_VERSION}")
        self.setMinimumSize(420, 520)
        self.resize(560, 720)
        self.setStyleSheet(STYLESHEET)
        self.tasks: list = load_tasks()   # every task, active and archived
        self.view = "active"              # "active" | "history"
        self._build_ui()
        self._rebuild_list()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # Header: title/count on the left, Active/History switch on the right
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("To-Do List")
        title.setObjectName("title")
        self.count_label = QLabel("")
        self.count_label.setObjectName("count")
        titles.addWidget(title)
        titles.addWidget(self.count_label)
        head.addLayout(titles, 1)

        self.btn_active = QPushButton("Active")
        self.btn_history = QPushButton("History")
        group = QButtonGroup(self)
        for b in (self.btn_active, self.btn_history):
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(b)
        self.btn_active.setChecked(True)
        self.btn_active.clicked.connect(lambda: self._set_view("active"))
        self.btn_history.clicked.connect(lambda: self._set_view("history"))
        head.addWidget(self.btn_active, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(self.btn_history, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)

        # Add-task row (hidden in History)
        self.add_row = QWidget()
        add_lay = QHBoxLayout(self.add_row)
        add_lay.setContentsMargins(0, 0, 0, 0)
        add_lay.setSpacing(8)
        self.prio_box = QComboBox()
        self.prio_box.addItems(["Low", "Medium", "High"])
        self.prio_box.setCurrentText("Medium")
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("What needs doing?  (press Enter)")
        self.add_edit.returnPressed.connect(self._add_task)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_task)
        add_lay.addWidget(self.prio_box)
        add_lay.addWidget(self.add_edit, 1)
        add_lay.addWidget(self.add_btn)
        outer.addWidget(self.add_row)

        # Clear-completed (hidden in History)
        self.clear_btn = QPushButton("Clear Completed")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setToolTip("Moves finished tasks to History — nothing is deleted")
        self.clear_btn.clicked.connect(self._clear_completed)
        outer.addWidget(self.clear_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # Task list: scrollable so cards keep their size however many there are
        self.list_content = QWidget()
        self.list_content.setObjectName("list_content")
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)   # keeps cards packed at the top

        self.scroll = QScrollArea()
        self.scroll.setObjectName("scroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.list_content)
        outer.addWidget(self.scroll, 1)

        # Empty / all-done state
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("subtitle")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.empty_label)

    # ── List rendering ─────────────────────────────────────────────────────

    def _set_view(self, view: str):
        self.view = view
        self._rebuild_list()

    def _clear_layout(self):
        # Last item is the trailing stretch; remove only the cards before it.
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _visible_tasks(self) -> list:
        if self.view == "history":
            gone = [t for t in self.tasks if t.get("archived")]
            return sorted(gone, key=lambda t: t.get("archived_at", ""), reverse=True)
        return [t for t in reversed(self.tasks) if not t.get("archived")]   # newest on top

    def _rebuild_list(self):
        history = self.view == "history"
        self._clear_layout()
        shown = self._visible_tasks()
        for task in shown:
            card = TaskCard(task, history, self._on_toggle, self._on_delete,
                            self._on_edit, self._on_restore, self._on_purge)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)

        self.add_row.setVisible(not history)
        self.clear_btn.setVisible(not history)
        archived = sum(1 for t in self.tasks if t.get("archived"))
        self.btn_history.setText(f"History ({archived})" if archived else "History")
        self._update_empty_state(shown, archived)
        self._update_count(shown)

    def _update_empty_state(self, shown: list, archived: int):
        if shown:
            self.empty_label.setText("")
            self.empty_label.hide()
            if self.view == "active" and all(t.get("done") for t in shown):
                self.empty_label.setText("All done — nice work! 🎉")
                self.empty_label.show()
            return
        if self.view == "history":
            self.empty_label.setText("History is empty — finished and removed tasks land here.")
        elif archived:
            self.empty_label.setText("Nothing to do — see History for finished tasks.")
        else:
            self.empty_label.setText("No tasks yet — add one above.")
        self.empty_label.show()

    def _update_count(self, shown: list):
        if self.view == "history":
            self.count_label.setText(f"{len(shown)} in history" if shown else "History")
            return
        done = sum(1 for t in shown if t.get("done"))
        self.count_label.setText(f"{done} of {len(shown)} completed" if shown else "0 tasks")

    # ── Actions ────────────────────────────────────────────────────────────

    def _find(self, task_id: int):
        return next((t for t in self.tasks if t.get("id") == task_id), None)

    def _commit(self):
        save_tasks(self.tasks)
        self._rebuild_list()

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
        self._commit()

    def _on_toggle(self, task_id: int):
        task = self._find(task_id)
        if not task:
            return
        if task.get("done"):
            # Re-opening keeps the old comment so completing again pre-fills it.
            task["done"] = False
            task.pop("completed", None)
        else:
            dlg = CompleteDialog(self, task.get("text", ""), task.get("closing_comment", ""))
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            task["done"] = True
            task["completed"] = datetime.now().isoformat()
            task["closing_comment"] = dlg.comment()
        self._commit()

    def _archive(self, task: dict, reason: str):
        task["archived"] = True
        task["archived_at"] = datetime.now().isoformat()
        task["archived_reason"] = reason

    def _on_delete(self, task_id: int):
        task = self._find(task_id)
        if task:
            self._archive(task, "deleted")
            self._commit()

    def _on_restore(self, task_id: int):
        task = self._find(task_id)
        if task:
            for k in ("archived", "archived_at", "archived_reason"):
                task.pop(k, None)
            self._commit()

    def _on_purge(self, task_id: int):
        task = self._find(task_id)
        if not task:
            return
        ans = QMessageBox.question(
            self, "Delete forever",
            f"Permanently delete this task and its history?\n\n{task.get('text', '')}\n\n"
            "This cannot be undone.",
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.tasks = [t for t in self.tasks if t.get("id") != task_id]
            self._commit()

    def _on_edit(self, task_id: int):
        task = self._find(task_id)
        if not task:
            return
        new_text, ok = QInputDialog.getText(
            self, "Edit task", "Task:", QLineEdit.EchoMode.Normal, task.get("text", "")
        )
        if ok and new_text.strip():
            task["text"] = new_text.strip()
            self._commit()

    def _clear_completed(self):
        finished = [t for t in self.tasks if t.get("done") and not t.get("archived")]
        if not finished:
            return
        for t in finished:
            self._archive(t, "cleared")
        self._commit()

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
