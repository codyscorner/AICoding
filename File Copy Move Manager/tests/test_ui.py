"""The Preview dialog and the glue code in both tabs (run headless)."""
import logging
import os
import queue
from pathlib import Path

import pytest

from copy_plan import Action
from helpers import DAY, JUNE, make_plan, tree, write


def dirs(tmp_path):
    return os.path.join(str(tmp_path), "src"), os.path.join(str(tmp_path), "dest")


def all_label_text(widget) -> str:
    from PyQt6.QtWidgets import QCheckBox, QLabel, QPushButton
    parts = [w.text() for w in widget.findChildren((QLabel, QPushButton, QCheckBox))]
    return "\n".join(parts) + "\n" + widget.windowTitle()


def drain(q: queue.Queue) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def mixed_plan(tmp_path, **opts):
    """A plan with one of each interesting outcome."""
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)                       # new
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)                       # numbered: loses the name to a/ in this copy
    write(os.path.join(src, "e", "blocked.png"), b"X" * 7)                      # numbered: a file is in the way on disk
    write(os.path.join(dest, "2025", "06", "blocked.png"), b"Y" * 9)
    write(os.path.join(src, "c", "done.png"), b"D" * 5, JUNE)                   # up to date
    write(os.path.join(dest, "2025", "06", "done.png"), b"D" * 5, JUNE)
    write(os.path.join(src, "d", "same.png"), b"S" * 5, JUNE)                   # same content, other date
    write(os.path.join(dest, "2025", "06", "same.png"), b"S" * 5, JUNE + 5 * DAY)
    return src, dest, make_plan(src, dest, **opts)


# ── spelling ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode, past, total", [("copy", "Copied", "Total Copied"), ("move", "Moved", "Total Moved")])
def test_counter_labels_are_spelled_correctly(qapp, tmp_path, mode, past, total):
    win = make_window(tmp_path)
    win._on_mode_changed(mode)
    assert win.copied_title_label.text() == f"{past}:"
    assert win._multi_tab.copied_title_label.text() == f"{total}:"
    assert "copyd" not in all_label_text(win).lower()


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_preview_dialog_has_no_made_up_words(qapp, tmp_path, mode):
    from ui.preview_dialog import PreviewDialog
    _src, _dest, plan = mixed_plan(tmp_path)
    dialog = PreviewDialog(plan, {"operation_mode": mode})
    text = all_label_text(dialog).lower()
    assert "copyd" not in text and "moveed" not in text
    assert f"to {mode}" in text


# ── the table ────────────────────────────────────────────────────────────────

def test_table_has_the_four_comparison_columns(qapp, tmp_path):
    from ui.preview_dialog import HEADERS, PreviewDialog
    for header in ("Pre-Destination Path", "Pre-Destination Date/Time",
                   "Current Destination Path", "Current Date/Time"):
        assert header in HEADERS
    _src, _dest, plan = mixed_plan(tmp_path)
    dialog = PreviewDialog(plan, {"operation_mode": "copy"})
    model = dialog.table.model()
    from PyQt6.QtCore import Qt
    assert [model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())] == HEADERS


def test_rows_show_planned_and_current_destination_side_by_side(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from ui.preview_dialog import (COL_ACTION, COL_CUR_DT, COL_CUR_PATH, COL_CUR_SIZE, COL_PRE_DT,
                                   COL_PRE_PATH, PlanTableModel, format_dt)
    _src, _dest, plan = mixed_plan(tmp_path)
    blocked = next(i for i in plan.items if i.action is Action.NUMBERED and i.cur_dest)
    model = PlanTableModel([blocked])

    def cell(col, role=Qt.ItemDataRole.DisplayRole):
        return model.data(model.index(0, col), role)

    assert cell(COL_PRE_PATH).endswith("blocked_001.png")
    assert cell(COL_PRE_DT) == format_dt(blocked.src_mtime)
    assert cell(COL_CUR_PATH).endswith("blocked.png")           # the file in the way
    assert cell(COL_CUR_SIZE) == "9.0 B"                        # its size, so a different file is obvious
    assert cell(COL_CUR_DT) == format_dt(blocked.cur_mtime)
    assert cell(COL_ACTION) == "New (numbered)"
    assert cell(COL_ACTION, Qt.ItemDataRole.DecorationRole) is not None


def newest_wins_plan(tmp_path, with_update=True):
    """Your two example rows: a newer source (update) and an older one (skipped, file is older)."""
    src, dest = dirs(tmp_path)
    if with_update:
        write(os.path.join(src, "a", "edited.png"), b"new version!", JUNE + DAY)
        write(os.path.join(dest, "2025", "06", "edited.png"), b"old", JUNE)
    write(os.path.join(src, "b", "IMG_4513-2.jpg"), b"source", JUNE)
    write(os.path.join(dest, "2025", "06", "IMG_4513-2.jpg"), b"destination copy", JUNE + 20)
    return src, dest, make_plan(src, dest, incremental=True, number_duplicates=False)


def test_update_and_older_rows_use_your_wording_and_show_both_sizes(qapp, tmp_path):
    from ui.preview_dialog import COL_ACTION, COL_CUR_SIZE, COL_SIZE, PlanTableModel, summary_lines
    _src, _dest, plan = newest_wins_plan(tmp_path)
    assert plan.counts[Action.REFRESH] == 1 and plan.counts[Action.OLDER] == 1
    model = PlanTableModel(plan.items)
    by_action = {model.data(model.index(r, COL_ACTION)): r for r in range(model.rowCount())}
    assert set(by_action) == {"Update (newer source)", "Skipped — file is older"}
    update = by_action["Update (newer source)"]
    assert model.data(model.index(update, COL_SIZE)) == "12.0 B"          # source size ...
    assert model.data(model.index(update, COL_CUR_SIZE)) == "3.0 B"       # ... next to the destination's
    text = " ".join(summary_lines(plan, "Copy"))
    assert "Update" in text and "Skipped, file is older 1" in text


def test_only_older_files_left_is_nothing_to_copy_not_a_warning(qapp, tmp_path):
    from ui.preview_dialog import PreviewDialog
    _src, _dest, plan = newest_wins_plan(tmp_path, with_update=False)
    assert plan.copy_count == 0 and plan.counts[Action.OLDER] == 1
    text = all_label_text(PreviewDialog(plan, {"operation_mode": "copy"}))
    assert "Nothing to copy — everything is already at the destination" in text
    assert "Skipped, file is older 1" in text


def test_dates_are_the_modified_date_and_the_tooltip_says_so(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from ui.preview_dialog import COL_CUR_DT, COL_PRE_DT, PlanTableModel
    _src, _dest, plan = newest_wins_plan(tmp_path)
    model = PlanTableModel(plan.items)
    for col in (COL_PRE_DT, COL_CUR_DT):
        assert "Modified date" in model.data(model.index(0, col), Qt.ItemDataRole.ToolTipRole)


def test_a_row_that_lost_its_name_inside_the_same_copy_explains_it_in_the_tooltip(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from ui.preview_dialog import COL_ACTION, COL_CUR_PATH, PlanTableModel
    _src, _dest, plan = mixed_plan(tmp_path)
    in_copy = next(i for i in plan.items if i.action is Action.NUMBERED and i.ref)
    model = PlanTableModel([in_copy])
    assert model.data(model.index(0, COL_CUR_PATH)) == "—"       # nothing on disk is in the way
    assert in_copy.ref in model.data(model.index(0, COL_ACTION), Qt.ItemDataRole.ToolTipRole)


def test_dialog_opens_on_what_needs_copying_and_can_show_the_rest(qapp, tmp_path):
    from ui.preview_dialog import PreviewDialog
    _src, _dest, plan = mixed_plan(tmp_path)
    assert plan.copy_count == 3 and plan.skipped_count == 2
    dialog = PreviewDialog(plan, {"operation_mode": "copy"})
    assert dialog.table.model().rowCount() == 3
    dialog._show_all.setChecked(True)
    assert dialog.table.model().rowCount() == 5
    dialog._show_all.setChecked(False)
    assert dialog.table.model().rowCount() == 3


def test_size_column_sorts_as_numbers_not_text(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from ui.preview_dialog import COL_SIZE, PreviewDialog
    src, dest = dirs(tmp_path)
    for n, size in enumerate((9, 100, 20)):
        write(os.path.join(src, f"d{n}", f"p{n}.png"), b"x" * size)
    dialog = PreviewDialog(make_plan(src, dest), {"operation_mode": "copy"})
    dialog.table.sortByColumn(COL_SIZE, Qt.SortOrder.AscendingOrder)
    model = dialog.table.model()
    assert [model.data(model.index(r, COL_SIZE)) for r in range(3)] == ["9.0 B", "20.0 B", "100.0 B"]


def test_sort_can_be_reversed_reset_and_survives_the_show_all_checkbox(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from ui.preview_dialog import COL_NAME, COL_SIZE, PreviewDialog
    src, dest = dirs(tmp_path)
    for n, size in enumerate((30, 10, 20)):
        write(os.path.join(src, f"d{n}", f"p{n}.png"), b"x" * size)
    write(os.path.join(src, "d9", "big_done.png"), b"y" * 500, JUNE)             # already there: only in "show all"
    write(os.path.join(dest, "2025", "06", "big_done.png"), b"y" * 500, JUNE)
    plan = make_plan(src, dest, incremental=True)
    dialog = PreviewDialog(plan, {"operation_mode": "copy"})
    model = dialog.table.model()

    def column(col):
        return [model.data(model.index(r, col)) for r in range(model.rowCount())]

    natural = column(COL_NAME)
    dialog.table.sortByColumn(COL_SIZE, Qt.SortOrder.DescendingOrder)
    assert column(COL_SIZE) == ["30.0 B", "20.0 B", "10.0 B"]
    dialog.table.sortByColumn(COL_SIZE, Qt.SortOrder.AscendingOrder)
    assert column(COL_SIZE) == ["10.0 B", "20.0 B", "30.0 B"]

    dialog._show_all.setChecked(True)                                           # the sort is kept
    assert column(COL_SIZE) == ["10.0 B", "20.0 B", "30.0 B", "500.0 B"]
    dialog._show_all.setChecked(False)

    dialog.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)                  # back to copy order
    assert column(COL_NAME) == natural


def test_sorting_a_quarter_million_rows_is_fast(qapp):
    import time
    from PyQt6.QtCore import Qt
    from copy_plan import PlanItem
    from ui.preview_dialog import COL_PRE_PATH, COL_SIZE, PlanTableModel
    items = [PlanItem(f"B:\\src\\{i % 977}\\file_{i}.png", (i * 7919) % 100_003, 1.7e9 + i,
                      f"E:\\dest\\2025\\06\\file_{i}.png", Action.UP_TO_DATE) for i in range(250_000)]
    model = PlanTableModel(items)
    started = time.perf_counter()
    model.sort(COL_SIZE, Qt.SortOrder.AscendingOrder)
    model.sort(COL_PRE_PATH, Qt.SortOrder.DescendingOrder)
    assert time.perf_counter() - started < 5.0                      # was 8-18 s per sort via the proxy model


def test_nothing_to_copy_is_said_clearly_and_offers_no_proceed_button(qapp, tmp_path):
    from ui.preview_dialog import PreviewDialog
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "one.png"), b"1", JUNE)
    write(os.path.join(dest, "2025", "06", "one.png"), b"1", JUNE)
    dialog = PreviewDialog(make_plan(src, dest), {"operation_mode": "copy"})
    assert "Nothing to copy — everything is already at the destination" in all_label_text(dialog)
    assert not hasattr(dialog, "proceed_btn")
    # nothing left to copy is when you want to see what is there, so the matches are shown
    assert dialog.table.model().rowCount() == 1 and dialog._show_all.isChecked()


def test_nothing_to_copy_because_names_are_taken_does_not_claim_everything_is_there(qapp, tmp_path):
    from ui.preview_dialog import PreviewDialog
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(dest, "2025", "06", "photo.png"), b"a different image")
    plan = make_plan(src, dest, number_duplicates=False)
    assert plan.copy_count == 0 and plan.counts[Action.NAME_TAKEN] == 1
    text = all_label_text(PreviewDialog(plan, {"operation_mode": "copy"}))
    assert "everything is already at the destination" not in text
    assert "Nothing to copy with the current settings" in text


def test_name_in_use_banner_explains_how_to_keep_those_files(qapp, tmp_path):
    from ui.preview_dialog import PreviewDialog
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)
    plan = make_plan(src, dest, number_duplicates=False)
    text = all_label_text(PreviewDialog(plan, {"operation_mode": "copy"}))
    assert "Number duplicate files" in text and "1 file was skipped" in text


def test_dialog_fits_a_1080p_screen(qapp, tmp_path):
    from ui.preview_dialog import PreviewDialog
    _src, _dest, plan = mixed_plan(tmp_path)
    dialog = PreviewDialog(plan, {"operation_mode": "copy"})
    assert dialog.width() <= 1920 and dialog.height() <= 1080


# ── single-source tab: the glue ──────────────────────────────────────────────

def make_window(tmp_path):
    from config import ConfigManager
    from ui.main_window import MainWindow
    return MainWindow(ConfigManager(Path(tmp_path) / "cfg.json"), "0.0.0")


def fill_form(win, src, dest, *, number=True, incremental=True, preserve=False):
    win.source_edit.setText(src)
    win.dest_edit.setText(dest)
    win.ext_edit.setText("*.png, *.jpg")
    win.recursive_check.setChecked(True)
    win.preserve_check.setChecked(preserve)
    win.number_check.setChecked(number)
    win.incremental_check.setChecked(incremental)
    win.verify_check.setChecked(False)
    win.folder_combo.setCurrentText("year_month")
    win.workers_spin.setValue(1)
    return win._build_copy_options()


def test_preview_then_proceed_copies_exactly_the_previewed_plan(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    from ui.preview_dialog import PreviewDialog
    src, dest, _ = mixed_plan(tmp_path)
    win = make_window(tmp_path)
    options = fill_form(win, src, dest)

    win._preview_worker(options)                                     # what the Preview button runs
    data = next(d for k, d in drain(win._progress_queue) if k == "preview_ready")
    plan = data["plan"]
    assert plan.copy_count == 3

    started = {}
    monkeypatch.setattr(PreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(win, "_execute_copy", lambda opts: started.update(opts))
    win._on_preview_ready(data)
    assert started["plan"] is plan                                   # Copy runs the very plan that was shown

    win._copy_worker(started)                                        # executing it ...
    complete = next(d for k, d in drain(win._progress_queue) if k == "complete")
    assert complete["copied_count"] == 3
    assert complete["skipped_count"] == 2
    assert complete["plan_counts"][Action.UP_TO_DATE] == 1
    assert set(tree(dest).values()) == {b"A" * 10, b"B" * 20, b"X" * 7, b"Y" * 9, b"D" * 5, b"S" * 5}

    win._preview_worker(fill_form(win, src, dest))                   # ... leaves nothing for the next Preview
    again = next(d for k, d in drain(win._progress_queue) if k == "preview_ready")["plan"]
    assert again.copy_count == 0


def test_cancelling_a_preview_is_a_quiet_stop(qapp, tmp_path):
    src, dest, _ = mixed_plan(tmp_path)
    win = make_window(tmp_path)
    options = fill_form(win, src, dest)
    win._cancel_requested = True
    win._preview_worker(options)
    kinds = [k for k, _ in drain(win._progress_queue)]
    assert "preview_cancelled" in kinds and "error" not in kinds


def test_cancelling_while_planning_a_copy_is_reported_as_cancelled_not_an_error(qapp, tmp_path):
    src, dest, _ = mixed_plan(tmp_path)
    win = make_window(tmp_path)
    options = fill_form(win, src, dest)
    win._cancel_requested = True
    win._copy_worker(options)
    kinds = [k for k, _ in drain(win._progress_queue)]
    assert "cancelled" in kinds and "error" not in kinds


# ── multi-source tab: the glue ───────────────────────────────────────────────

def multi_options(sources, dest, **over):
    opts = {
        "sources": sources, "dest_folder": dest, "extension": "*.png, *.jpg",
        "preserve_structure": False, "number_duplicates": True, "recursive_search": True,
        "folder_structure": "year_month", "min_size_bytes": None, "max_size_bytes": None,
        "max_days_old": None, "verify_checksum": False, "incremental": True,
        "operation_mode": "copy", "workers_per_source": 1, "sort_order": "largest",
        "sort_order_label": "Largest first",
    }
    opts.update(over)
    return opts


def make_tab(tmp_path):
    from config import ConfigManager
    from ui.multi_source_tab import MultiSourceTab
    return MultiSourceTab(ConfigManager(Path(tmp_path) / "cfg.json"), logging.getLogger("test"), None)


def test_multi_source_incremental_no_longer_crashes_and_converges(qapp, tmp_path):
    # Regression: with Incremental on, _pre_filter_incremental was a @staticmethod that used
    # `self`, so any source with an already-copied file failed with "name 'self' is not defined".
    s1, s2, dest = (os.path.join(str(tmp_path), n) for n in ("s1", "s2", "dest"))
    write(os.path.join(s1, "photo.png"), b"A" * 10)
    write(os.path.join(s1, "only1.png"), b"1" * 3)
    write(os.path.join(s2, "photo.png"), b"B" * 20)                  # same name, different image
    tab = make_tab(tmp_path)

    tab._worker(multi_options([s1, s2], dest))
    messages = drain(tab._progress_queue)
    first = next(d for k, d in messages if k == "all_complete")
    assert (first["copied"], first["skipped"], first["errors"]) == (3, 0, 0)
    assert set(tree(dest).values()) == {b"A" * 10, b"B" * 20, b"1" * 3}

    tab._worker(multi_options([s1, s2], dest))                       # second run: everything is there
    messages = drain(tab._progress_queue)
    second = next(d for k, d in messages if k == "all_complete")
    assert (second["copied"], second["skipped"], second["errors"]) == (0, 3, 0)
    assert not [d for k, d in messages if k == "status" and "ERROR" in str(d)]


def test_multi_source_cancel_while_planning_is_a_cancel_not_an_error(qapp, tmp_path):
    s1, dest = os.path.join(str(tmp_path), "s1"), os.path.join(str(tmp_path), "dest")
    write(os.path.join(s1, "photo.png"), b"A")
    tab = make_tab(tmp_path)
    tab._cancel_requested = True
    tab._worker(multi_options([s1], dest))
    kinds = [k for k, _ in drain(tab._progress_queue)]
    assert "all_cancelled" in kinds and "all_complete" not in kinds
