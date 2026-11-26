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

MIGRATIONS = [SCHEMA_V1]      # index i upgrades user_version i -> i+1

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
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for v in range(version, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[v])
        conn.execute(f"PRAGMA user_version = {v + 1}")
    conn.commit()
    return conn


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── listing ───────────────────────────────────────────────────────────────────

def begin_run(conn) -> None:
    """Start a new scan: forget the previous run's membership and the listing scratch table."""
    conn.execute("DELETE FROM run_files")
    conn.execute("""CREATE TEMP TABLE IF NOT EXISTS seen (
                        path  TEXT PRIMARY KEY COLLATE NOCASE,
                        size  INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        side  INTEGER NOT NULL)""")
    conn.execute("DELETE FROM temp.seen")
    conn.commit()


def add_listing(conn, entries, side: int) -> None:
    """Stage walked files [(full_path, size, mtime)] for this run. A path already staged keeps
    its first side (so a file can only ever be in the run once)."""
    rows = [(p, s, m, side) for p, s, m in entries]
    for i in range(0, len(rows), BATCH):
        conn.executemany("INSERT OR IGNORE INTO temp.seen(path, size, mtime, side) VALUES (?,?,?,?)",
                         rows[i:i + BATCH])
    conn.commit()


def apply_listing(conn) -> dict:
    """Merge the staged listing into `files`, all in SQL:
    new path -> insert; size or mtime changed -> drop its now-stale hashes and update;
    then every listed file joins `run_files`. Returns {new, changed, unchanged}."""
    counts = conn.execute("""
        SELECT COALESCE(SUM(f.id IS NULL), 0) AS new,
               COALESCE(SUM(f.id IS NOT NULL AND (f.size <> s.size OR f.mtime <> s.mtime)), 0) AS changed,
               COUNT(*) AS listed
        FROM temp.seen s LEFT JOIN files f ON f.path = s.path""").fetchone()
    conn.execute("""
        DELETE FROM hashes WHERE file_id IN (
            SELECT f.id FROM files f JOIN temp.seen s ON s.path = f.path
            WHERE f.size <> s.size OR f.mtime <> s.mtime)""")
    conn.execute("""
        INSERT INTO files(path, size, mtime)
        SELECT path, size, mtime FROM temp.seen WHERE true
        ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime
        WHERE files.size <> excluded.size OR files.mtime <> excluded.mtime""")
    conn.execute("""
        INSERT OR IGNORE INTO run_files(file_id, side)
        SELECT f.id, s.side FROM temp.seen s JOIN files f ON f.path = s.path""")
    conn.execute("DELETE FROM temp.seen")
    conn.commit()
    return {"new": counts["new"], "changed": counts["changed"],
            "unchanged": counts["listed"] - counts["new"] - counts["changed"]}


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

def candidates(conn, algo: str, compare: bool):
    """Size pre-filter, in SQL: files of this run whose size is shared with another file
    (in compare mode: shared between side A and side B). `cached` = already hashed with algo."""
    return conn.execute("""
        WITH run AS (
            SELECT f.id, f.path, f.size, r.side
            FROM run_files r JOIN files f ON f.id = r.file_id),
        shared AS (
            SELECT size FROM run GROUP BY size
            HAVING COUNT(*) > 1 AND (:compare = 0 OR (MIN(side) = 0 AND MAX(side) = 1)))
        SELECT run.id, run.path, run.size, run.side,
               EXISTS (SELECT 1 FROM hashes h WHERE h.file_id = run.id AND h.algo = :algo) AS cached
        FROM run WHERE run.size IN (SELECT size FROM shared)
        ORDER BY run.path""", {"algo": algo, "compare": int(compare)}).fetchall()


def save_hash(conn, file_id: int, algo: str, digest: str) -> None:
    conn.execute("INSERT OR REPLACE INTO hashes(file_id, algo, hash, hashed_at) VALUES (?,?,?,?)",
                 (file_id, algo, digest, _now()))


def run_count(conn, side=None) -> int:
    if side is None:
        return conn.execute("SELECT COUNT(*) FROM run_files").fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM run_files WHERE side = ?", (side,)).fetchone()[0]


# ── ranking ───────────────────────────────────────────────────────────────────

def ranked(conn, algo: str, keep_rule: str, compare: bool):
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
            JOIN hashes h ON h.file_id = f.id AND h.algo = :algo)
        SELECT id, path, size, mtime, hash, side, dup_rank, copies,
               CASE WHEN dup_rank > 1 AND side = :remove_side THEN 1 ELSE 0 END AS remove
        FROM ranked
        WHERE copies > 1
          AND (:compare = 0 OR (min_side = 0 AND max_side = 1 AND (dup_rank = 1 OR side = 1)))
        ORDER BY size DESC, hash, dup_rank""",
        {"algo": algo, "compare": int(compare), "remove_side": 1 if compare else 0}).fetchall()


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
    conn.execute("DELETE FROM run_files")
    conn.execute("DELETE FROM hashes")
    conn.execute("DELETE FROM files")
    conn.commit()
    conn.execute("VACUUM")
