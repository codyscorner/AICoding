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
import stat
import time
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait

import hash_db
from filetypes import Matcher


# Number of parallel workers for hashing (I/O bound, can use many)
MAX_WORKERS = 16

# Read buffer per hashing worker
BUFFER_SIZE = 1024 * 1024

# Folder duplicates are moved into; never scanned
DUPES_DIR = "Dupes"

# Windows system folders: never scanned (recycle bins hold deleted copies, not real duplicates)
SKIP_DIRS = {"$recycle.bin", "recycler", "system volume information"}

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


def is_read_only(path: str) -> bool:
    """True when the file has the Windows read-only attribute (os.unlink then fails with
    WinError 5 'Access is denied' even though nothing has the file open)."""
    try:
        attrs = os.stat(long_path(path)).st_file_attributes
    except (OSError, AttributeError):                 # gone, or not Windows
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_READONLY)


def count_read_only(paths) -> int:
    return sum(1 for p in paths if is_read_only(p))


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
    max_size: int = 0                    # bytes; 0 = no limit (bigger files are ignored, not hashed)
    file_types: tuple = ()               # preset names / masks; empty = all files
    read_only_paths: frozenset = frozenset()   # group members with the read-only attribute


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
        self.checkpoint_files = 20000        # listing progress is saved every N files ...
        self.checkpoint_seconds = 5.0        # ... or every N seconds, whichever comes first
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

    def _walk(self, conn, recursive: bool, errors: Dict[str, str]) -> None:
        """List every file of the folders in the walk queue into the `listing` table, as
        (full_path, size, mtime, side). Skips Dupes/system folders, links and the app's own
        database files. Progress is checkpointed to the database every few seconds and on
        cancel, so a cancelled or crashed listing carries on from the folders still queued."""
        stack = hash_db.walk_queue(conn)
        done = sum(hash_db.listing_counts(conn).values())
        buffer: List[Tuple[str, int, float, int]] = []
        last_checkpoint = time.monotonic()
        while stack and not self._cancelled():
            current, side = stack.pop()
            try:
                with os.scandir(long_path(current)) as it:
                    for e in it:
                        full = os.path.join(current, e.name)
                        try:
                            is_junction = getattr(e, "is_junction", None)
                            if e.is_symlink() or (is_junction and is_junction()):
                                continue                      # never follow links (loops)
                            if e.is_dir(follow_symlinks=False):
                                if recursive and e.name != DUPES_DIR and e.name.lower() not in SKIP_DIRS:
                                    stack.append((full, side))
                            elif e.is_file(follow_symlinks=False):
                                if os.path.normcase(full) in self._db_files:
                                    continue
                                st = e.stat(follow_symlinks=False)
                                buffer.append((full, st.st_size, st.st_mtime, side))
                                if (done + len(buffer)) % 2000 == 0:
                                    self._report_progress(0, 100, f"Listing: {done + len(buffer):,} files")
                        except OSError as ex:
                            errors[full] = str(ex)
            except OSError as ex:
                errors[current] = str(ex)
            # `current` is fully listed: a checkpoint here never splits a folder
            if len(buffer) >= self.checkpoint_files or time.monotonic() - last_checkpoint > self.checkpoint_seconds:
                hash_db.checkpoint_walk(conn, buffer, stack)
                done += len(buffer)
                buffer = []
                last_checkpoint = time.monotonic()
        hash_db.checkpoint_walk(conn, buffer, stack)

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
             keep_rule: str = "First (alphabetical)", max_size: int = 0, file_types=(),
             resume: bool = False, job_extra: Optional[dict] = None,
             progress_start: int = 0, progress_end: int = 70) -> ScanResult:
        """Scan one folder for duplicates without touching any files. max_size (bytes, 0 = no
        limit) ignores bigger files; file_types (preset names such as "Images" and/or masks such
        as "*.psd", empty = all) ignores other types. resume=True carries on an interrupted run of
        the same folder from the step it reached (listing, hashing or applying)."""
        if not os.path.exists(source_folder):
            raise ValueError(f"Source folder does not exist: {source_folder}")
        return self._scan([(source_folder, 0)], recursive, algorithm, keep_rule, False, max_size,
                          tuple(file_types or ()), resume, job_extra, progress_start, progress_end)

    def scan_compare(self, reference_folder: str, target_folder: str, recursive: bool = True,
                      algorithm: str = "md5", max_size: int = 0, file_types=(),
                      resume: bool = False, job_extra: Optional[dict] = None) -> ScanResult:
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
                          KEEP_RULES[0], True, max_size, tuple(file_types or ()), resume, job_extra, 0, 70)

    @staticmethod
    def _job_key(folders, recursive: bool, compare: bool) -> dict:
        """What has to match for an interrupted run to be resumed"""
        return {"folders": [[os.path.normcase(os.path.abspath(f)), side] for f, side in folders],
                "recursive": bool(recursive), "compare": bool(compare)}

    def pending_job(self) -> Optional[dict]:
        """The interrupted run, if any: {'settings': {...}, 'phase': ..., 'updated': ...}"""
        conn = hash_db.connect(self.db_path)
        try:
            job = hash_db.get_job(conn)
        finally:
            conn.close()
        return job if job and job["phase"] in hash_db.RESUMABLE_PHASES else None

    def set_job_extra(self, **extra) -> None:
        """Store UI settings (permanent delete etc.) with the run in progress, for the resume prompt"""
        conn = hash_db.connect(self.db_path)
        try:
            job = hash_db.get_job(conn)
            if job:
                job["settings"].update(extra)
                hash_db.set_job(conn, job["settings"], job["phase"])
        finally:
            conn.close()

    def finish_job(self) -> None:
        """The run completed, or was deliberately abandoned (review cancelled): nothing to resume"""
        conn = hash_db.connect(self.db_path)
        try:
            hash_db.clear_job(conn)
        finally:
            conn.close()

    def _scan(self, folders, recursive: bool, algorithm: str, keep_rule: str, compare: bool,
              max_size: int, file_types: tuple, resume: bool, job_extra: Optional[dict],
              progress_start: int, progress_end: int) -> ScanResult:
        empty = ScanResult({}, {}, {}, 0, 0, keep_rule, algorithm=algorithm, compare_mode=compare,
                           max_size=max_size, file_types=file_types)
        key = self._job_key(folders, recursive, compare)
        conn = hash_db.connect(self.db_path)
        try:
            hash_db.set_type_filter(conn, Matcher(list(file_types)) if file_types else None)
            walk_errors: Dict[str, str] = {}

            job = hash_db.get_job(conn)
            phase = None
            if resume and job and job["phase"] in hash_db.RESUMABLE_PHASES and \
                    all(job["settings"].get(k) == v for k, v in key.items()):
                phase = job["phase"]
                settings = {**job["settings"], **(job_extra or {}), **key}
                hash_db.set_job(conn, settings, phase)
                self._log_status(f"Resuming the interrupted run (it had reached: {phase})")
            if phase is None:
                hash_db.begin_run(conn, [(os.path.abspath(f), side) for f, side in folders])
                hash_db.set_job(conn, {**(job_extra or {}), **key}, "listing")
                phase = "listing"

            if phase == "listing":
                mode_str = "recursively" if recursive else "in root folder only"
                done_before = sum(hash_db.listing_counts(conn).values())
                if done_before:
                    self._log_status(f"Listing {mode_str} — continuing after {done_before:,} file(s) already listed...")
                else:
                    self._log_status(f"Listing {mode_str}...")
                self._walk(conn, recursive, walk_errors)
                if self._cancelled():
                    listed = sum(hash_db.listing_counts(conn).values())
                    self._log_status(f"Cancelled while listing — {listed:,} file(s) listed so far are saved; "
                                     f"Find Duplicates continues from here")
                    return empty
                counts_by_side = hash_db.listing_counts(conn)
                for folder, side in folders:
                    self._log_status(f"Listed {counts_by_side.get(side, 0):,} file(s) in {folder}")

                counts = hash_db.apply_listing(conn)
                if recursive:
                    for folder, _ in folders:
                        hash_db.prune_folder(conn, os.path.abspath(folder))
                self._log_status(f"Database: {counts['new']:,} new, {counts['changed']:,} changed, "
                                 f"{counts['unchanged']:,} unchanged file(s)")
                hash_db.set_phase(conn, "hashing")
                phase = "hashing"

            excluded = hash_db.excluded_counts(conn, max_size)
            if file_types:
                self._log_status(f"File types: {', '.join(file_types)} — ignoring {excluded['type']:,} "
                                 f"file(s) of other types")
            if excluded["size"]:
                self._log_status(f"Ignoring {excluded['size']:,} file(s) larger than "
                                 f"{max_size / 1024 / 1024:,.0f} MB")
            total_listed = hash_db.run_count(conn, max_size=max_size)

            hash_errors: Dict[str, str] = {}
            if phase == "hashing":
                cands = hash_db.candidates(conn, algorithm, compare, max_size)
                pending = [r for r in cands if not r["cached"]]
                self._log_status(
                    f"Size pre-filter: {len(cands):,} of {total_listed:,} file(s) share a size with another file; "
                    f"{len(cands) - len(pending):,} hash(es) reused from the cache, {len(pending):,} to hash"
                )
                if pending:
                    self._log_status(f"Hashing {len(pending):,} file(s) with {self.max_workers} workers "
                                     f"({algorithm.upper()})...")
                hash_errors = self._hash_pending(conn, pending, algorithm, progress_start, progress_end)
                if self._cancelled():
                    self._log_status("Cancelled while hashing — every hash finished so far is saved; "
                                     "Find Duplicates continues from here")
                    return empty
                hash_db.set_phase(conn, "review")
            else:
                self._log_status("Listing and hashing were already finished — rebuilding the duplicate list")

            hash_errors.update(walk_errors)
            total = hash_db.run_count(conn, 1, max_size) if compare else total_listed
            result = self._build_result(conn, algorithm, keep_rule, compare, max_size, file_types,
                                        total, hash_errors)
        finally:
            conn.close()

        if compare:
            self._log_status(f"Found {len(result.to_remove):,} file(s) in target folder that already exist "
                             f"in reference folder")
        else:
            self._log_status(f"Found {len(result.groups):,} duplicate group(s), "
                             f"{len(result.to_remove):,} duplicate file(s)")
        return result

    def _build_result(self, conn, algorithm: str, keep_rule: str, compare: bool, max_size: int,
                      file_types: tuple, total_files: int, hash_errors: Dict[str, str]) -> ScanResult:
        """Turn the ranked SQL rows into groups: rank 1 = primary, remove = 1 -> to_remove"""
        groups: Dict[str, List[FileEntry]] = {}
        primary_map: Dict[str, FileEntry] = {}
        to_remove: List[Tuple[str, FileEntry]] = []
        for r in hash_db.ranked(conn, algorithm, keep_rule, compare, max_size):
            entry = FileEntry(r["path"], r["size"], r["mtime"], r["hash"], file_id=r["id"])
            if r["dup_rank"] == 1:
                primary_map[r["hash"]] = entry
            if not compare or r["side"] == 1:
                groups.setdefault(r["hash"], []).append(entry)
            if r["remove"]:
                to_remove.append((r["hash"], entry))
        unique_count = total_files - len(to_remove) - len(hash_errors)
        return ScanResult(groups, primary_map, hash_errors, total_files, max(unique_count, 0), keep_rule,
                          to_remove, algorithm, compare, max_size, file_types)

    def rescan_keep_rule(self, scan_result: ScanResult, keep_rule: str) -> ScanResult:
        """Re-rank the same run under a new keep rule: one SQL query, no re-hashing"""
        conn = hash_db.connect(self.db_path)
        try:
            ft = scan_result.file_types
            hash_db.set_type_filter(conn, Matcher(list(ft)) if ft else None)
            result = self._build_result(conn, scan_result.algorithm, keep_rule, scan_result.compare_mode,
                                        scan_result.max_size, ft, scan_result.total_files,
                                        scan_result.hash_errors)
            result.read_only_paths = scan_result.read_only_paths   # same files, only the survivor changes
            return result
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
                clear_read_only: bool = False,
                progress_start: int = 70, progress_end: int = 100) -> Tuple[List[DedupeResult], int, int, int]:
        """Move (or delete) every rank > 1 file of each duplicate group. clear_read_only removes the
        read-only attribute from a duplicate just before deleting it."""
        return self._remove(scan_result, source_folder, permanent_delete, clear_read_only,
                            progress_start, progress_end)

    def execute_compare(self, scan_result: ScanResult, target_folder: str, permanent_delete: bool = False,
                         clear_read_only: bool = False,
                         progress_start: int = 70, progress_end: int = 100) -> Tuple[List[DedupeResult], int, int, int]:
        """Move (or delete) target-folder files that match the reference folder. Reference is never touched."""
        return self._remove(scan_result, target_folder, permanent_delete, clear_read_only,
                            progress_start, progress_end)

    def _remove(self, scan_result: ScanResult, folder: str, permanent_delete: bool, clear_read_only: bool,
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
        cleared_count = 0
        changed_count = 0
        gone_ids: List[int] = []
        primary_ok: Dict[str, bool] = {}
        conn = hash_db.connect(self.db_path)
        if hash_db.get_job(conn):
            hash_db.set_phase(conn, "applying")
        for idx, (file_hash, entry) in enumerate(duplicates, 1):
            if self._cancelled():
                self._log_status("Operation cancelled by user")
                break

            filename = os.path.basename(entry.path)
            progress = progress_start + int((idx / max(duplicate_count, 1)) * (progress_end - progress_start))
            self._report_progress(progress, 100, f"{action}: {filename}")

            primary = scan_result.primary_map[file_hash]
            primary_name = os.path.basename(primary.path)
            # Safety: a resumed run may apply a list made earlier. Only remove a duplicate that is
            # unchanged since it was hashed, and only while its kept copy still exists.
            if file_hash not in primary_ok:
                primary_ok[file_hash] = os.path.exists(long_path(primary.path))
            reason = None
            if not primary_ok[file_hash]:
                reason = f"kept copy is gone ({primary.path}) - skipped"
            else:
                try:
                    st = os.stat(long_path(entry.path))
                    if st.st_size != entry.size or st.st_mtime != entry.mtime:
                        reason = "changed since it was scanned - skipped"
                except FileNotFoundError:
                    reason = "already gone"
                    if entry.file_id is not None:
                        gone_ids.append(entry.file_id)
                except OSError as e:
                    reason = str(e)
            if reason:
                changed_count += 1
                self._log_status(f"Skipped {filename}: {reason}")
                results.append(DedupeResult(entry.path, None, file_hash, True, False, False, error_message=reason))
                continue
            try:
                if permanent_delete:
                    # A move is a same-drive rename, which Windows allows on read-only files;
                    # a delete is refused until the attribute is cleared
                    if clear_read_only and is_read_only(entry.path):
                        os.chmod(long_path(entry.path), stat.S_IWRITE)
                        cleared_count += 1
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
                    if len(gone_ids) >= hash_db.BATCH:     # crash-safe: moved files leave the cache as we go
                        hash_db.forget(conn, gone_ids)
                        gone_ids = []
            except Exception as e:
                if permanent_delete and isinstance(e, PermissionError) and is_read_only(entry.path):
                    e = PermissionError(f"file is read-only - tick 'Clear read-only flag' to delete it ({entry.path})")
                self._log_status(f"Error {action.lower()} {filename}: {e}")
                results.append(DedupeResult(entry.path, None, file_hash, True, False, False, error_message=str(e)))

        try:
            if gone_ids:                               # those paths no longer exist: drop their cache rows
                hash_db.forget(conn, gone_ids)
            if not self._cancelled():
                hash_db.clear_job(conn)                # finished: nothing left to resume
        finally:
            conn.close()
        if changed_count:
            self._log_status(f"{changed_count:,} file(s) skipped because they changed or their kept copy is gone")

        if cleared_count:
            self._log_status(f"Cleared the read-only flag on {cleared_count:,} file(s) before deleting")
        action_past = "deleted" if permanent_delete else "moved"
        if self._cancelled():
            self._log_status(f"Operation cancelled: {moved_count:,} file(s) {action_past} — "
                             f"Find Duplicates continues with the rest")
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
