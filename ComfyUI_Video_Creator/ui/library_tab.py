"""Library tab: browse finished videos (the Output folder by default),
play them, delete them, send one back to the Extend tab, and see the
prompt + settings that produced each one (from the prompt history)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

import workflow_tools
from config import ConfigManager
from file_ops import archive_paths, delete_paths, thumbnail_caches
from media_tools import extract_embedded_prompt, probe
from ui.prompt_history import describe_timing, find_entry_for_result, format_entry
from ui.styles import COLORS
from ui.widgets import MediaBrowser, NoScrollComboBox
from workflow_folders import apply_sort, folder_rel, library_workflow_folders, plan_sort

SCOPE_ALL = "*all"        # every video under the Library folder, workflow folders included
SCOPE_LOOSE = "*loose"    # only the videos lying directly in the Library folder
SCOPE_PREFIX = "wf:"      # "wf:<folder>" = one workflow's folder


def _entry_from_embedded(prompt_data: dict) -> dict:
    """Build a history-entry-shaped dict (same shape `format_entry` expects)
    out of the API prompt VHS_VideoCombine embedded in the mp4 itself, for
    files with no matching history entry — a reused-settings retry (history
    is deliberately skipped for those) or a video made/renamed elsewhere."""
    a = workflow_tools.analyze(prompt_data)
    positive = negative = ""
    for pf in a.prompts:
        if pf.negative:
            negative = negative or pf.text
        else:
            positive = positive or pf.text
    seed = None
    if a.seed_fields:
        nid, key = a.seed_fields[0]
        try:
            seed = int(prompt_data[nid]["inputs"][key])
        except (KeyError, TypeError, ValueError):
            seed = None
    loras = [
        {"node": slot.node_id, "key": slot.name_key, "label": slot.label,
         "name": slot.name, "strengths": slot.strengths}
        for slot in a.loras if slot.name and slot.name.lower() != "none"
    ]
    settings = {
        "workflow": "(read from this file's embedded metadata)",
        "mode": "?",
        "seed": seed,
        "length": {"label": a.length_field.label, "value": a.length_field.value} if a.length_field else None,
        "steps": a.sampler_steps[0] if a.sampler_steps else None,
        "megapixels": a.mp_fields[0].value if a.mp_fields else None,
        "loras": loras,
        "video_input_mode": None,
        "extend_stitch": None,
        # A graph with no image or video loader can only have been a
        # text-to-video run — the same test the Text → Video tab applies.
        "text_to_video": not (a.accepts_image or a.accepts_video),
    }
    return {"positive": positive, "negative": negative or None, "settings": settings}


def _fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024:.0f} KB"


def _fmt_dur(seconds: float) -> str:
    s = int(round(seconds))
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}" if m else f"{seconds:.1f}s"


class LibraryTab(QWidget):
    play_requested = pyqtSignal(list)        # list[str] playlist
    send_to_extend = pyqtSignal(object)      # Path
    reuse_requested = pyqtSignal(object, object, object)  # result video Path, workflow Path, history entry dict
    folder_changed = pyqtSignal(str)
    files_moved = pyqtSignal()               # videos were rearranged on disk (Sort into workflow folders)

    DATE_MODES = [("all", "All dates"), ("year", "Year"), ("month", "Month"), ("day", "Day")]

    def __init__(self, config: ConfigManager, ffmpeg_getter, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._ffmpeg_getter = ffmpeg_getter
        self._detail_hit: tuple[Path, dict] | None = None
        self._active_rel = ""                 # folder of the workflow selected on the active tab
        self._shown: tuple[str, bool] | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        split = QSplitter(Qt.Orientation.Horizontal)

        self.browser = MediaBrowser(
            "video", self.effective_folder(), config.get("library_sort", "Newest First"),
            ffmpeg_getter, multi=True, last_frame=False, title="Library", show_delete=False,
            hint="Finished videos — Output folder unless you pick another one",
        )
        self.browser.selection_changed.connect(lambda _p: self._update_details())
        self.browser.activated.connect(lambda p: self.play_requested.emit([str(p)]))
        self.browser.folder_changed.connect(self._on_folder_changed)
        self.browser.sort_changed.connect(lambda s: (config.set("library_sort", s), config.save()))
        self.browser.loaded.connect(self._on_loaded)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        scope_row = QHBoxLayout()
        scope_row.setSpacing(6)
        scope_lbl = QLabel("Workflow:")
        scope_lbl.setStyleSheet(f"color: {COLORS['accent_hover']}; font-weight: bold;")
        scope_row.addWidget(scope_lbl)
        self._scope_combo = NoScrollComboBox()
        self._scope_combo.setMinimumWidth(320)
        self._scope_combo.setToolTip(
            "Each workflow saves its videos in its own folder under the Library folder.\n"
            "Pick one workflow's videos, every workflow together, or the loose videos that "
            "were saved before the folders existed.")
        self._scope_combo.activated.connect(self._on_scope_picked)
        scope_row.addWidget(self._scope_combo, stretch=1)
        self._follow_chk = QCheckBox("Follow the active workflow")
        self._follow_chk.setToolTip(
            "On: switching workflow on the Image / Video / Text tab switches this list to that "
            "workflow's videos, so you can compare against what it already made.\n"
            "Picking something else from the list turns this off.")
        self._follow_chk.setChecked(bool(config.get("library_follow", True)))
        self._follow_chk.toggled.connect(self._on_follow_toggled)
        scope_row.addWidget(self._follow_chk)
        left_lay.addLayout(scope_row)

        filt_row = QHBoxLayout()
        filt_row.setSpacing(6)
        filt_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by filename…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        filt_row.addWidget(self._search, stretch=1)
        filt_row.addWidget(QLabel("Date:"))
        self._date_mode = NoScrollComboBox()
        for key, label in self.DATE_MODES:
            self._date_mode.addItem(label, key)
        self._date_mode.setFixedWidth(100)
        self._date_mode.currentIndexChanged.connect(self._on_date_mode_changed)
        filt_row.addWidget(self._date_mode)
        self._date_value = NoScrollComboBox()
        self._date_value.setMinimumWidth(160)
        self._date_value.setEnabled(False)
        self._date_value.addItem("—", "")
        self._date_value.currentIndexChanged.connect(lambda _i: self._apply_filter())
        filt_row.addWidget(self._date_value)
        self._filter_status = QLabel("")
        self._filter_status.setObjectName("status_dim")
        filt_row.addWidget(self._filter_status)
        left_lay.addLayout(filt_row)

        left_lay.addWidget(self.browser, stretch=1)
        split.addWidget(left)

        right = QWidget()
        right.setMinimumWidth(380)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        btn_group = QGroupBox("Actions")
        bl = QVBoxLayout(btn_group)
        bl.setSpacing(6)
        row1 = QHBoxLayout()
        play_btn = QPushButton("▶  Play")
        play_btn.setToolTip("Play the selected video(s) back-to-back")
        play_btn.clicked.connect(self._play_selected)
        row1.addWidget(play_btn)
        extend_btn = QPushButton("🎬  Send to Extend")
        extend_btn.setToolTip("Use this video as the source on the Video → Extend tab")
        extend_btn.clicked.connect(self._send_selected)
        row1.addWidget(extend_btn)
        self._reuse_btn = QPushButton("🔁 Reuse Settings")
        self._reuse_btn.setToolTip(
            "Reload this run's prompt, LoRAs, seed, steps and source image/video into the matching "
            "tab so you can tweak it and try again")
        self._reuse_btn.setEnabled(False)
        self._reuse_btn.clicked.connect(self._reuse_selected)
        row1.addWidget(self._reuse_btn)
        bl.addLayout(row1)
        row2 = QHBoxLayout()
        open_btn = QPushButton("📂 Open Folder")
        open_btn.setObjectName("secondary_btn")
        open_btn.clicked.connect(self._open_folder)
        row2.addWidget(open_btn)
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setObjectName("secondary_btn")
        refresh_btn.clicked.connect(self.refresh)
        row2.addWidget(refresh_btn)
        archive_btn = QPushButton("📦 Archive")
        archive_btn.setObjectName("secondary_btn")
        archive_btn.setToolTip("Move the selected video(s) to the Archive folder (set in Settings)")
        archive_btn.clicked.connect(self._archive_selected)
        row2.addWidget(archive_btn)
        del_btn = QPushButton("🗑 Delete")
        del_btn.setObjectName("cancel_btn")
        del_btn.setToolTip("Delete the selected video file(s) — goes to the Recycle Bin (Del)")
        del_btn.clicked.connect(self._delete_selected)
        row2.addWidget(del_btn)
        row2.addStretch()
        bl.addLayout(row2)
        row3 = QHBoxLayout()
        sort_btn = QPushButton("🗂 Sort into workflow folders…")
        sort_btn.setObjectName("secondary_btn")
        sort_btn.setToolTip(
            "Move the videos lying loose in the Library folder into the folder of the workflow "
            "that made them (found through each workflow's prompt history). Shows what will move first.")
        sort_btn.clicked.connect(self._sort_into_folders)
        row3.addWidget(sort_btn)
        row3.addStretch()
        bl.addLayout(row3)
        rl.addWidget(btn_group)

        info_group = QGroupBox("Selected video")
        il = QVBoxLayout(info_group)
        il.setSpacing(4)
        self._info = QLabel("Nothing selected")
        self._info.setWordWrap(True)
        self._info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        il.addWidget(self._info)
        rl.addWidget(info_group)

        made_group = QGroupBox("Produced by")
        ml = QVBoxLayout(made_group)
        ml.setSpacing(4)
        self._made_lbl = QLabel("")
        self._made_lbl.setWordWrap(True)
        self._made_lbl.setObjectName("status_dim")
        ml.addWidget(self._made_lbl)
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setPlaceholderText(
            "Select one video to see the prompt, LoRAs, seed and length it was generated with "
            "(from the workflow's prompt history).")
        ml.addWidget(self._details, stretch=1)
        rl.addWidget(made_group, stretch=1)

        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([1000, 520])
        lay.addWidget(split)

    # ------------------------------------------------------------------ #

    def effective_folder(self) -> str:
        return (self._cfg.get("library_dir", "") or "").strip() or (self._cfg.get("output_dir", "") or "").strip()

    def set_folder(self, folder: str):
        # The Library folder is the root; what the grid lists is the picked scope inside it.
        self._rebuild_scopes()
        self._apply_scope(force=True)

    def refresh(self):
        self._rebuild_scopes()
        self._apply_scope(force=True)

    def shutdown(self):
        self.browser.shutdown()

    def _on_folder_changed(self, folder: str):
        self._cfg.set("library_dir", folder)
        self._cfg.save()
        self.folder_changed.emit(folder)
        self._rebuild_scopes()
        self._apply_scope(force=True)

    # -- which workflow's videos the grid lists ---------------------------- #

    def follow_workflow(self, workflow_rel: str):
        """A tab's workflow changed: list that workflow's videos (when following)."""
        self._active_rel = folder_rel(workflow_rel)
        if self._follow_chk.isChecked() and self._active_rel:
            self._rebuild_scopes(select=SCOPE_PREFIX + self._active_rel)
            self._apply_scope()

    def _rebuild_scopes(self, select: str | None = None):
        """Fill the Workflow dropdown: All, Unsorted, then every folder that holds
        videos — plus the active workflow's, which has none until its first run."""
        keep = select if select is not None else self._scope_combo.currentData()
        root = self.effective_folder()
        folders = library_workflow_folders(root) if root and Path(root).is_dir() else []
        if self._active_rel and self._active_rel not in folders:
            folders.append(self._active_rel)
        self._scope_combo.blockSignals(True)
        self._scope_combo.clear()
        self._scope_combo.addItem("All workflows", SCOPE_ALL)
        self._scope_combo.addItem("Unsorted — loose in the Library folder", SCOPE_LOOSE)
        for f in sorted(folders, key=str.lower):
            self._scope_combo.addItem(f, SCOPE_PREFIX + f)
        idx = self._scope_combo.findData(keep) if keep else -1
        self._scope_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._scope_combo.blockSignals(False)

    def _scope_target(self) -> tuple[str, bool]:
        """(folder to list, include subfolders)"""
        root = self.effective_folder()
        scope = self._scope_combo.currentData() or SCOPE_ALL
        if scope == SCOPE_ALL:
            return root, True
        if scope == SCOPE_LOOSE:
            return root, False
        return str(Path(root) / scope[len(SCOPE_PREFIX):]) if root else "", False

    def _apply_scope(self, force: bool = False):
        target = self._scope_target()
        if target == self._shown and not force:
            return
        self._shown = target
        scope = self._scope_combo.currentData() or ""
        self.browser.missing_text = ("No videos yet for this workflow"
                                     if scope.startswith(SCOPE_PREFIX) else None)
        self.browser.set_folder(*target)

    def _on_scope_picked(self, _index: int):
        """The user chose from the dropdown: following stops unless they picked the active workflow."""
        picked = self._scope_combo.currentData()
        if picked != SCOPE_PREFIX + self._active_rel and self._follow_chk.isChecked():
            self._follow_chk.blockSignals(True)
            self._follow_chk.setChecked(False)
            self._follow_chk.blockSignals(False)
            self._cfg.set("library_follow", False)
            self._cfg.save()
        self._apply_scope()

    def _on_follow_toggled(self, on: bool):
        self._cfg.set("library_follow", bool(on))
        self._cfg.save()
        if on:
            self.follow_workflow(self._active_rel)

    def _sort_into_folders(self):
        root = self.effective_folder()
        wf_dir = (self._cfg.get("workflow_dir", "") or "").strip()
        if not root or not Path(root).is_dir():
            QMessageBox.information(self, "Sort into workflow folders", "Set the Library / Output folder first.")
            return
        plan = plan_sort(wf_dir, root)
        if not plan.moves:
            QMessageBox.information(
                self, "Sort into workflow folders",
                "Nothing to move: no video lying loose in the Library folder is named in a "
                f"workflow's prompt history.\n\n{len(plan.unmatched)} loose video(s) have no history entry.")
            return
        counts = plan.per_folder()
        box = QMessageBox(self)
        box.setWindowTitle("Sort into workflow folders")
        box.setIcon(QMessageBox.Icon.Question)
        extra = []
        if plan.unmatched:
            extra.append(f"{len(plan.unmatched)} loose video(s) are not named in any prompt history and stay where they are.")
        if plan.ambiguous:
            extra.append(f"{len(plan.ambiguous)} are claimed by two workflows and stay where they are.")
        if plan.clashes:
            extra.append(f"{len(plan.clashes)} would overwrite a file already in the target folder and stay where they are.")
        box.setText(f"Move {len(plan.moves)} video(s) into {len(counts)} workflow folder(s) under\n{root}?")
        box.setInformativeText("\n".join(extra + ["Each video goes to the folder of the workflow whose "
                                                  "prompt history names it. A list of every move is saved "
                                                  "in the Library folder."]))
        detail = [f"{n:>4}  →  {folder}" for folder, n in counts.items()]
        if plan.unmatched:
            detail += ["", "Staying (no history entry):"] + [f"   {p.name}" for p in plan.unmatched[:200]]
        box.setDetailedText("\n".join(detail))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.browser.deleting.emit([src for src, _dst in plan.moves])     # close any player holding them
        moved, errors, manifest = apply_sort(plan)
        self.refresh()
        self.files_moved.emit()
        msg = f"Moved {moved} video(s) into workflow folders."
        if manifest:
            msg += f"\n\nList of moves: {manifest.name}"
        if errors:
            msg += "\n\nCould not move:\n" + "\n".join(errors[:12])
        QMessageBox.information(self, "Sort into workflow folders", msg)

    # ------------------------------------------------------------------ #

    def _selected(self) -> list[Path]:
        return self.browser.selected_paths()

    def _play_selected(self):
        paths = self._selected()
        if paths:
            self.play_requested.emit([str(p) for p in paths])

    def _send_selected(self):
        paths = self._selected()
        if paths:
            self.send_to_extend.emit(paths[0])

    def _reuse_selected(self):
        paths = self._selected()
        if len(paths) != 1 or self._detail_hit is None:
            return
        p = paths[0]
        if not p.exists():
            self._detail_hit = None
            self._reuse_btn.setEnabled(False)
            QMessageBox.information(
                self, "Reuse settings", f"{p.name} is no longer on disk — rescanning the Library.")
            self.refresh()
            return
        wf_path, entry = self._detail_hit
        self.reuse_requested.emit(p, wf_path, entry)

    def _open_folder(self):
        folder = self.browser.folder
        if folder and Path(folder).is_dir():
            os.startfile(folder)

    def _delete_selected(self):
        paths = self._selected()
        if not paths:
            return
        names = "\n".join(p.name for p in paths[:8]) + ("\n…" if len(paths) > 8 else "")
        ans = QMessageBox.question(
            self, "Delete video" + ("s" if len(paths) > 1 else ""),
            f"Send {len(paths)} file{'s' if len(paths) > 1 else ''} to the Recycle Bin?\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.browser.deleting.emit(paths)
        root = Path(self.browser.folder) if self.browser.folder else None
        caches: list[Path] = []
        for p in paths:
            caches += thumbnail_caches(p, root)
        _n, errors, _recycled = delete_paths(paths + caches)
        if errors:
            QMessageBox.warning(self, "Delete", "Some files could not be deleted:\n" + "\n".join(errors))
        self.refresh()

    def _archive_selected(self):
        paths = self._selected()
        if not paths:
            return
        archive_dir = (self._cfg.get("archive_dir", "") or "").strip()
        if not archive_dir:
            QMessageBox.information(
                self, "Archive", "Set an Archive folder in Settings first (Folders → Archive).")
            return
        names = "\n".join(p.name for p in paths[:8]) + ("\n…" if len(paths) > 8 else "")
        ans = QMessageBox.question(
            self, "Archive video" + ("s" if len(paths) > 1 else ""),
            f"Move {len(paths)} file{'s' if len(paths) > 1 else ''} to the archive folder?\n\n"
            f"{names}\n\n→ {archive_dir}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.browser.deleting.emit(paths)   # close any player holding these files before they move
        root = Path(self.browser.folder) if self.browser.folder else None
        caches: list[Path] = []
        for p in paths:
            caches += thumbnail_caches(p, root)
        _moved, errors = archive_paths(paths, Path(archive_dir))
        if caches:
            delete_paths(caches)            # purge the cache so the grid never shows a stale tile
        if errors:
            QMessageBox.warning(self, "Archive", "Some files could not be archived:\n" + "\n".join(errors))
        gone = [p for p in paths if not p.exists()]
        if gone:
            self.browser.deleted.emit(gone)
        self.refresh()

    # ------------------------------------------------------------------ #

    def _on_loaded(self, _n: int):
        self._rebuild_date_values()
        self._apply_filter()

    @staticmethod
    def _date_key(ts: float, mode: str) -> str:
        d = datetime.fromtimestamp(ts)
        return {"year": d.strftime("%Y"), "month": d.strftime("%Y-%m"), "day": d.strftime("%Y-%m-%d")}.get(mode, "")

    @staticmethod
    def _item_ctime(item) -> float:
        try:
            return Path(item.data(Qt.ItemDataRole.UserRole)).stat().st_ctime
        except OSError:
            return 0.0

    def _rebuild_date_values(self):
        mode = self._date_mode.currentData()
        prev = self._date_value.currentData()
        grid = self.browser.grid
        self._date_value.blockSignals(True)
        self._date_value.clear()
        if mode == "all":
            self._date_value.setEnabled(False)
            self._date_value.addItem("—", "")
        else:
            self._date_value.setEnabled(True)
            counts: dict[str, int] = {}
            for i in range(grid.count()):
                k = self._date_key(self._item_ctime(grid.item(i)), mode)
                if k:
                    counts[k] = counts.get(k, 0) + 1
            for k in sorted(counts, reverse=True):
                self._date_value.addItem(f"{k}  ({counts[k]})", k)
            idx = self._date_value.findData(prev) if prev else -1
            self._date_value.setCurrentIndex(idx if idx >= 0 else 0)
        self._date_value.blockSignals(False)

    def _on_date_mode_changed(self, _i):
        self._rebuild_date_values()
        self._apply_filter()

    def _apply_filter(self, *_):
        query = self._search.text().strip().lower()
        mode = self._date_mode.currentData()
        dval = self._date_value.currentData() if mode and mode != "all" else ""
        grid = self.browser.grid
        shown = 0
        for i in range(grid.count()):
            item = grid.item(i)
            ok = (not query or query in item.text().lower())
            if ok and dval:
                ok = self._date_key(self._item_ctime(item), mode) == dval
            item.setHidden(not ok)
            if ok:
                shown += 1
        total = grid.count()
        self._filter_status.setText("" if shown == total else f"{shown} of {total} shown")

    # ------------------------------------------------------------------ #

    def _update_details(self):
        paths = self._selected()
        if not paths:
            self._info.setText("Nothing selected")
            self._made_lbl.setText("")
            self._details.setPlainText("")
            self._detail_hit = None
            self._reuse_btn.setEnabled(False)
            return
        if len(paths) > 1:
            total = 0
            for p in paths:
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
            self._info.setText(f"{len(paths)} videos selected  ·  {_fmt_size(total)}")
            self._made_lbl.setText("")
            self._details.setPlainText("")
            self._detail_hit = None
            self._reuse_btn.setEnabled(False)
            return
        p = paths[0]
        try:
            size = _fmt_size(p.stat().st_size)
        except OSError:
            size = "?"
        props = probe(self._ffmpeg_getter(), p)
        bits = [f"<b>{p.name}</b>", size]
        if props.width and props.height:
            bits.append(f"{props.width}×{props.height}")
        if props.fps:
            bits.append(f"{props.fps:g} fps")
        if props.duration:
            bits.append(_fmt_dur(props.duration))
        bits.append("audio" if props.has_audio else "no audio")
        self._info.setText("  ·  ".join(bits))

        wf_dir = Path((self._cfg.get("workflow_dir", "") or "").strip())
        hit = find_entry_for_result(wf_dir, p.name) if str(wf_dir) else None
        self._detail_hit = hit
        self._reuse_btn.setEnabled(hit is not None)
        if hit is None:
            prompt_data = extract_embedded_prompt(p)
            if prompt_data:
                self._made_lbl.setText(
                    "No history entry — showing the prompt embedded in this video's own metadata.")
                self._details.setPlainText(format_entry(_entry_from_embedded(prompt_data)))
                self._details.setStyleSheet(f"color: {COLORS['fg_primary']};")
            else:
                self._made_lbl.setText(
                    "No history entry names this file, and no ComfyUI metadata found in it "
                    "(older run, renamed, or made elsewhere).")
                self._details.setPlainText("")
            return
        wf_path, entry = hit
        try:
            rel = wf_path.relative_to(wf_dir).as_posix()
        except ValueError:
            rel = wf_path.name
        made = f"{rel}   ·   {entry.get('timestamp', '?')}"
        if describe_timing(entry):
            made += f"   ·   ⏱ generated in {describe_timing(entry)}"
        self._made_lbl.setText(made)
        self._details.setPlainText(format_entry(entry, result=p.name))
        self._details.setStyleSheet(f"color: {COLORS['fg_primary']};")
