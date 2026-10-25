"""SQLite-backed scan / ROW_NUMBER() ranking / execute tests for File Hash Dedupe."""
import csv
import os

import pytest

import hasher
from hasher import FileDeduplicator


def _write(path, data: bytes, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def db(tmp_path):
    return tmp_path / "cache" / "hashes.db"


@pytest.fixture
def dd(db):
    db.parent.mkdir()
    return FileDeduplicator(db, max_workers=4)


@pytest.fixture
def hash_calls(monkeypatch):
    """Count real file hashes, to prove cached files are not re-hashed."""
    calls = []
    real = hasher._compute_file_hash

    def spy(path, algorithm, cancel_check):
        calls.append(path)
        return real(path, algorithm, cancel_check)
    monkeypatch.setattr(hasher, "_compute_file_hash", spy)
    return calls


def _single_tree(root):
    _write(root / "b.txt", b"same", 2000)
    _write(root / "a.txt", b"same", 3000)
    _write(root / "sub" / "deeper" / "c.txt", b"same", 1000)
    _write(root / "unique.txt", b"one of a kind")
    _write(root / "samesize.txt", b"diff")          # same size as "same", different content


def test_single_folder_ranks_and_moves(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    res = dd.scan(str(src), algorithm="md5")

    assert len(res.groups) == 1
    (h, entries), = res.groups.items()
    assert len(entries) == 3
    assert res.primary_map[h].path == str(src / "a.txt")          # First (alphabetical)
    assert sorted(os.path.basename(e.path) for _, e in res.to_remove) == ["b.txt", "c.txt"]
    assert res.total_files == 5 and res.unique_count == 3

    results, total, unique, moved = dd.execute(res, str(src))
    assert moved == 2
    assert (src / "a.txt").exists() and not (src / "b.txt").exists()
    assert sorted(os.listdir(src / "Dupes")) == ["b.txt", "c.txt"]
    assert (src / "samesize.txt").exists() and (src / "unique.txt").exists()


@pytest.mark.parametrize("rule,kept", [("Oldest", "c.txt"), ("Newest", "a.txt"),
                                       ("Shortest path", "a.txt"), ("First (alphabetical)", "a.txt")])
def test_keep_rules_rerank_without_rehashing(tmp_path, dd, hash_calls, rule, kept):
    src = tmp_path / "src"
    _single_tree(src)
    res = dd.scan(str(src))
    n = len(hash_calls)
    res2 = dd.rescan_keep_rule(res, rule)
    assert len(hash_calls) == n
    (h, primary), = res2.primary_map.items()
    assert os.path.basename(primary.path) == kept
    assert primary.path not in {e.path for _, e in res2.to_remove}
    assert len(res2.to_remove) == 2


def test_rescan_reuses_cache_and_rehashes_changed(tmp_path, dd, hash_calls):
    src = tmp_path / "src"
    _single_tree(src)
    dd.scan(str(src))
    assert len(hash_calls) == 4                     # 3 x "same" + samesize; unique-size file never hashed

    hash_calls.clear()
    dd.scan(str(src))
    assert hash_calls == []                         # everything cached

    _write(src / "samesize.txt", b"same", 5000)     # content + mtime change -> stale hash dropped
    hash_calls.clear()
    res = dd.scan(str(src))
    assert hash_calls == [str(src / "samesize.txt")]
    assert len(res.to_remove) == 3


def test_algorithms_cached_separately(tmp_path, dd, hash_calls):
    src = tmp_path / "src"
    _single_tree(src)
    dd.scan(str(src), algorithm="md5")
    hash_calls.clear()
    res = dd.scan(str(src), algorithm="blake2b")
    assert len(hash_calls) == 4
    (h, _), = res.groups.items()
    assert len(h) == 128                            # blake2b hex digest
    assert dd.cache_stats()["hashes"] == 8


def test_dupes_folder_and_db_never_scanned(tmp_path):
    src = tmp_path / "src"
    _single_tree(src)
    _write(src / "Dupes" / "old.txt", b"same")
    d = FileDeduplicator(src / "hashes.db", max_workers=2)     # DB inside the scanned folder
    res = d.scan(str(src))
    paths = {e.path for es in res.groups.values() for e in es}
    assert not any("Dupes" in p or "hashes.db" in p for p in paths)
    assert res.total_files == 5


def test_execute_forgets_moved_rows_and_prune_drops_deleted(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    res = dd.scan(str(src))
    assert dd.cache_stats()["files"] == 5
    dd.execute(res, str(src))
    assert dd.cache_stats()["files"] == 3           # moved b.txt, c.txt forgotten

    (src / "unique.txt").unlink()                   # deleted outside the app
    dd.scan(str(src))
    assert dd.cache_stats()["files"] == 2           # pruned on the next recursive scan


def test_permanent_delete(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    res = dd.scan(str(src))
    _, _, _, moved = dd.execute(res, str(src), permanent_delete=True)
    assert moved == 2
    assert not (src / "Dupes").exists()
    assert sorted(p.name for p in src.rglob("*.txt")) == ["a.txt", "samesize.txt", "unique.txt"]


def test_non_recursive_ignores_subfolders(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    res = dd.scan(str(src), recursive=False)
    assert res.total_files == 4
    assert sorted(os.path.basename(e.path) for _, e in res.to_remove) == ["b.txt"]


def test_compare_removes_only_target_matches(tmp_path, dd):
    a, b = tmp_path / "A", tmp_path / "B"
    _write(a / "x.bin", b"xxxx")
    _write(a / "copy_of_x.bin", b"xxxx")            # dupes inside A are never touched
    _write(a / "y.bin", b"yyyyy")
    _write(b / "x1.bin", b"xxxx")
    _write(b / "nested" / "x2.bin", b"xxxx")
    _write(b / "w1.bin", b"wwwwww")                 # duplicated inside B only: not a match
    _write(b / "w2.bin", b"wwwwww")
    _write(b / "z.bin", b"zzzzz")                   # same size as y, different content

    res = dd.scan_compare(str(a), str(b))
    assert res.compare_mode
    assert sorted(os.path.basename(e.path) for _, e in res.to_remove) == ["x1.bin", "x2.bin"]
    (h, primary), = res.primary_map.items()
    assert os.path.dirname(primary.path) == str(a)
    assert {os.path.dirname(e.path) for e in res.groups[h]} <= {str(b), str(b / "nested")}
    assert res.total_files == 5

    _, _, _, moved = dd.execute_compare(res, str(b))
    assert moved == 2
    assert sorted(p.name for p in a.iterdir()) == ["copy_of_x.bin", "x.bin", "y.bin"]
    assert sorted(os.listdir(b / "Dupes")) == ["x1.bin", "x2.bin"]
    assert (b / "w1.bin").exists() and (b / "w2.bin").exists() and (b / "z.bin").exists()


def test_compare_refuses_overlapping_folders(tmp_path, dd):
    a = tmp_path / "A"
    _write(a / "inner" / "f.txt", b"f")
    with pytest.raises(ValueError, match="overlap"):
        dd.scan_compare(str(a), str(a / "inner"))
    with pytest.raises(ValueError, match="overlap"):
        dd.scan_compare(str(a / "inner"), str(a))


def test_csv_report_includes_reference_primary(tmp_path, dd):
    a, b = tmp_path / "A", tmp_path / "B"
    _write(a / "x.bin", b"xxxx")
    _write(b / "x1.bin", b"xxxx")
    res = dd.scan_compare(str(a), str(b))
    results, *_ = dd.execute_compare(res, str(b))
    out = tmp_path / "r.csv"
    hasher.write_csv_report(str(out), res.groups, res.primary_map, results)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [(r["role"], os.path.basename(r["path"])) for r in rows] == [("primary", "x.bin"), ("duplicate", "x1.bin")]
    assert rows[1]["action"].startswith("moved to")


def test_cancel_during_hashing_keeps_finished_hashes(tmp_path, db, hash_calls):
    db.parent.mkdir()
    src = tmp_path / "src"
    for i in range(20):
        _write(src / f"f{i:02d}.txt", b"dup")
    state = {"cancel": False}
    d = FileDeduplicator(db, max_workers=1, cancel_check=lambda: state["cancel"],
                         progress_callback=lambda c, t, f: state.update(cancel=f.startswith("Hashing 5/")))
    res = d.scan(str(src))
    assert res.groups == {} and res.to_remove == []
    saved = d.cache_stats()["hashes"]
    assert 5 <= saved < 20

    hash_calls.clear()
    res = FileDeduplicator(db, max_workers=2).scan(str(src))
    assert len(hash_calls) == 20 - saved            # only the unfinished ones
    assert len(res.to_remove) == 19


def test_clear_cache(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    dd.scan(str(src))
    dd.clear_cache()
    assert dd.cache_stats() == {"files": 0, "hashes": 0}


def test_recycle_bin_and_system_folders_skipped(tmp_path, dd):
    src = tmp_path / "src"
    _write(src / "a.jpg", b"pic")
    _write(src / "$RECYCLE.BIN" / "S-1-5-21-1" / "$IABC.jpg", b"pic")
    _write(src / "RECYCLER" / "x.jpg", b"pic")
    _write(src / "System Volume Information" / "y.jpg", b"pic")
    _write(src / "keep" / "b.jpg", b"pic")
    res = dd.scan(str(src))
    assert res.total_files == 2
    assert [os.path.basename(e.path) for _, e in res.to_remove] == ["b.jpg"]


def test_migration_forgets_recycle_bin_rows(tmp_path):
    import sqlite3
    import hash_db
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(hash_db.SCHEMA_V1)
    conn.execute("PRAGMA user_version = 1")
    conn.executemany("INSERT INTO files(path, size, mtime) VALUES (?, 1, 0)",
                     [(r"M:\$RECYCLE.BIN\S-1-5-21-402136527\$ID4BDC7.jpg",),
                      (r"M:\System Volume Information\tracking.log",),
                      (r"M:\Photos\keep.jpg",)])
    conn.commit()
    conn.close()
    conn = hash_db.connect(path)
    assert [r[0] for r in conn.execute("SELECT path FROM files")] == [r"M:\Photos\keep.jpg"]
    conn.close()


def test_max_size_ignores_big_files_but_keeps_their_cache(tmp_path, dd, hash_calls):
    src = tmp_path / "src"
    _write(src / "small1.jpg", b"s" * 100)
    _write(src / "small2.jpg", b"s" * 100)
    _write(src / "model1.safetensors", b"m" * 5000)
    _write(src / "model2.safetensors", b"m" * 5000)

    res = dd.scan(str(src), max_size=1000)
    assert len(hash_calls) == 2                        # big files never hashed
    assert [os.path.basename(e.path) for _, e in res.to_remove] == ["small2.jpg"]
    assert res.total_files == 2

    res2 = dd.rescan_keep_rule(res, "Newest")          # limit survives a re-rank
    assert all(e.size <= 1000 for _, e in res2.to_remove)

    hash_calls.clear()
    res = dd.scan(str(src))                            # no limit: only the big ones need hashing
    assert len(hash_calls) == 2
    assert len(res.to_remove) == 2

    hash_calls.clear()
    res = dd.scan(str(src), max_size=1000)             # limit back on: big rows kept in cache, ignored
    assert hash_calls == []
    assert len(res.to_remove) == 1
    assert dd.cache_stats()["hashes"] == 4


def test_max_size_in_compare_mode(tmp_path, dd):
    a, b = tmp_path / "A", tmp_path / "B"
    _write(a / "big.bin", b"b" * 5000)
    _write(a / "pic.jpg", b"p" * 10)
    _write(b / "big copy.bin", b"b" * 5000)
    _write(b / "pic copy.jpg", b"p" * 10)
    res = dd.scan_compare(str(a), str(b), max_size=1000)
    assert [os.path.basename(e.path) for _, e in res.to_remove] == ["pic copy.jpg"]
    assert res.total_files == 1


def test_file_types_only_dedupes_selected_types(tmp_path, dd, hash_calls):
    src = tmp_path / "src"
    _write(src / "a.jpg", b"img")
    _write(src / "copy" / "a.JPG", b"img")              # extension match is case-insensitive
    _write(src / "m1.safetensors", b"mod")
    _write(src / "m2.safetensors", b"mod")
    _write(src / "d1.json", b"dat")
    _write(src / "d2.json", b"dat")

    res = dd.scan(str(src), file_types=("Images",))
    assert len(hash_calls) == 2                          # models + json never hashed
    assert [os.path.basename(e.path) for _, e in res.to_remove] == ["a.JPG"]
    assert res.total_files == 2

    res2 = dd.rescan_keep_rule(res, "Shortest path")     # filter survives a re-rank
    assert len(res2.to_remove) == 1 and res2.to_remove[0][1].path.lower().endswith(".jpg")

    hash_calls.clear()
    res = dd.scan(str(src), file_types=("Images", "Data"))
    assert len(hash_calls) == 2                          # only the json pair is new work
    assert sorted(os.path.basename(e.path) for _, e in res.to_remove) == ["a.JPG", "d2.json"]


def test_file_types_extra_mask_and_all(tmp_path, dd):
    src = tmp_path / "src"
    _write(src / "x.psd", b"psd")
    _write(src / "y.psd", b"psd")
    _write(src / "a.txt", b"txt")
    _write(src / "b.txt", b"txt")
    res = dd.scan(str(src), file_types=("*.psd",))
    assert [os.path.basename(e.path) for _, e in res.to_remove] == ["y.psd"]
    res = dd.scan(str(src), file_types=("Images",))      # .psd is in the Images preset
    assert len(res.to_remove) == 1
    res = dd.scan(str(src))                              # nothing selected = every type
    assert len(res.to_remove) == 2


def test_file_types_in_compare_mode(tmp_path, dd):
    a, b = tmp_path / "A", tmp_path / "B"
    _write(a / "p.png", b"png")
    _write(a / "m.safetensors", b"safe")
    _write(b / "p copy.png", b"png")
    _write(b / "m copy.safetensors", b"safe")
    res = dd.scan_compare(str(a), str(b), file_types=("Images",))
    assert [os.path.basename(e.path) for _, e in res.to_remove] == ["p copy.png"]


def _make_read_only(path):
    import stat
    os.chmod(path, stat.S_IREAD)


def test_read_only_delete_fails_with_clear_message(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    for p in (src / "b.txt", src / "sub" / "deeper" / "c.txt"):
        _make_read_only(p)
    assert hasher.is_read_only(str(src / "b.txt"))
    assert hasher.count_read_only([str(src / "a.txt"), str(src / "b.txt")]) == 1
    msgs = []
    d = FileDeduplicator(dd.db_path, status_callback=msgs.append)
    res = d.scan(str(src))
    results, _, _, deleted = d.execute(res, str(src), permanent_delete=True)
    assert deleted == 0
    assert (src / "b.txt").exists()
    assert any("read-only" in m and "Clear read-only flag" in m for m in msgs)
    assert all("read-only" in r.error_message for r in results if r.is_duplicate)


def test_read_only_cleared_then_deleted(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    for p in (src / "b.txt", src / "sub" / "deeper" / "c.txt"):
        _make_read_only(p)
    _make_read_only(src / "a.txt")                       # the kept copy stays read-only
    msgs = []
    d = FileDeduplicator(dd.db_path, status_callback=msgs.append)
    res = d.scan(str(src))
    _, _, _, deleted = d.execute(res, str(src), permanent_delete=True, clear_read_only=True)
    assert deleted == 2
    assert not (src / "b.txt").exists()
    assert hasher.is_read_only(str(src / "a.txt"))
    assert any("Cleared the read-only flag on 2" in m for m in msgs)


def test_read_only_files_move_without_clearing(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    _make_read_only(src / "b.txt")
    res = dd.scan(str(src))
    _, _, _, moved = dd.execute(res, str(src))           # same-drive move = rename, allowed
    assert moved == 2
    assert (src / "Dupes" / "b.txt").exists()


def test_read_only_paths_survive_rerank(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    res = dd.scan(str(src))
    res.read_only_paths = frozenset({str(src / "b.txt")})
    assert dd.rescan_keep_rule(res, "Oldest").read_only_paths == res.read_only_paths


# ---------- resume after cancel ----------

def _resume_tree(root):
    for d in range(6):
        for f in range(3):
            _write(root / f"dir{d}" / f"f{f}.jpg", f"content{f}".encode())   # 6 copies of each of 3 files


@pytest.fixture
def scandirs(monkeypatch):
    """Record every folder listed, to prove a resumed scan skips work already done."""
    seen = []
    real = os.scandir

    def spy(path):
        seen.append(path)
        return real(path)
    monkeypatch.setattr(hasher.os, "scandir", spy)
    return seen


def _cancel_after(n):
    state = {"calls": 0}

    def check():
        state["calls"] += 1
        return state["calls"] > n
    return check


def test_resume_after_cancel_while_listing(tmp_path, db, scandirs):
    db.parent.mkdir()
    src = tmp_path / "src"
    _resume_tree(src)
    d = FileDeduplicator(db, cancel_check=_cancel_after(3))
    d.checkpoint_files = 1                               # save after every folder
    assert d.scan(str(src), resume=True).to_remove == []
    job = d.pending_job()
    assert job["phase"] == "listing"
    import hash_db
    conn = hash_db.connect(db)
    listed = sum(hash_db.listing_counts(conn).values())
    queued = len(hash_db.walk_queue(conn))
    conn.close()
    assert 0 < listed < 18 and queued > 0
    first_pass = len(scandirs)

    scandirs.clear()
    res = FileDeduplicator(db).scan(str(src), resume=True)
    assert len(scandirs) == 7 - first_pass               # root + 6 dirs, minus those already listed
    assert res.total_files == 18
    assert len(res.to_remove) == 15
    assert FileDeduplicator(db).pending_job()["phase"] == "review"


def test_resume_after_cancel_while_hashing_skips_listing(tmp_path, db, scandirs, hash_calls):
    db.parent.mkdir()
    src = tmp_path / "src"
    _resume_tree(src)
    state = {"cancel": False}
    d = FileDeduplicator(db, max_workers=1, cancel_check=lambda: state["cancel"],
                         progress_callback=lambda c, t, f: state.update(cancel=f.startswith("Hashing 4/")))
    d.scan(str(src), resume=True)
    assert d.pending_job()["phase"] == "hashing"
    saved = FileDeduplicator(db).cache_stats()["hashes"]
    assert 4 <= saved < 18

    scandirs.clear()
    hash_calls.clear()
    res = FileDeduplicator(db, max_workers=2).scan(str(src), resume=True)
    assert scandirs == []                                # listing was finished: not redone
    assert len(hash_calls) == 18 - saved                 # only the files not hashed yet
    assert len(res.to_remove) == 15


def test_resume_after_cancel_while_applying(tmp_path, db, scandirs, hash_calls):
    db.parent.mkdir()
    src = tmp_path / "src"
    _resume_tree(src)
    res = FileDeduplicator(db).scan(str(src), resume=True)
    d = FileDeduplicator(db, cancel_check=_cancel_after(5))
    _, _, _, moved = d.execute(res, str(src))
    assert 0 < moved < 15
    assert d.pending_job()["phase"] == "applying"

    scandirs.clear()
    hash_calls.clear()
    res = FileDeduplicator(db).scan(str(src), resume=True)
    assert scandirs == [] and hash_calls == []           # straight back to the remaining duplicates
    assert len(res.to_remove) == 15 - moved
    _, _, _, moved2 = FileDeduplicator(db).execute(res, str(src))
    assert moved + moved2 == 15
    assert FileDeduplicator(db).pending_job() is None    # finished: nothing to resume
    assert len(os.listdir(src / "Dupes")) == 15


def test_resume_ignored_for_a_different_folder(tmp_path, db):
    db.parent.mkdir()
    a, b = tmp_path / "a", tmp_path / "b"
    _resume_tree(a)
    _write(b / "x.jpg", b"x")
    _write(b / "y.jpg", b"x")
    FileDeduplicator(db, cancel_check=_cancel_after(2)).scan(str(a), resume=True)
    res = FileDeduplicator(db).scan(str(b), resume=True)
    assert res.total_files == 2 and len(res.to_remove) == 1


def test_apply_skips_changed_duplicate_and_missing_kept_copy(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)                                    # a.txt kept; b.txt, sub/deeper/c.txt dupes
    _write(src / "x1.bin", b"xx")
    _write(src / "x2.bin", b"xx")                        # x1 kept, x2 dupe
    res = dd.scan(str(src))
    _write(src / "b.txt", b"same", 9999)                 # same content, new mtime: changed since scan
    (src / "x1.bin").unlink()                            # kept copy gone
    results, _, _, moved = dd.execute(res, str(src))
    assert moved == 1                                    # only c.txt
    assert (src / "b.txt").exists() and (src / "x2.bin").exists()
    errors = {os.path.basename(r.source_path): r.error_message for r in results if r.error_message}
    assert "changed since it was scanned" in errors["b.txt"]
    assert "kept copy is gone" in errors["x2.bin"]


def test_review_cancel_and_clear_cache_end_the_job(tmp_path, dd):
    src = tmp_path / "src"
    _single_tree(src)
    dd.scan(str(src), resume=True, job_extra={"source": str(src), "permanent_delete": True})
    job = dd.pending_job()
    assert job["phase"] == "review" and job["settings"]["permanent_delete"] is True
    dd.finish_job()
    assert dd.pending_job() is None
    dd.scan(str(src), resume=True)
    dd.clear_cache()
    assert dd.pending_job() is None
