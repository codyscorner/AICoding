"""The planner: what happens to each source file, decided before anything is written."""
import os

import pytest

import copy_plan
from copy_plan import Action, PlanCancelled, build_plan, planned_name, stamps_match
from helpers import DAY, HOUR, JUNE, by_rel, make_plan, scan, write


def dirs(tmp_path):
    return os.path.join(str(tmp_path), "src"), os.path.join(str(tmp_path), "dest")


def dest_file(dest, *parts):
    return os.path.join(os.path.normpath(dest), "2025", "06", *parts)


# ── date comparison ──────────────────────────────────────────────────────────

class TestStampsMatch:
    def test_identical(self):
        assert stamps_match(10, 100.0, 10, 100.0)

    def test_two_second_tolerance_for_fat_rounding(self):
        assert stamps_match(10, 100.0, 10, 102.0)
        assert not stamps_match(10, 100.0, 10, 103.0)

    def test_exactly_one_hour_apart_is_a_daylight_saving_artefact(self):
        assert stamps_match(10, 100.0, 10, 100.0 + 3600)
        assert stamps_match(10, 100.0 + 3600, 10, 100.0)
        assert stamps_match(10, 100.0, 10, 100.0 + 3601)

    def test_two_hours_apart_is_a_real_difference(self):
        assert not stamps_match(10, 100.0, 10, 100.0 + 7200)

    def test_size_must_match(self):
        assert not stamps_match(10, 100.0, 11, 100.0)


# ── the basic outcomes ───────────────────────────────────────────────────────

def test_new_file_is_planned_into_its_date_folder(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A")
    plan = make_plan(src, dest)
    (item,) = plan.items
    assert item.action is Action.NEW
    assert item.pre_dest == dest_file(dest, "photo.png")
    assert item.cur_dest is None
    assert item.src_mtime == JUNE
    assert plan.copy_count == 1 and plan.skipped_count == 0


def test_empty_source_gives_an_empty_plan(tmp_path):
    _src, dest = dirs(tmp_path)
    plan = build_plan([], dest)
    assert plan.items == [] and plan.copy_count == 0


def test_two_different_images_with_one_name_get_separate_destinations(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)
    items = by_rel(make_plan(src, dest), src)
    first, second = items[os.path.join("a", "photo.png")], items[os.path.join("b", "photo.png")]
    assert first.action is Action.NEW and os.path.basename(first.pre_dest) == "photo.png"
    assert second.action is Action.NUMBERED and os.path.basename(second.pre_dest) == "photo_001.png"
    assert second.pre_dest != first.pre_dest


def test_a_numbered_file_says_which_file_took_its_name_when_nothing_on_disk_was_in_the_way(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)
    items = by_rel(make_plan(src, dest), src)
    second = items[os.path.join("b", "photo.png")]
    assert second.action is Action.NUMBERED and second.cur_dest is None
    assert second.ref == items[os.path.join("a", "photo.png")].source_path

    # a file already at the destination is reported as the thing in the way instead
    write(dest_file(dest, "photo.png"), b"someone else")
    items = by_rel(make_plan(src, dest), src)
    assert all(i.cur_dest == dest_file(dest, "photo.png") and i.ref is None
               for i in items.values() if i.action is Action.NUMBERED)


def test_identical_copies_in_several_folders_are_copied_once(tmp_path):
    src, dest = dirs(tmp_path)
    for sub in "abc":
        write(os.path.join(src, sub, "photo.png"), b"SAME")
    plan = make_plan(src, dest)
    assert plan.copy_count == 1
    assert plan.counts[Action.DUPLICATE_SOURCE] == 2
    copied = plan.to_copy[0]
    for item in plan.items:
        assert item.pre_dest == copied.pre_dest
        if item is not copied:
            assert item.ref == copied.source_path


def test_same_image_with_different_dates_is_still_one_image(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"SAME", JUNE)
    write(os.path.join(src, "b", "photo.png"), b"SAME", JUNE + 3 * DAY)
    plan = make_plan(src, dest)
    assert plan.copy_count == 1 and plan.counts[Action.DUPLICATE_SOURCE] == 1


def test_the_newest_copy_of_an_image_is_the_one_that_gets_copied(tmp_path):
    # Several copies of one image with different dates: the destination carries the date of the
    # newest copy (with "newest wins" that is the image's date).
    src, dest = dirs(tmp_path)
    for sub in "bcd":
        write(os.path.join(src, sub, "photo.png"), b"SAME", JUNE)
    write(os.path.join(src, "a", "photo.png"), b"SAME", JUNE + 2 * DAY)      # lone, newest
    for incremental in (True, False):
        plan = make_plan(src, dest, incremental=incremental)
        assert plan.copy_count == 1
        assert plan.to_copy[0].src_mtime == JUNE + 2 * DAY
        assert plan.to_copy[0].source_path.endswith(os.path.join("a", "photo.png"))


@pytest.mark.parametrize("incremental, copies", [(True, 1), (False, 2)])
def test_incremental_trusts_size_and_date_between_sources_but_strict_mode_checks_bytes(tmp_path, incremental, copies):
    # Same name, same size, same date, different bytes. Incremental means "size + date are enough",
    # so it sees one file; with Incremental off nothing is trusted and both images are kept.
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    write(os.path.join(src, "b", "photo.png"), b"BBBB", JUNE)
    plan = make_plan(src, dest, incremental=incremental)
    assert plan.copy_count == copies


# ── comparing with what is already at the destination ───────────────────────

def test_same_size_and_date_is_up_to_date(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A", JUNE)
    existing = write(dest_file(dest, "photo.png"), b"A", JUNE)
    (item,) = make_plan(src, dest).items
    assert item.action is Action.UP_TO_DATE
    assert item.pre_dest == existing and item.cur_dest == existing
    assert item.cur_size == 1 and item.cur_mtime == JUNE


def test_a_one_hour_date_gap_is_not_a_change(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A", JUNE)
    write(dest_file(dest, "photo.png"), b"A", JUNE + HOUR)
    (item,) = make_plan(src, dest).items
    assert item.action is Action.UP_TO_DATE


def test_same_bytes_with_another_date_is_recognised_by_content(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    write(dest_file(dest, "photo.png"), b"AAAA", JUNE + 5 * DAY)
    (item,) = make_plan(src, dest).items
    assert item.action is Action.SAME_CONTENT
    assert item.cur_mtime == JUNE + 5 * DAY       # Preview shows the differing dates side by side


def test_same_size_but_different_bytes_is_a_different_file(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    other = write(dest_file(dest, "photo.png"), b"BBBB", JUNE + DAY)
    (item,) = make_plan(src, dest).items
    assert item.action is Action.NUMBERED
    assert os.path.basename(item.pre_dest) == "photo_001.png"
    assert item.cur_dest == other                  # the file that is in the way


@pytest.mark.parametrize("incremental, expected", [(True, Action.UP_TO_DATE), (False, Action.NUMBERED)])
def test_incremental_trusts_size_and_date_but_non_incremental_checks_bytes(tmp_path, incremental, expected):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    write(dest_file(dest, "photo.png"), b"BBBB", JUNE)          # same size, same date, different bytes
    (item,) = make_plan(src, dest, incremental=incremental).items
    assert item.action is expected


def test_non_incremental_identical_file_is_skipped(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    write(dest_file(dest, "photo.png"), b"AAAA", JUNE + DAY)
    (item,) = make_plan(src, dest, incremental=False).items
    assert not item.writes


def test_oversized_files_are_not_hashed_when_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_plan, "CONTENT_CHECK_MAX_BYTES", 5)
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAAAAAA", JUNE)
    write(dest_file(dest, "photo.png"), b"AAAAAAAA", JUNE + DAY)
    (item,) = make_plan(src, dest, incremental=True).items
    assert item.action is Action.NUMBERED          # too big to check: treated as different
    (item,) = make_plan(src, dest, incremental=False).items
    assert not item.writes                         # non-incremental always compares bytes


# ── when the name is taken ───────────────────────────────────────────────────

def test_with_numbering_off_a_taken_name_is_skipped_never_overwritten(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    other = write(dest_file(dest, "photo.png"), b"a different image", JUNE)
    (item,) = make_plan(src, dest, number_duplicates=False).items
    assert item.action is Action.NAME_TAKEN
    assert item.pre_dest == other and item.cur_dest == other
    assert not item.writes


def test_with_numbering_off_the_first_image_gets_the_name_and_the_rest_are_skipped(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)
    plan = make_plan(src, dest, number_duplicates=False)
    assert plan.counts[Action.NEW] == 1 and plan.counts[Action.NAME_TAKEN] == 1


def test_a_folder_with_the_files_name_pushes_it_to_a_numbered_name(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A")
    os.makedirs(dest_file(dest, "photo.png"))
    (item,) = make_plan(src, dest).items
    assert item.action is Action.NUMBERED and os.path.basename(item.pre_dest) == "photo_001.png"


def test_names_are_compared_ignoring_case(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "Photo.PNG"), b"A")
    write(os.path.join(src, "b", "photo.png"), b"BB")
    plan = make_plan(src, dest)
    assert sorted(i.action.value for i in plan.items) == ["new", "numbered"]


def test_a_numbered_name_never_steals_another_files_own_name(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A")
    write(os.path.join(src, "b", "photo.png"), b"BB")
    write(os.path.join(src, "c", "photo_001.png"), b"CCC")      # really is called photo_001.png
    items = by_rel(make_plan(src, dest), src)
    assert os.path.basename(items[os.path.join("c", "photo_001.png")].pre_dest) == "photo_001.png"
    assert items[os.path.join("c", "photo_001.png")].action is Action.NEW
    assert os.path.basename(items[os.path.join("b", "photo.png")].pre_dest) == "photo_002.png"


# ── numbered copies made by an earlier run ───────────────────────────────────

def test_numbered_copies_from_an_earlier_run_are_recognised(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)
    write(dest_file(dest, "photo.png"), b"A" * 10)
    write(dest_file(dest, "photo_001.png"), b"B" * 20)
    plan = make_plan(src, dest)
    assert plan.copy_count == 0
    items = by_rel(plan, src)
    assert os.path.basename(items[os.path.join("b", "photo.png")].pre_dest) == "photo_001.png"


def test_repeat_numbered_duplicates_from_the_old_numbering_bug_cause_no_new_copies(tmp_path):
    # Older versions added photo_002, photo_003 ... on every re-run. They are identical;
    # the planner must simply recognise the image and copy nothing.
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 10)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20)
    write(dest_file(dest, "photo.png"), b"A" * 10)
    for n in (1, 2, 3):
        write(dest_file(dest, f"photo_00{n}.png"), b"B" * 20)
    assert make_plan(src, dest).copy_count == 0


# ── "newest wins": the same name, a different date ──────────────────────────

def test_a_newer_source_is_copied_over_the_older_copy_at_the_destination(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"the edited version", JUNE + DAY)
    old = write(dest_file(dest, "photo.png"), b"old", JUNE)
    (item,) = make_plan(src, dest, incremental=True, number_duplicates=False).items
    assert item.action is Action.REFRESH and item.writes
    assert item.pre_dest == old and item.cur_dest == old          # same name -> copied over it
    assert item.src_mtime == JUNE + DAY and item.cur_mtime == JUNE
    assert (item.size, item.cur_size) == (18, 3)


def test_an_older_source_is_skipped_because_the_file_is_older(tmp_path):
    # e.g. IMG_4513-2.jpg: source 15:43:29, destination 15:43:49
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "IMG_4513-2.jpg"), b"source version", JUNE)
    write(dest_file(dest, "IMG_4513-2.jpg"), b"destination version", JUNE + 20)
    (item,) = make_plan(src, dest, incremental=True, number_duplicates=False).items
    assert item.action is Action.OLDER and not item.writes
    assert item.pre_dest == item.cur_dest
    assert item.src_mtime < item.cur_mtime


def test_the_same_date_with_different_bytes_keeps_the_destination_copy(tmp_path):
    # A tie must not flip-flop between two different images, so the destination copy stays.
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"AAAA", JUNE)
    write(dest_file(dest, "photo.png"), b"different and longer", JUNE + 1)
    (item,) = make_plan(src, dest, incremental=True, number_duplicates=False).items
    assert item.action is Action.OLDER


def test_numbering_on_never_overwrites_whatever_the_dates(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"newer one", JUNE + DAY)
    write(os.path.join(src, "b", "other.png"), b"older one", JUNE - DAY)
    write(dest_file(dest, "photo.png"), b"old", JUNE)
    write(dest_file(dest, "other.png"), b"destination copy", JUNE)
    plan = make_plan(src, dest, incremental=True, number_duplicates=True)
    assert [i.action for i in plan.items] == [Action.NUMBERED, Action.NUMBERED]


def test_without_incremental_dates_are_not_compared(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"newer one", JUNE + DAY)
    write(os.path.join(src, "b", "other.png"), b"older one", JUNE - DAY)
    write(dest_file(dest, "photo.png"), b"old", JUNE)
    write(dest_file(dest, "other.png"), b"destination copy", JUNE)
    plan = make_plan(src, dest, incremental=False, number_duplicates=False)
    assert [i.action for i in plan.items] == [Action.NAME_TAKEN, Action.NAME_TAKEN]


def test_the_newest_of_several_different_files_takes_the_name(tmp_path):
    src, dest = dirs(tmp_path)
    for n in (1, 3, 2):
        write(os.path.join(src, f"d{n}", "photo.png"), bytes([64 + n]) * (n + 4), JUNE + n * DAY)
    items = by_rel(make_plan(src, dest, incremental=True, number_duplicates=False), src)
    newest = items[os.path.join("d3", "photo.png")]
    assert newest.action is Action.NEW
    for n in (1, 2):
        older = items[os.path.join(f"d{n}", "photo.png")]
        assert older.action is Action.OLDER and older.cur_dest is None
        assert older.ref == newest.source_path                  # says which file is newer

    write(dest_file(dest, "photo.png"), b"the old one", JUNE - DAY)          # now something old is there
    items = by_rel(make_plan(src, dest, incremental=True, number_duplicates=False), src)
    assert items[os.path.join("d3", "photo.png")].action is Action.REFRESH
    assert items[os.path.join("d1", "photo.png")].action is Action.OLDER
    assert items[os.path.join("d2", "photo.png")].action is Action.OLDER


def test_sources_matching_a_copy_that_is_about_to_be_replaced_are_reported_as_older(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"version one", JUNE)
    write(os.path.join(src, "b", "photo.png"), b"version two!", JUNE + DAY)
    write(dest_file(dest, "photo.png"), b"version one", JUNE)
    items = by_rel(make_plan(src, dest, incremental=True, number_duplicates=False), src)
    assert items[os.path.join("b", "photo.png")].action is Action.REFRESH
    stale = items[os.path.join("a", "photo.png")]
    assert stale.action is Action.OLDER                          # not "up to date": its copy is being replaced
    assert stale.ref == items[os.path.join("b", "photo.png")].source_path


def test_a_newer_copy_of_the_version_at_the_destination_stops_an_in_between_file_replacing_it(tmp_path):
    # The destination holds version one (dated JUNE). Another source still has the SAME version
    # re-stamped three days later; a different file dated one day later must not replace it, or the
    # next run would flip it back.
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"version one", JUNE)
    restamped = write(os.path.join(src, "b", "photo.png"), b"version one", JUNE + 3 * DAY)
    write(os.path.join(src, "c", "photo.png"), b"another file!", JUNE + DAY)
    write(dest_file(dest, "photo.png"), b"version one", JUNE)
    items = by_rel(make_plan(src, dest, incremental=True, number_duplicates=False), src)
    between = items[os.path.join("c", "photo.png")]
    assert between.action is Action.OLDER and between.ref == restamped


def test_a_folder_in_the_way_is_name_in_use_not_older(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A", JUNE + DAY)
    os.makedirs(dest_file(dest, "photo.png"))
    (item,) = make_plan(src, dest, incremental=True, number_duplicates=False).items
    assert item.action is Action.NAME_TAKEN


# ── mirror (preserve structure) layout ───────────────────────────────────────

def test_mirror_layout_skips_a_source_older_than_the_destination_copy(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "sub", "photo.png"), b"older source", JUNE)
    write(os.path.join(dest, "sub", "photo.png"), b"newer destination", JUNE + DAY)
    for numbering in (True, False):
        (item,) = make_plan(src, dest, preserve_structure=True, incremental=True,
                            number_duplicates=numbering).items
        assert item.action is Action.OLDER


def test_mirror_layout_still_updates_when_the_dates_are_equal_but_the_file_differs(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "sub", "photo.png"), b"changed within a second", JUNE)
    write(os.path.join(dest, "sub", "photo.png"), b"before", JUNE + 1)
    (item,) = make_plan(src, dest, preserve_structure=True, incremental=True).items
    assert item.action is Action.REFRESH


def test_mirror_layout_updates_a_changed_file_in_place_when_incremental(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "sub", "photo.png"), b"the new version", JUNE + DAY)
    old = write(os.path.join(dest, "sub", "photo.png"), b"old", JUNE)
    (item,) = make_plan(src, dest, preserve_structure=True, incremental=True).items
    assert item.action is Action.REFRESH
    assert item.pre_dest == old and item.cur_dest == old and item.cur_mtime == JUNE


def test_mirror_layout_without_incremental_never_overwrites(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "sub", "photo.png"), b"the new version", JUNE + DAY)
    write(os.path.join(dest, "sub", "photo.png"), b"old", JUNE)
    (item,) = make_plan(src, dest, preserve_structure=True, incremental=False).items
    assert item.action is Action.NUMBERED
    (item,) = make_plan(src, dest, preserve_structure=True, incremental=False, number_duplicates=False).items
    assert item.action is Action.NAME_TAKEN


def test_date_layout_with_numbering_on_never_overwrites_even_when_incremental(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "sub", "photo.png"), b"the new version", JUNE + DAY)
    old = write(dest_file(dest, "photo.png"), b"old", JUNE)
    (item,) = make_plan(src, dest, incremental=True, number_duplicates=True).items
    assert item.action is Action.NUMBERED and item.cur_dest == old


# ── housekeeping ─────────────────────────────────────────────────────────────

def test_items_come_back_in_the_order_the_files_were_given(tmp_path):
    src, dest = dirs(tmp_path)
    for i, name in enumerate("dcba"):
        write(os.path.join(src, name, f"p{i}.png"), bytes([i]) * (i + 1))
    files = scan(src)
    plan = build_plan(files, dest, folder_structure=copy_plan.FolderStructure.BY_YEAR_MONTH)
    assert [i.source_path for i in plan.items] == [f[0] for f in files]


def test_counts_and_bytes_to_copy(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "one.png"), b"1" * 7)
    write(os.path.join(src, "a", "two.png"), b"2" * 5)
    write(dest_file(dest, "two.png"), b"2" * 5)
    plan = make_plan(src, dest)
    assert plan.counts[Action.NEW] == 1 and plan.counts[Action.UP_TO_DATE] == 1
    assert plan.bytes_to_copy == 7 and plan.copy_count == 1 and plan.skipped_count == 1


def test_overlong_destination_names_are_shortened_the_same_way_every_time():
    folder = os.path.join("C:\\", "dest", "2025", "06")
    name = "x" * 300 + ".png"
    short = planned_name(folder, name)
    assert short.endswith("_tr_001.png")
    assert len(os.path.join(folder, short)) <= 245
    assert planned_name(folder, name) == short
    assert planned_name(folder, "photo.png") == "photo.png"


def test_planning_can_be_cancelled(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A")
    with pytest.raises(PlanCancelled):
        make_plan(src, dest, cancel_check=lambda: True)


def test_progress_is_reported(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 4)
    write(dest_file(dest, "photo.png"), b"A" * 4, JUNE + DAY)       # forces a content comparison
    seen = []
    make_plan(src, dest, progress=lambda stage, done, total: seen.append(stage))
    assert "Reading destination folders" in seen and "Comparing file contents" in seen
