"""SQLite hash cache and duplicate ranking for File Hash Dedupe.

Every file the app lists is one row in `files` (the full path is UNIQUE), and its hash for
each algorithm is one row in `hashes`. `run_files` marks which rows belong to the current
scan: side 0 = the source folder (or reference folder A), side 1 = target folder B.

Which copy survives is decided in SQL, the same way as Burn List Creator's file_ranked view:
ROW_NUMBER() OVER (PARTITION BY hash ...) gives every copy of a file a rank, rank 1 is kept
and every rank > 1 is a duplicate to move or delete.

Because hashes persist between runs, a rescan only hashes files that are new or whose
size / modified time changed since they were last hashed.
"""
import datetime
import json
import os
import sqlite3

MIN_SQLITE = (3, 25)          # window functions (upsert needs 3.24)
BATCH = 500

SCHEMA_V1 = """
CREATE TABLE files (
    id     INTEGER PRIMARY KEY,
    path   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    size   INTEGER NOT NULL,
    mtime  REAL NOT NULL
);
CREATE INDEX idx_files_size ON files(size);

CREATE TABLE hashes (
    file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    algo      TEXT NOT NULL,
    hash      TEXT NOT NULL,
    hashed_at TEXT,
    PRIMARY KEY (file_id, algo)
);
CREATE INDEX idx_hashes_hash ON hashes(algo, hash);

CREATE TABLE run_files (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    side    INTEGER NOT NULL DEFAULT 0
);
"""

SCHEMA_V2 = """
DELETE FROM files
WHERE instr(lower(path), '\\$recycle.bin\\') > 0
   OR instr(lower(path), '\\recycler\\') > 0
   OR instr(lower(path), '\\system volume information\\') > 0;
"""                           # v1.4.2: system folders are no longer scanned; forget rows already listed

SCHEMA_V3 = """
CREATE TABLE listing (                    -- files found by the walk in progress (resumable)
    path  TEXT PRIMARY KEY COLLATE NOCASE,
    size  INTEGER NOT NULL,
    mtime REAL NOT NULL,
    side  INTEGER NOT NULL
);
CREATE TABLE walk_queue (                 -- folders the walk in progress has still to list
    dir  TEXT PRIMARY KEY COLLATE NOCASE,
    side INTEGER NOT NULL
);
CREATE TABLE job (                        -- the run in progress: settings + step reached
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    settings TEXT NOT NULL,
    phase    TEXT NOT NULL,
    updated  TEXT
);
"""                           # v1.5.1: cancel / crash resumes where it stopped

MIGRATIONS = [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3]      # index i upgrades user_version i -> i+1

# Keep rule -> ORDER BY inside the ROW_NUMBER() window (first row = the copy that is kept).
# Only these fixed strings are ever put into the SQL text.
KEEP_ORDER = {
    "First (alphabetical)": "f.path",
    "Oldest": "f.mtime ASC, f.path",
    "Newest": "f.mtime DESC, f.path",
    "Shortest path": "length(f.path), f.path",
}


def connect(path) -> sqlite3.Connection:
    """Open (creating/migrating) the database. Connections are thread-affine: open one per
    thread that needs it."""
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise RuntimeError(f"SQLite {sqlite3.sqlite_version} is too old; need >= 3.25 for window functions")
    conn = sqlite3.connect(os.fspath(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    set_type_filter(conn, None)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for v in range(version, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[v])
        conn.execute(f"PRAGMA user_version = {v + 1}")
    conn.commit()
    return conn


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def set_type_filter(conn, matcher=None) -> None:
    """Register the SQL function type_ok(path) on this connection: 1 when the file name matches
    the selected file types (filetypes.Matcher), always 1 when matcher is None (all files).
    Like the size limit it only filters queries - every file stays listed and cached."""
    if matcher is None:
        conn.create_function("type_ok", 1, lambda path: 1, deterministic=True)
    else:
        conn.create_function("type_ok", 1, lambda path: 1 if matcher(os.path.basename(path)) else 0,
                             deterministic=True)


# ── listing ───────────────────────────────────────────────────────────────────

def begin_run(conn, folders) -> None:
    """Start a fresh scan: forget the previous run's membership and listing progress, and queue
    the root folders [(abs_path, side)] for listing."""
    conn.execute("DELETE FROM run_files")
    conn.execute("DELETE FROM listing")
    conn.execute("DELETE FROM walk_queue")
    conn.executemany("INSERT OR IGNORE INTO walk_queue(dir, side) VALUES (?,?)", list(folders))
    conn.commit()


def walk_queue(conn):
    """Folders still to be listed [(dir, side)] - a resumed scan carries on from here."""
    return [(r["dir"], r["side"]) for r in conn.execute("SELECT dir, side FROM walk_queue ORDER BY rowid")]


def checkpoint_walk(conn, entries, pending_dirs) -> None:
    """Save listing progress in one transaction: walked files [(path, size, mtime, side)] go into
    `listing` (first side wins) and the walk queue becomes `pending_dirs` [(dir, side)].
    A cancelled or crashed listing resumes from the last checkpoint."""
    for i in range(0, len(entries), BATCH):
        conn.executemany("INSERT OR IGNORE INTO listing(path, size, mtime, side) VALUES (?,?,?,?)",
                         entries[i:i + BATCH])
    conn.execute("DELETE FROM walk_queue")
    conn.executemany("INSERT OR IGNORE INTO walk_queue(dir, side) VALUES (?,?)", list(pending_dirs))
    conn.commit()


def listing_counts(conn) -> dict:
    """side -> files listed so far"""
    return {r["side"]: r["n"] for r in conn.execute("SELECT side, COUNT(*) AS n FROM listing GROUP BY side")}


def apply_listing(conn) -> dict:
    """Merge the finished listing into `files`, all in SQL:
    new path -> insert; size or mtime changed -> drop its now-stale hashes and update;
    then every listed file joins `run_files`. Returns {new, changed, unchanged}."""
    counts = conn.execute("""
        SELECT COALESCE(SUM(f.id IS NULL), 0) AS new,
               COALESCE(SUM(f.id IS NOT NULL AND (f.size <> s.size OR f.mtime <> s.mtime)), 0) AS changed,
               COUNT(*) AS listed
        FROM listing s LEFT JOIN files f ON f.path = s.path""").fetchone()
    conn.execute("""
        DELETE FROM hashes WHERE file_id IN (
            SELECT f.id FROM files f JOIN listing s ON s.path = f.path
            WHERE f.size <> s.size OR f.mtime <> s.mtime)""")
    conn.execute("""
        INSERT INTO files(path, size, mtime)
        SELECT path, size, mtime FROM listing WHERE true
        ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime
        WHERE files.size <> excluded.size OR files.mtime <> excluded.mtime""")
    conn.execute("""
        INSERT OR IGNORE INTO run_files(file_id, side)
        SELECT f.id, s.side FROM listing s JOIN files f ON f.path = s.path""")
    conn.execute("DELETE FROM listing")
    conn.execute("DELETE FROM walk_queue")
    conn.commit()
    return {"new": counts["new"], "changed": counts["changed"],
            "unchanged": counts["listed"] - counts["new"] - counts["changed"]}


# ── resumable job ─────────────────────────────────────────────────────────────
# One row: the settings of the run in progress and the step it reached
# (listing -> hashing -> review -> applying). No row = nothing to resume.

RESUMABLE_PHASES = ("listing", "hashing", "review", "applying")


def get_job(conn):
    row = conn.execute("SELECT settings, phase, updated FROM job WHERE id = 1").fetchone()
    if row is None:
        return None
    return {"settings": json.loads(row["settings"]), "phase": row["phase"], "updated": row["updated"]}


def set_job(conn, settings: dict, phase: str) -> None:
    conn.execute("INSERT OR REPLACE INTO job(id, settings, phase, updated) VALUES (1, ?, ?, ?)",
                 (json.dumps(settings), phase, _now()))
    conn.commit()


def set_phase(conn, phase: str) -> None:
    conn.execute("UPDATE job SET phase = ?, updated = ? WHERE id = 1", (phase, _now()))
    conn.commit()


def clear_job(conn) -> None:
    """The run finished (or was deliberately abandoned): nothing to resume."""
    conn.execute("DELETE FROM job")
    conn.execute("DELETE FROM listing")
    conn.execute("DELETE FROM walk_queue")
    conn.commit()


def prune_folder(conn, folder: str) -> int:
    """After a complete recursive listing of `folder`: forget rows under it that were not
    listed (the file is gone). Keeps the cache from growing forever."""
    prefix = folder if folder.endswith(os.sep) else folder + os.sep
    cur = conn.execute("""
        DELETE FROM files
        WHERE substr(path, 1, ?) = ? COLLATE NOCASE
          AND id NOT IN (SELECT file_id FROM run_files)""", (len(prefix), prefix))
    conn.commit()
    return cur.rowcount


# ── hashing ───────────────────────────────────────────────────────────────────

def candidates(conn, algo: str, compare: bool, max_size: int = 0):
    """Size pre-filter, in SQL: files of this run whose size is shared with another file
    (in compare mode: shared between side A and side B). `cached` = already hashed with algo.
    max_size > 0 leaves out files bigger than that many bytes, and type_ok() leaves out file types
    that are not selected (both stay listed and cached)."""
    # Two narrow temp tables first (ids + sizes only, no path strings): grouping a million sizes
    # this way is ~8x faster than a window function or IN-subquery over the full rows
    args = {"algo": algo, "compare": int(compare), "max_size": int(max_size)}
    conn.execute("DROP TABLE IF EXISTS temp.eligible")
    conn.execute("DROP TABLE IF EXISTS temp.shared_sizes")
    conn.execute("""
        CREATE TEMP TABLE eligible AS
        SELECT r.file_id AS id, r.side, f.size
        FROM run_files r JOIN files f ON f.id = r.file_id
        WHERE (:max_size = 0 OR f.size <= :max_size) AND type_ok(f.path)""", args)
    conn.execute("""
        CREATE TEMP TABLE shared_sizes AS
        SELECT size FROM temp.eligible GROUP BY size
        HAVING COUNT(*) > 1 AND (:compare = 0 OR (MIN(side) = 0 AND MAX(side) = 1))""", args)
    conn.execute("CREATE UNIQUE INDEX temp.idx_shared_sizes ON shared_sizes(size)")
    rows = conn.execute("""
        SELECT f.id, f.path, f.size, e.side,
               EXISTS (SELECT 1 FROM hashes h WHERE h.file_id = f.id AND h.algo = :algo) AS cached
        FROM temp.eligible e JOIN files f ON f.id = e.id
        WHERE e.size IN (SELECT size FROM temp.shared_sizes)
        ORDER BY f.path""", args).fetchall()
    conn.execute("DROP TABLE temp.eligible")
    conn.execute("DROP TABLE temp.shared_sizes")
    return rows


def save_hash(conn, file_id: int, algo: str, digest: str) -> None:
    conn.execute("INSERT OR REPLACE INTO hashes(file_id, algo, hash, hashed_at) VALUES (?,?,?,?)",
                 (file_id, algo, digest, _now()))


def run_count(conn, side=None, max_size: int = 0) -> int:
    """Files in this run (optionally one side), counting only those within max_size when it is set."""
    return conn.execute("""
        SELECT COUNT(*) FROM run_files r JOIN files f ON f.id = r.file_id
        WHERE (:side IS NULL OR r.side = :side) AND (:max_size = 0 OR f.size <= :max_size)
          AND type_ok(f.path)""",
        {"side": side, "max_size": int(max_size)}).fetchone()[0]


def excluded_counts(conn, max_size: int) -> dict:
    """Files in this run left out: {'type': not a selected file type, 'size': selected type but
    bigger than max_size bytes}."""
    row = conn.execute("""
        SELECT COALESCE(SUM(NOT ok), 0) AS by_type,
               COALESCE(SUM(ok AND :max_size > 0 AND size > :max_size), 0) AS by_size
        FROM (SELECT type_ok(f.path) AS ok, f.size
              FROM run_files r JOIN files f ON f.id = r.file_id)""", {"max_size": int(max_size)}).fetchone()
    return {"type": row["by_type"], "size": row["by_size"]}


# ── ranking ───────────────────────────────────────────────────────────────────

def ranked(conn, algo: str, keep_rule: str, compare: bool, max_size: int = 0):
    """Every copy in a duplicate group, ranked with ROW_NUMBER(). `remove` = 1 marks the rows
    to move/delete: rank > 1 in single-folder mode; in compare mode only target-side (B) rows,
    and rank 1 is always a reference (A) file because side sorts first.
    Compare mode returns only groups present on both sides: the kept A file plus every B copy."""
    order = KEEP_ORDER.get(keep_rule, KEEP_ORDER["First (alphabetical)"])
    return conn.execute(f"""
        WITH ranked AS (
            SELECT f.id, f.path, f.size, f.mtime, h.hash, r.side,
                   ROW_NUMBER() OVER (PARTITION BY h.hash, f.size ORDER BY r.side, {order}) AS dup_rank,
                   COUNT(*)    OVER (PARTITION BY h.hash, f.size) AS copies,
                   MIN(r.side) OVER (PARTITION BY h.hash, f.size) AS min_side,
                   MAX(r.side) OVER (PARTITION BY h.hash, f.size) AS max_side
            FROM run_files r
            JOIN files f  ON f.id = r.file_id
            JOIN hashes h ON h.file_id = f.id AND h.algo = :algo
            WHERE (:max_size = 0 OR f.size <= :max_size) AND type_ok(f.path))
        SELECT id, path, size, mtime, hash, side, dup_rank, copies,
               CASE WHEN dup_rank > 1 AND side = :remove_side THEN 1 ELSE 0 END AS remove
        FROM ranked
        WHERE copies > 1
          AND (:compare = 0 OR (min_side = 0 AND max_side = 1 AND (dup_rank = 1 OR side = 1)))
        ORDER BY size DESC, hash, dup_rank""",
        {"algo": algo, "compare": int(compare), "remove_side": 1 if compare else 0,
         "max_size": int(max_size)}).fetchall()


# ── upkeep ────────────────────────────────────────────────────────────────────

def forget(conn, file_ids) -> None:
    """Drop rows for files that were moved to Dupes or deleted (their path no longer exists)."""
    ids = [(i,) for i in file_ids]
    for i in range(0, len(ids), BATCH):
        conn.executemany("DELETE FROM files WHERE id = ?", ids[i:i + BATCH])
    conn.commit()


def stats(conn) -> dict:
    return {"files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "hashes": conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]}


def clear(conn) -> None:
    """Forget every cached file and hash (the next scan hashes everything again)."""
    clear_job(conn)
    conn.execute("DELETE FROM run_files")
    conn.execute("DELETE FROM hashes")
    conn.execute("DELETE FROM files")
    conn.commit()
    conn.execute("VACUUM")
