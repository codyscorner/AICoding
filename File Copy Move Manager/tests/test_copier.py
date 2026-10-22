"""Executing a plan: the next preview is empty, Preview == Copy, and nothing is lost on cancel."""
import os
import random
import stat

import pytest

from copy_plan import Action
from file_operations import FileCopier, summarize_results
from folder_organization import FolderStructure
from helpers import DAY, HOUR, JUNE, by_rel, leftovers, make_plan, run_copy, tree, write


def dirs(tmp_path):
    return os.path.join(str(tmp_path), "src"), os.path.join(str(tmp_path), "dest")


def build_tricky_source(src):
    """One of everything that used to break convergence."""
    write(os.path.join(src, "a", "photo.png"), b"A" * 10, JUNE)
    write(os.path.join(src, "b", "photo.png"), b"B" * 20, JUNE)               # different image, same name
    write(os.path.join(src, "c", "photo.png"), b"A" * 10, JUNE + 3 * DAY)     # same image as a, other date
    write(os.path.join(src, "d", "photo.png"), b"A" * 10, JUNE + HOUR)        # same image, 1 h (DST) off
    write(os.path.join(src, "e", "photo.png"), b"C" * 10, JUNE + 30)          # same SIZE as a, other bytes
    write(os.path.join(src, "f", "photo_001.png"), b"D" * 30, JUNE)           # really is called photo_001
    write(os.path.join(src, "g", "other.jpg"), b"E", JUNE)
    write(os.path.join(src, "h", "deep", "deeper", "pic.png"), b"F", JUNE - 40 * DAY)   # another month


# ── the point of the whole exercise: copy, then preview shows nothing ───────

@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize("number", [True, False])
def test_after_a_copy_the_next_preview_is_empty(tmp_path, incremental, number):
    src, dest = dirs(tmp_path)
    build_tricky_source(src)
    opts = dict(incremental=incremental, number_duplicates=number)

    _, results = run_copy(src, dest, make_plan(src, dest, **opts), **opts)
    assert results and all(r.success for r in results)
    first = tree(dest)

    again = make_plan(src, dest, **opts)
    assert again.copy_count == 0, [(i.source_path, i.action.value) for i in again.to_copy]

    _, results2 = run_copy(src, dest, **opts)           # no plan: scans and compares again
    assert results2 == []
    assert tree(dest) == first                          # nothing rewritten, nothing added
    assert leftovers(dest) == []

    source_contents = set(tree(src).values())
    if number:
        assert set(first.values()) == source_contents   # every distinct image is in the backup
    else:
        # numbering is off: the first image keeps the name, the two other photo.png images are skipped
        assert b"B" * 20 not in first.values() and b"C" * 10 not in first.values()
        assert {b"A" * 10, b"D" * 30, b"E", b"F"} <= set(first.values())


@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize("number", [True, False])
def test_mirror_layout_copies_everything_to_its_own_path_and_converges(tmp_path, incremental, number):
    src, dest = dirs(tmp_path)
    build_tricky_source(src)
    opts = dict(incremental=incremental, number_duplicates=number, preserve=True)
    popts = dict(incremental=incremental, number_duplicates=number, preserve_structure=True)

    run_copy(src, dest, make_plan(src, dest, **popts), **opts)
    assert tree(dest) == tree(src)
    assert make_plan(src, dest, **popts).copy_count == 0


def test_a_changed_file_is_updated_in_place_in_mirror_layout(tmp_path):
    src, dest = dirs(tmp_path)
    popts = dict(incremental=True, preserve_structure=True)
    write(os.path.join(src, "s", "photo.png"), b"version 1", JUNE)
    run_copy(src, dest, make_plan(src, dest, **popts), incremental=True, preserve=True)

    write(os.path.join(src, "s", "photo.png"), b"version 2 is longer", JUNE + DAY)
    plan = make_plan(src, dest, **popts)
    assert plan.counts[Action.REFRESH] == 1
    run_copy(src, dest, plan, incremental=True, preserve=True)

    assert tree(dest) == {os.path.join("s", "photo.png"): b"version 2 is longer"}
    assert make_plan(src, dest, **popts).copy_count == 0


def test_a_newer_source_is_copied_over_and_an_older_one_is_left_alone(tmp_path):
    # The date layout with Incremental on and numbering off: the destination keeps the NEWEST
    # version of every name, and the next Preview is empty (the two rules you asked for).
    src, dest = dirs(tmp_path)
    opts = dict(incremental=True, number_duplicates=False)
    first = write(os.path.join(src, "a", "photo.png"), b"version one", JUNE)
    other = write(os.path.join(src, "b", "photo.png"), b"another file with this name", JUNE - DAY)
    run_copy(src, dest, make_plan(src, dest, **opts), **opts)
    assert list(tree(dest).values()) == [b"version one"]               # the newer of the two got the name
    assert make_plan(src, dest, **opts).copy_count == 0

    write(first, b"version two, edited later", JUNE + 2 * DAY)          # the file changes at the source
    plan = make_plan(src, dest, **opts)
    assert [i.action for i in plan.to_copy] == [Action.REFRESH]
    assert plan.counts[Action.OLDER] == 1                                # b/photo.png is older: skipped
    run_copy(src, dest, plan, **opts)
    assert list(tree(dest).values()) == [b"version two, edited later"]
    assert abs(os.path.getmtime(os.path.join(dest, "2025", "06", "photo.png")) - (JUNE + 2 * DAY)) < 2
    assert make_plan(src, dest, **opts).copy_count == 0                  # nothing left to copy
    assert os.path.exists(other)                                         # a copy never touches the source


def test_a_read_only_destination_file_can_still_be_refreshed(tmp_path):
    src, dest = dirs(tmp_path)
    popts = dict(incremental=True, preserve_structure=True)
    write(os.path.join(src, "photo.png"), b"v1", JUNE)
    run_copy(src, dest, make_plan(src, dest, **popts), incremental=True, preserve=True)
    target = os.path.join(dest, "photo.png")
    os.chmod(target, stat.S_IREAD)

    write(os.path.join(src, "photo.png"), b"version two", JUNE + DAY)
    _, results = run_copy(src, dest, make_plan(src, dest, **popts), incremental=True, preserve=True)
    assert all(r.success for r in results)
    with open(target, "rb") as f:
        assert f.read() == b"version two"


# ── Preview == Copy ──────────────────────────────────────────────────────────

def test_the_copy_writes_exactly_what_the_plan_promised(tmp_path):
    src, dest = dirs(tmp_path)
    build_tricky_source(src)
    plan = make_plan(src, dest)
    _, results = run_copy(src, dest, plan)

    promised = {os.path.normcase(i.pre_dest) for i in plan.to_copy}
    written = {os.path.normcase(os.path.join(dest, r)) for r in tree(dest)}
    assert written == promised
    assert {r.destination_file for r in results} == {os.path.basename(i.pre_dest) for i in plan.to_copy}


def test_copy_without_a_plan_gives_the_same_result_as_copy_after_preview(tmp_path):
    src, dest_a = dirs(tmp_path)
    dest_b = os.path.join(str(tmp_path), "dest_b")
    build_tricky_source(src)
    run_copy(src, dest_a, make_plan(src, dest_a))
    run_copy(src, dest_b)
    assert tree(dest_a) == tree(dest_b)


def test_a_name_taken_after_the_plan_was_made_is_not_overwritten(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"ours")
    plan = make_plan(src, dest)
    someone_elses = write(os.path.join(dest, "2025", "06", "photo.png"), b"someone else's file")

    _, results = run_copy(src, dest, plan)
    with open(someone_elses, "rb") as f:
        assert f.read() == b"someone else's file"
    assert [r.destination_file for r in results] == ["photo_001.png"]
    assert leftovers(dest) == []


# ── counters ─────────────────────────────────────────────────────────────────

def test_counters_include_the_files_the_plan_skipped(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "one.png"), b"1")
    write(os.path.join(src, "b", "two.png"), b"2")
    write(os.path.join(dest, "2025", "06", "two.png"), b"2")
    seen = []
    copier, results = run_copy(src, dest, counters_callback=lambda c, s, e: seen.append((c, s, e)))
    assert seen[0] == (0, 1, 0) and seen[-1] == (1, 1, 0)
    assert copier.planned_skips == 1
    summary = summarize_results(results, copier.planned_skips)
    assert (summary.copied, summary.skipped, summary.errors) == (1, 1, 0)


def test_nothing_to_copy_still_reports_what_was_skipped(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "one.png"), b"1")
    run_copy(src, dest)
    seen, log = [], []
    copier, results = run_copy(src, dest, counters_callback=lambda c, s, e: seen.append((c, s, e)),
                               status_callback=log.append)
    assert results == [] and seen[-1] == (0, 1, 0)
    assert any(m.startswith("Nothing to copy") for m in log)
    assert any(m.startswith("Skipped (unchanged)") for m in log)       # per-file reason still logged


# ── move mode and cancel: no data loss ──────────────────────────────────────

def test_move_mode_removes_sources_it_copied_and_keeps_ones_it_skipped(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"SAME")
    write(os.path.join(src, "b", "photo.png"), b"SAME")          # identical: skipped, so stays put
    write(os.path.join(src, "c", "other.png"), b"OTHER")
    run_copy(src, dest, move_mode=True)
    assert not os.path.exists(os.path.join(src, "a", "photo.png"))
    assert os.path.exists(os.path.join(src, "b", "photo.png"))
    assert not os.path.exists(os.path.join(src, "c", "other.png"))
    assert set(tree(dest).values()) == {b"SAME", b"OTHER"}


def test_cancelling_a_large_move_keeps_the_source_and_leaves_no_partial_file(tmp_path, monkeypatch):
    # Regression: a cancel part-way through a >=120 MB file used to delete the source
    # and leave a truncated copy behind.
    monkeypatch.setattr(FileCopier, "LARGE_FILE_THRESHOLD", 1024)
    monkeypatch.setattr(FileCopier, "CHUNK_SIZE", 256)
    src, dest = dirs(tmp_path)
    payload = os.urandom(4096)
    big = write(os.path.join(src, "a", "big.png"), payload)
    plan = make_plan(src, dest)          # planned without cancelling, so Cancel lands mid-file
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 4          # lets a few chunks through, then "Cancel" is pressed

    _, results = run_copy(src, dest, plan, move_mode=True, cancel_check=cancel)
    with open(big, "rb") as f:
        assert f.read() == payload
    assert tree(dest) == {}
    assert leftovers(dest) == []
    assert not any(r.destination_file for r in results)

    _, results = run_copy(src, dest, move_mode=True)           # a later run finishes the job
    assert not os.path.exists(big)
    assert list(tree(dest).values()) == [payload]


def test_cancelling_midway_then_rerunning_finishes_the_job(tmp_path):
    src, dest = dirs(tmp_path)
    for i in range(30):
        write(os.path.join(src, f"d{i % 3}", f"p{i}.png"), bytes([i + 1]) * (i + 1))
    stop = {"now": False}

    def counters(copied, skipped, errors):
        if copied >= 10:
            stop["now"] = True

    run_copy(src, dest, cancel_check=lambda: stop["now"], counters_callback=counters)
    partial = tree(dest)
    assert 10 <= len(partial) < 30
    assert leftovers(dest) == []

    run_copy(src, dest)
    assert len(tree(dest)) == 30
    assert make_plan(src, dest).copy_count == 0


def test_a_file_that_vanishes_after_the_preview_is_one_error_not_a_crash(tmp_path):
    src, dest = dirs(tmp_path)
    gone = write(os.path.join(src, "a", "gone.png"), b"G")
    write(os.path.join(src, "a", "kept.png"), b"K")
    plan = make_plan(src, dest)
    os.remove(gone)
    _, results = run_copy(src, dest, plan)
    summary = summarize_results(results)
    assert (summary.copied, summary.errors) == (1, 1)
    assert leftovers(dest) == []


def test_a_leftover_temp_file_from_an_interrupted_copy_is_reported_and_ignored(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A")
    stray = write(os.path.join(dest, "2025", "06", "~fcmm_0123456789ab.partial"), b"half a fi")
    log = []
    copier, results = run_copy(src, dest, status_callback=log.append)
    assert [r.destination_file for r in results] == ["photo.png"]        # the stray never confuses matching
    assert any(m.startswith("Note:") and "interrupted" in m for m in log)
    assert os.path.exists(stray)                                         # and nobody deletes it for you
    plan = make_plan(src, dest)
    assert plan.leftover_temp_files == [stray] and plan.copy_count == 0


def test_the_live_transfer_row_is_cleared_even_when_the_copy_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(FileCopier, "MIN_FILE_PROGRESS_SIZE", 1)
    monkeypatch.setattr(FileCopier, "MAX_RETRIES", 1)
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 50)
    plan = make_plan(src, dest)

    def broken(self, *args, **kwargs):
        raise OSError("drive vanished")

    monkeypatch.setattr(FileCopier, "_copy_to_temp", broken)
    events = []
    _, results = run_copy(src, dest, plan, transfer_callback=lambda tid, name, pct: events.append(pct))
    assert not results[0].success
    assert events[0] == 0 and events[-1] == -1


def test_checksum_verification_still_works(tmp_path):
    src, dest = dirs(tmp_path)
    write(os.path.join(src, "a", "photo.png"), b"A" * 1000)
    _, results = run_copy(src, dest, verify_checksum=True)
    assert [r.checksum_verified for r in results] == [True]


# ── randomized: convergence must hold for any mix ───────────────────────────

NAMES = ["photo.png", "img.jpg", "a.png", "b.png", "photo_001.png", "Photo.PNG"]
FOLDERS = ["f1", "f2", os.path.join("f3", "x"), os.path.join("f3", "y"), "f4"]
SHIFTS = [0, 0, 0, HOUR, -HOUR, DAY, 2 * DAY, 30 * DAY, -45 * DAY]     # incl. other months


def random_source(src, seed):
    """Random tree with many same-name / same-size / different-date copies.

    Each image gets its own date (10 s apart), so two *different* images never share
    both size and date — the one thing Incremental mode is documented to trust.
    """
    rnd = random.Random(seed)
    contents = [(bytes([65 + i]) * rnd.choice([5, 5, 9, 12]), i * 10) for i in range(8)]   # some share a size
    for _ in range(rnd.randint(15, 45)):
        path = os.path.join(src, rnd.choice(FOLDERS), rnd.choice(NAMES))
        if os.path.exists(path):
            continue
        data, offset = rnd.choice(contents)
        write(path, data, JUNE + offset + rnd.choice(SHIFTS))


def newest_per_slot(src):
    """{(date folder, lower-case name): (mtime, bytes)} of the newest source for every destination name."""
    from folder_organization import FolderOrganizer
    best = {}
    for root, _dirs, names in os.walk(src):
        for name in names:
            path = os.path.join(root, name)
            mtime = os.stat(path).st_mtime
            sub = FolderOrganizer.subfolder_for_mtime(mtime, FolderStructure.BY_YEAR_MONTH)
            key = (sub, name.lower())
            if key not in best or mtime > best[key][0]:
                with open(path, "rb") as f:
                    best[key] = (mtime, f.read())
    return best


def assert_no_source_is_newer_and_different(src, dest):
    """The postcondition of "newest wins": every name has a file at the destination, and no source
    with that name (in that date folder) is both different from it and newer than it. (A backup
    never deletes, so a destination file may be newer than every source left — that is fine.)"""
    from folder_organization import FolderOrganizer
    for root, _dirs, names in os.walk(src):
        for name in names:
            path = os.path.join(root, name)
            mtime = os.stat(path).st_mtime
            sub = FolderOrganizer.subfolder_for_mtime(mtime, FolderStructure.BY_YEAR_MONTH)
            target = os.path.join(dest, sub, name)
            assert os.path.exists(target), (sub, name)
            with open(path, "rb") as a, open(target, "rb") as b:
                same = a.read() == b.read()
            assert same or mtime <= os.path.getmtime(target) + 2.5, (path, "is newer than", target)


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("incremental, number, mirror", [
    (True, True, False), (True, False, False), (False, True, False), (False, False, False),
    (True, True, True), (False, True, True),
])
def test_random_trees_always_converge(tmp_path, seed, incremental, number, mirror):
    src, dest = dirs(tmp_path)
    random_source(src, seed)
    before = tree(src)
    popts = dict(incremental=incremental, number_duplicates=number, preserve_structure=mirror)
    copts = dict(incremental=incremental, number_duplicates=number, preserve=mirror)

    _, results = run_copy(src, dest, make_plan(src, dest, **popts), **copts)
    assert all(r.success for r in results)
    first = tree(dest)

    assert make_plan(src, dest, **popts).copy_count == 0
    run_copy(src, dest, **copts)
    assert tree(dest) == first                      # a second run changes nothing
    assert tree(src) == before                      # copy mode never touches the source
    assert leftovers(dest) == []

    if mirror:
        assert first == before
    elif number:
        assert set(first.values()) == set(before.values())      # every distinct image was kept
    else:
        # numbering off: every name holds the NEWEST version of that name (per date folder)
        for (sub, name), (mtime, content) in newest_per_slot(src).items():
            path = os.path.join(dest, sub, name)
            assert os.path.exists(path), (sub, name)
            with open(path, "rb") as f:
                assert f.read() == content, (sub, name)
            assert abs(os.path.getmtime(path) - mtime) < 2.5, (sub, name)


@pytest.mark.parametrize("seed", range(6))
def test_repeated_runs_with_files_changing_in_between_always_converge(tmp_path, seed):
    """Run, change the sources (re-save some files later with new bytes, add new names), run again ...
    After every run the next Preview must be empty and every name must hold its newest version."""
    src, dest = dirs(tmp_path)
    rnd = random.Random(seed)
    opts = dict(incremental=True, number_duplicates=False)
    random_source(src, seed)
    counter = 0
    for generation in range(1, 5):
        run_copy(src, dest, make_plan(src, dest, **opts), **opts)
        assert make_plan(src, dest, **opts).copy_count == 0, f"generation {generation}"
        assert_no_source_is_newer_and_different(src, dest)

        # "Later" must really be later than anything already in that month (the originals reach
        # JUNE + 2 days + 1 hour), otherwise the destination copy is legitimately the newer one.
        later = JUNE + 3 * DAY + generation * 5000
        existing = [os.path.join(r, f) for r, _d, fs in os.walk(src) for f in fs]
        for path in rnd.sample(existing, min(4, len(existing))):          # re-saved later, new content
            counter += 1
            write(path, bytes([97 + counter % 26]) * (3 + counter % 7), later + counter * 10)
        for _ in range(3):                                                  # and some brand-new files
            counter += 1
            new = os.path.join(src, rnd.choice(FOLDERS), rnd.choice(NAMES))
            if not os.path.exists(new):
                write(new, bytes([65 + counter % 26]) * (4 + counter % 5), later + counter * 10)


@pytest.mark.parametrize("seed", range(3))
def test_parallel_workers_converge_too(tmp_path, seed):
    src, dest = dirs(tmp_path)
    random_source(src, seed + 100)
    opts = dict(incremental=True, number_duplicates=True)
    run_copy(src, dest, make_plan(src, dest, **opts), workers=4, **opts)
    first = tree(dest)
    assert make_plan(src, dest, **opts).copy_count == 0
    assert set(first.values()) == set(tree(src).values())
    assert leftovers(dest) == []
