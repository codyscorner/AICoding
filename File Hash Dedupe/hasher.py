"""File hashing and deduplication module for File Hash Dedupe.

The scan is SQLite-backed (see hash_db.py):
1. List every file (full path, size, modified time) into the database - one row per path
2. Size pre-filter in SQL: only files that share a size with another file can be duplicates
3. Hash those candidates in parallel, skipping any whose hash is already cached
4. Rank every copy of each hash with ROW_NUMBER() in SQL: rank 1 is kept, rank > 1 is removed
"""

import os
import csv
import hashlib
import shutil
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait

import hash_db


# Number of parallel workers for hashing (I/O bound, can use many)
MAX_WORKERS = 16

# Read buffer per hashing worker
BUFFER_SIZE = 1024 * 1024

# Folder duplicates are moved into; never scanned
DUPES_DIR = "Dupes"

# Hash algorithms offered in the UI (both are stdlib — no extra dependency)
ALGORITHMS = {"MD5": "md5", "BLAKE2b": "blake2b"}

# Rules for picking which copy of a duplicate group survives as primary (ORDER BY in hash_db)
KEEP_RULES = list(hash_db.KEEP_ORDER)

_LONG_PREFIX = "\\\\?\\"


def long_path(p: str) -> str:
    """Add the \\\\?\\ prefix to long absolute paths so Win32 APIs accept > 260 chars."""
    if os.name != "nt" or p.startswith(_LONG_PREFIX) or len(p) < 240:
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\"):                      # UNC share
        return _LONG_PREFIX + "UNC\\" + p[2:]
    return _LONG_PREFIX + p


def _inside(child: str, parent: str) -> bool:
    c, p = os.path.normcase(child), os.path.normcase(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


class _Cancelled(Exception):
    """Raised inside a hash when cancel is requested."""


@dataclass
class FileEntry:
    """A file in a duplicate group, as ranked by the database"""
    path: str
    size: int
    mtime: float
    file_hash: Optional[str] = None
    error: Optional[str] = None
    file_id: Optional[int] = None


@dataclass
class DedupeResult:
    """Result of a single file's dedupe operation"""
    source_path: str
    dest_path: Optional[str]
    file_hash: str
    is_duplicate: bool
    is_primary: bool
    moved: bool
    error_message: Optional[str] = None


@dataclass
class ScanResult:
    """Result of a scan pass: duplicate groups found, ready for preview or execution"""
    groups: Dict[str, List[FileEntry]]   # hash -> entries shown in the group (compare mode: target copies only)
    primary_map: Dict[str, FileEntry]    # hash -> rank-1 entry (kept, never moved)
    hash_errors: Dict[str, str]          # path -> error message
    total_files: int
    unique_count: int
    keep_rule: str
    to_remove: List[Tuple[str, FileEntry]] = field(default_factory=list)   # (hash, entry) for every rank > 1 row
    algorithm: str = "md5"
    compare_mode: bool = False


def _compute_file_hash(file_path: str, algorithm: str, cancel_check: Optional[Callable[[], bool]]) -> str:
    """Hex digest of a file's contents; cancel is checked once per buffer"""
    hasher = hashlib.new(algorithm)
    view = memoryview(bytearray(BUFFER_SIZE))
    with open(long_path(file_path), 'rb', buffering=0) as f:
        while True:
            if cancel_check and cancel_check():
                raise _Cancelled
            n = f.readinto(view)
            if not n:
                break
            hasher.update(view[:n])
    return hasher.hexdigest()


def write_csv_report(csv_path: str, groups: Dict[str, List[FileEntry]], primary_map: Dict[str, FileEntry],
                      results: Optional[List[DedupeResult]] = None) -> None:
    """Write a CSV report of duplicate groups, and the action taken per file if results are given"""
    action_by_path = {}
    if results:
        for r in results:
            if r.is_primary:
                action_by_path[r.source_path] = "kept"
            elif r.error_message:
                action_by_path[r.source_path] = f"error: {r.error_message}"
            elif r.moved and r.dest_path:
                action_by_path[r.source_path] = f"moved to {r.dest_path}"
            elif r.moved:
                action_by_path[r.source_path] = "deleted"

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["group_hash", "role", "path", "size_bytes", "action"])
        for file_hash, entries in groups.items():
            primary = primary_map[file_hash]
            rows = list(entries)
            if all(e.path != primary.path for e in rows):      # compare mode: the kept file is in folder A
                rows.insert(0, primary)
            for entry in rows:
                role = "primary" if entry.path == primary.path else "duplicate"
                default_action = "kept" if role == "primary" else "pending"
                action = action_by_path.get(entry.path, default_action)
                writer.writerow([file_hash, role, entry.path, entry.size, action])


class FileDeduplicator:
    """Finds and moves duplicate files, using a SQLite hash cache and ROW_NUMBER() ranking"""

    def __init__(
        self,
        db_path: str,
        status_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_workers: int = MAX_WORKERS
    ):
        self.db_path = os.fspath(db_path)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.max_workers = max(1, max_workers)
        db = os.path.normcase(os.path.abspath(self.db_path))
        self._db_files = {db, db + "-wal", db + "-shm", db + "-journal"}

    def _log_status(self, message: str) -> None:
        if self.status_callback:
            self.status_callback(message)

    def _report_progress(self, current: int, total: int, filename: str) -> None:
        if self.progress_callback:
            self.progress_callback(current, total, filename)

    def _cancelled(self) -> bool:
        return bool(self.cancel_check and self.cancel_check())

    # ---------- listing ----------

    def _walk(self, folder: str, recursive: bool, errors: Dict[str, str]) -> List[Tuple[str, int, float]]:
        """Every file under folder as (full_path, size, mtime). Skips Dupes folders, links and the
        app's own database files."""
        entries: List[Tuple[str, int, float]] = []
        stack = [folder]
        while stack and not self._cancelled():
            current = stack.pop()
            try:
                with os.scandir(long_path(current)) as it:
                    for e in it:
                        full = os.path.join(current, e.name)
                        try:
                            is_junction = getattr(e, "is_junction", None)
                            if e.is_symlink() or (is_junction and is_junction()):
                                continue                      # never follow links (loops)
                            if e.is_dir(follow_symlinks=False):
                                if recursive and e.name != DUPES_DIR:
                                    stack.append(full)
                            elif e.is_file(follow_symlinks=False):
                                if os.path.normcase(full) in self._db_files:
                                    continue
                                st = e.stat(follow_symlinks=False)
                                entries.append((full, st.st_size, st.st_mtime))
                                if len(entries) % 2000 == 0:
                                    self._report_progress(0, 100, f"Listing: {len(entries):,} files")
                        except OSError as ex:
                            errors[full] = str(ex)
            except OSError as ex:
                errors[current] = str(ex)
        return entries

    # ---------- hashing ----------

    def _hash_pending(self, conn, pending, algorithm: str, progress_start: int, progress_end: int) -> Dict[str, str]:
        """Hash the pending rows in parallel; this thread is the only DB writer. Hashes are
        committed in batches, so a cancelled scan keeps everything hashed so far."""
        errors: Dict[str, str] = {}
        total_files = len(pending)
        total_bytes = sum(r["size"] for r in pending) or 1
        if not pending:
            return errors

        done_files = 0
        done_bytes = 0
        since_commit = 0
        cancel_logged = False
        inflight = {}
        rows = iter(pending)

        def submit_more(pool):
            while len(inflight) < self.max_workers * 2 and not self._cancelled():
                row = next(rows, None)
                if row is None:
                    return
                inflight[pool.submit(_compute_file_hash, row["path"], algorithm, self.cancel_check)] = row

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            submit_more(pool)
            while inflight:
                done, _ = wait(inflight, timeout=0.25, return_when=FIRST_COMPLETED)
                for fut in done:
                    row = inflight.pop(fut)
                    name = os.path.basename(row["path"])
                    try:
                        digest = fut.result()
                    except _Cancelled:
                        continue
                    except OSError as e:
                        errors[row["path"]] = str(e)
                        self._log_status(f"Error: {name} - {e}")
                    else:
                        hash_db.save_hash(conn, row["id"], algorithm, digest)
                        since_commit += 1
                        if since_commit >= hash_db.BATCH:
                            conn.commit()
                            since_commit = 0
                    done_files += 1
                    done_bytes += row["size"]
                    progress = progress_start + int(done_bytes / total_bytes * (progress_end - progress_start))
                    self._report_progress(progress, 100, f"Hashing {done_files:,}/{total_files:,}: {name}")
                if self._cancelled() and not cancel_logged:
                    self._log_status("Cancellation requested...")
                    cancel_logged = True
                submit_more(pool)
        conn.commit()
        return errors

    # ---------- scan ----------

    def scan(self, source_folder: str, recursive: bool = True, algorithm: str = "md5",
             keep_rule: str = "First (alphabetical)",
             progress_start: int = 0, progress_end: int = 70) -> ScanResult:
        """Scan one folder for duplicates without touching any files"""
        if not os.path.exists(source_folder):
            raise ValueError(f"Source folder does not exist: {source_folder}")
        return self._scan([(source_folder, 0)], recursive, algorithm, keep_rule, False,
                          progress_start, progress_end)

    def scan_compare(self, reference_folder: str, target_folder: str, recursive: bool = True,
                      algorithm: str = "md5") -> ScanResult:
        """Scan target_folder (B) for files that already exist (by content) in reference_folder (A).
        reference_folder is only ever read, never modified."""
        if not os.path.exists(reference_folder):
            raise ValueError(f"Reference folder does not exist: {reference_folder}")
        if not os.path.exists(target_folder):
            raise ValueError(f"Target folder does not exist: {target_folder}")
        ref, tgt = os.path.abspath(reference_folder), os.path.abspath(target_folder)
        if _inside(ref, tgt) or _inside(tgt, ref):
            raise ValueError("The reference and target folders overlap (one is inside the other). "
                             "Pick two separate folders.")
        return self._scan([(reference_folder, 0), (target_folder, 1)], recursive, algorithm,
                          KEEP_RULES[0], True, 0, 70)

    def _scan(self, folders, recursive: bool, algorithm: str, keep_rule: str, compare: bool,
              progress_start: int, progress_end: int) -> ScanResult:
        empty = ScanResult({}, {}, {}, 0, 0, keep_rule, algorithm=algorithm, compare_mode=compare)
        conn = hash_db.connect(self.db_path)
        try:
            hash_db.begin_run(conn)
            walk_errors: Dict[str, str] = {}
            mode_str = "recursively" if recursive else "in root folder only"
            for folder, side in folders:
                name = ("reference folder (A)" if side == 0 else "target folder (B)") if compare else "source folder"
                self._log_status(f"Listing {name} {mode_str}...")
                entries = self._walk(os.path.abspath(folder), recursive, walk_errors)
                if self._cancelled():
                    self._log_status("Operation cancelled while listing files")
                    return empty
                self._log_status(f"Listed {len(entries):,} file(s) in {folder}")
                hash_db.add_listing(conn, entries, side)

            counts = hash_db.apply_listing(conn)
            if recursive:
                for folder, _ in folders:
                    hash_db.prune_folder(conn, os.path.abspath(folder))
            self._log_status(f"Database: {counts['new']:,} new, {counts['changed']:,} changed, "
                             f"{counts['unchanged']:,} unchanged file(s)")

            cands = hash_db.candidates(conn, algorithm, compare)
            pending = [r for r in cands if not r["cached"]]
            total_listed = hash_db.run_count(conn)
            self._log_status(
                f"Size pre-filter: {len(cands):,} of {total_listed:,} file(s) share a size with another file; "
                f"{len(cands) - len(pending):,} hash(es) reused from the cache, {len(pending):,} to hash"
            )

            if pending:
                self._log_status(f"Hashing {len(pending):,} file(s) with {self.max_workers} workers "
                                 f"({algorithm.upper()})...")
            hash_errors = self._hash_pending(conn, pending, algorithm, progress_start, progress_end)
            if self._cancelled():
                self._log_status("Operation cancelled during hashing (hashes done so far are kept for next time)")
                return empty

            hash_errors.update(walk_errors)
            total = hash_db.run_count(conn, 1) if compare else total_listed
            result = self._build_result(conn, algorithm, keep_rule, compare, total, hash_errors)
        finally:
            conn.close()

        if compare:
            self._log_status(f"Found {len(result.to_remove):,} file(s) in target folder that already exist "
                             f"in reference folder")
        else:
            self._log_status(f"Found {len(result.groups):,} duplicate group(s), "
                             f"{len(result.to_remove):,} duplicate file(s)")
        return result

    def _build_result(self, conn, algorithm: str, keep_rule: str, compare: bool,
                      total_files: int, hash_errors: Dict[str, str]) -> ScanResult:
        """Turn the ranked SQL rows into groups: rank 1 = primary, remove = 1 -> to_remove"""
        groups: Dict[str, List[FileEntry]] = {}
        primary_map: Dict[str, FileEntry] = {}
        to_remove: List[Tuple[str, FileEntry]] = []
        for r in hash_db.ranked(conn, algorithm, keep_rule, compare):
            entry = FileEntry(r["path"], r["size"], r["mtime"], r["hash"], file_id=r["id"])
            if r["dup_rank"] == 1:
                primary_map[r["hash"]] = entry
            if not compare or r["side"] == 1:
                groups.setdefault(r["hash"], []).append(entry)
            if r["remove"]:
                to_remove.append((r["hash"], entry))
        unique_count = total_files - len(to_remove) - len(hash_errors)
        return ScanResult(groups, primary_map, hash_errors, total_files, max(unique_count, 0), keep_rule,
                          to_remove, algorithm, compare)

    def rescan_keep_rule(self, scan_result: ScanResult, keep_rule: str) -> ScanResult:
        """Re-rank the same run under a new keep rule: one SQL query, no re-hashing"""
        conn = hash_db.connect(self.db_path)
        try:
            return self._build_result(conn, scan_result.algorithm, keep_rule, scan_result.compare_mode,
                                      scan_result.total_files, scan_result.hash_errors)
        finally:
            conn.close()

    def cache_stats(self) -> dict:
        conn = hash_db.connect(self.db_path)
        try:
            return hash_db.stats(conn)
        finally:
            conn.close()

    def clear_cache(self) -> None:
        conn = hash_db.connect(self.db_path)
        try:
            hash_db.clear(conn)
        finally:
            conn.close()

    # ---------- execute ----------

    def execute(self, scan_result: ScanResult, source_folder: str, permanent_delete: bool = False,
                progress_start: int = 70, progress_end: int = 100) -> Tuple[List[DedupeResult], int, int, int]:
        """Move (or delete) every rank > 1 file of each duplicate group"""
        return self._remove(scan_result, source_folder, permanent_delete, progress_start, progress_end)

    def execute_compare(self, scan_result: ScanResult, target_folder: str, permanent_delete: bool = False,
                         progress_start: int = 70, progress_end: int = 100) -> Tuple[List[DedupeResult], int, int, int]:
        """Move (or delete) target-folder files that match the reference folder. Reference is never touched."""
        return self._remove(scan_result, target_folder, permanent_delete, progress_start, progress_end)

    def _remove(self, scan_result: ScanResult, folder: str, permanent_delete: bool,
                progress_start: int, progress_end: int) -> Tuple[List[DedupeResult], int, int, int]:
        compare = scan_result.compare_mode
        dupes_folder = os.path.join(folder, DUPES_DIR)
        if not permanent_delete:
            os.makedirs(long_path(dupes_folder), exist_ok=True)

        results: List[DedupeResult] = []
        if not compare:
            for file_hash, primary in scan_result.primary_map.items():
                results.append(DedupeResult(primary.path, None, file_hash, False, True, False))
        for path, error in scan_result.hash_errors.items():
            results.append(DedupeResult(path, None, '', False, False, False, error_message=error))

        duplicates = scan_result.to_remove
        duplicate_count = len(duplicates)
        action = "Deleting" if permanent_delete else "Moving"
        if compare:
            self._log_status(f"{action} {duplicate_count:,} file(s) from target folder that match the reference folder...")
        else:
            dest_desc = "permanently" if permanent_delete else "to Dupes folder"
            self._log_status(f"{action} {duplicate_count:,} duplicate(s) {dest_desc}...")

        moved_count = 0
        gone_ids: List[int] = []
        for idx, (file_hash, entry) in enumerate(duplicates, 1):
            if self._cancelled():
                self._log_status("Operation cancelled by user")
                break

            filename = os.path.basename(entry.path)
            progress = progress_start + int((idx / max(duplicate_count, 1)) * (progress_end - progress_start))
            self._report_progress(progress, 100, f"{action}: {filename}")

            primary_name = os.path.basename(scan_result.primary_map[file_hash].path)
            try:
                if permanent_delete:
                    os.unlink(long_path(entry.path))
                    results.append(DedupeResult(entry.path, None, file_hash, True, False, True))
                else:
                    dest_path = self._get_unique_dest_path(dupes_folder, filename)
                    shutil.move(long_path(entry.path), long_path(dest_path))
                    self._log_status(f"Moved: {filename} (dup of {primary_name})")
                    results.append(DedupeResult(entry.path, dest_path, file_hash, True, False, True))
                moved_count += 1
                if entry.file_id is not None:
                    gone_ids.append(entry.file_id)
            except Exception as e:
                self._log_status(f"Error {action.lower()} {filename}: {e}")
                results.append(DedupeResult(entry.path, None, file_hash, True, False, False, error_message=str(e)))

        if gone_ids:                                   # those paths no longer exist: drop their cache rows
            conn = hash_db.connect(self.db_path)
            try:
                hash_db.forget(conn, gone_ids)
            finally:
                conn.close()

        action_past = "deleted" if permanent_delete else "moved"
        if self._cancelled():
            self._log_status(f"Operation cancelled: {moved_count:,} file(s) {action_past}")
        elif compare:
            self._log_status(f"Complete: {moved_count:,} file(s) {action_past} from target folder")
        else:
            error_count = len(scan_result.hash_errors) + sum(1 for r in results if r.is_duplicate and not r.moved)
            self._log_status(
                f"Complete: {len(scan_result.primary_map):,} unique group(s), {moved_count:,} duplicate(s) "
                f"{action_past}, {error_count:,} error(s)"
            )

        return results, scan_result.total_files, scan_result.unique_count, moved_count

    def _get_unique_dest_path(self, dest_folder: str, filename: str) -> str:
        dest_path = os.path.join(dest_folder, filename)

        if not os.path.exists(long_path(dest_path)):
            return dest_path

        base_name, ext = os.path.splitext(filename)
        counter = 1

        while os.path.exists(long_path(dest_path)):
            new_filename = f"{base_name}_{counter:03d}{ext}"
            dest_path = os.path.join(dest_folder, new_filename)
            counter += 1

        return dest_path
