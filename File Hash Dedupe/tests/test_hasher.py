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
