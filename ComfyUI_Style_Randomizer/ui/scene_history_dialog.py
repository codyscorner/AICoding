from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTreeWidget,
    QTreeWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QMessageBox, QWidget,
)

import scene_history
from ui.styles import COLORS

NO_IDEA = "(no idea saved)"


def _snip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


class SceneHistoryDialog(QDialog):
    """Every Scenario that was generated from, with the Ideas tried on it listed
    underneath. Find one by words, then *Use this* loads the Scenario + Idea back
    into the Prompt editor (a Scenario on its own loads its newest Idea)."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = path
        self.chosen: dict | None = None      # {"scenario", "idea", "count"} for the editor
        self.setWindowTitle("Scenario history")
        self.setMinimumSize(780, 600)
        self.resize(920, 700)
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(8)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter - type any words from a scenario, idea or note…")
        self._filter.textChanged.connect(self._refresh)
        v.addWidget(self._filter)

        split = QSplitter(Qt.Orientation.Vertical)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Scenario  /  Ideas tried with it", "Last used", "Uses"])
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setColumnWidth(0, 560)
        self._tree.setColumnWidth(1, 130)
        self._tree.currentItemChanged.connect(lambda *_: self._show_current())
        self._tree.itemDoubleClicked.connect(lambda *_: self._use())
        split.addWidget(self._tree)

        dw = QWidget()
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        self._meta = QLabel("")
        self._meta.setObjectName("subtitle")
        self._meta.setWordWrap(True)
        dl.addWidget(self._meta)
        self._scenario_lbl = QLabel("Scenario")
        self._idea_lbl = QLabel("Idea")
        for lbl, attr in ((self._scenario_lbl, "_scenario_view"), (self._idea_lbl, "_idea_view")):
            lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
            dl.addWidget(lbl)
            box = QPlainTextEdit()
            box.setReadOnly(True)
            setattr(self, attr, box)
            dl.addWidget(box, stretch=1)
        split.addWidget(dw)
        split.setSizes([260, 380])
        v.addWidget(split, stretch=1)

        row = QHBoxLayout()
        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("subtitle")
        row.addWidget(self._count_lbl)
        row.addStretch()
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("cancel_btn")
        self._delete_btn.setMinimumWidth(170)
        self._delete_btn.clicked.connect(self._delete)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("cancel_btn")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.reject)
        self._use_btn = QPushButton("Use this")
        self._use_btn.setMinimumWidth(110)
        self._use_btn.clicked.connect(self._use)
        row.addWidget(self._delete_btn)
        row.addWidget(close_btn)
        row.addWidget(self._use_btn)
        v.addLayout(row)

    # ------------------------------------------------------------------ #
    def _refresh(self):
        all_entries = scene_history.load(self._path)
        shown = scene_history.search(all_entries, self._filter.text())
        groups = scene_history.group_by_scenario(shown)
        filtering = bool(self._filter.text().strip())

        bold = QFont(self.font())
        bold.setBold(True)
        self._tree.blockSignals(True)
        self._tree.clear()
        for g in groups:
            title = g["note"] or _snip(g["scenario"], 95) or "(no scenario - idea only)"
            n = len(g["entries"])
            top = QTreeWidgetItem([f"{title}   [{n} idea{'s' if n != 1 else ''}]", g["time"], f"x{g['uses']}"])
            top.setFont(0, bold)
            top.setData(0, Qt.ItemDataRole.UserRole, ("group", g))
            for e in g["entries"]:
                idea = _snip(e.get("idea", ""), 95) or NO_IDEA
                child = QTreeWidgetItem([idea, e.get("time", ""), f"x{int(e.get('uses', 1))}"])
                child.setData(0, Qt.ItemDataRole.UserRole, ("entry", e))
                top.addChild(child)
            self._tree.addTopLevelItem(top)
            top.setExpanded(filtering or len(groups) <= 3)
        self._tree.blockSignals(False)

        total_groups = len(scene_history.group_by_scenario(all_entries))
        self._count_lbl.setText(
            f"{len(groups)} of {total_groups} scenarios shown" if filtering
            else f"{total_groups} scenario{'s' if total_groups != 1 else ''}, {len(all_entries)} idea{'s' if len(all_entries) != 1 else ''} saved")
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        self._show_current()

    def _selected(self):
        item = self._tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _show_current(self):
        sel = self._selected()
        self._use_btn.setEnabled(sel is not None)
        self._delete_btn.setEnabled(sel is not None)
        if sel is None:
            self._meta.setText("Nothing saved yet - every Generate click is recorded here." if not self._filter.text().strip()
                               else "No match.")
            self._scenario_view.setPlainText("")
            self._idea_view.setPlainText("")
            self._delete_btn.setText("Delete")
            return
        kind, data = sel
        if kind == "group":
            newest = data["entries"][0]
            n = len(data["entries"])
            self._meta.setText(f"Scenario with {n} idea{'s' if n != 1 else ''} tried on it, used {data['uses']}x in total. "
                               f"Use this loads it with its newest idea (shown below) - open it to pick another.")
            self._scenario_view.setPlainText(data["scenario"])
            self._idea_lbl.setText("Newest idea")
            self._idea_view.setPlainText(newest.get("idea", ""))
            self._delete_btn.setText(f"Delete scenario + {n} idea{'s' if n != 1 else ''}")
        else:
            bits = [data.get("time", "")]
            if data.get("provider"):
                bits.append(f"{data['provider']} / {data.get('model', '')}")
            if data.get("count"):
                bits.append(f"{data['count']} prompts")
            bits.append(f"used {int(data.get('uses', 1))}x")
            self._meta.setText("   ·   ".join(b for b in bits if b))
            self._scenario_view.setPlainText(data.get("scenario", ""))
            self._idea_lbl.setText("Idea")
            self._idea_view.setPlainText(data.get("idea", ""))
            self._delete_btn.setText("Delete this idea")

    def _use(self):
        sel = self._selected()
        if sel is None:
            return
        kind, data = sel
        e = data["entries"][0] if kind == "group" else data
        self.chosen = {"scenario": e.get("scenario", ""), "idea": e.get("idea", ""), "count": e.get("count", 0)}
        self.accept()

    def _delete(self):
        sel = self._selected()
        if sel is None:
            return
        kind, data = sel
        if kind == "group":
            n = len(data["entries"])
            question = f"Delete this scenario and the {n} idea{'s' if n != 1 else ''} tied to it?"
        else:
            question = "Delete this idea from the history?"
        if QMessageBox.question(
                self, "Delete", question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if kind == "group":
            scene_history.delete_scenario(self._path, data["scenario"])
        else:
            scene_history.delete(self._path, data["id"])
        self._refresh()
