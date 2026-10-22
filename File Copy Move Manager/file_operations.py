"""File operation classes for File Copy Move Manager application"""

import os
import shutil
import time
import fnmatch
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable
from dataclasses import dataclass

from folder_organization import FolderStructure
from copy_plan import (
    Action, Plan, PlanItem, TEMP_PREFIX, TEMP_SUFFIX, WRITE_ACTIONS, build_plan, compute_md5,
)


def format_file_size(size_bytes: float) -> str:
    """Format a byte count in human-readable units (e.g. "1.23 MB")."""
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


@dataclass
class FileOperationResult:
    """Result of a file operation"""
    success: bool
    source_file: str
    destination_file: Optional[str] = None
    error_message: Optional[str] = None
    file_size: int = 0
    copy_time: float = 0.0
    checksum_verified: Optional[bool] = None
    cancelled: bool = False       # stopped by Cancel before/while this file was copied


@dataclass
class RunSummary:
    """Totals for a finished (or cancelled) run."""
    copied: int
    skipped: int       # includes the files the plan skipped before anything was copied
    errors: int
    bytes_copied: int


def summarize_results(results: List[FileOperationResult], planned_skips: int = 0) -> RunSummary:
    """Count copied / skipped / errors. Files stopped by Cancel are not counted as skipped."""
    copied = skipped = errors = total_bytes = 0
    for r in results:
        if r.cancelled:
            continue
        if not r.success:
            errors += 1
        elif r.destination_file is not None:
            copied += 1
            total_bytes += r.file_size
        else:
            skipped += 1
    return RunSummary(copied, skipped + planned_skips, errors, total_bytes)


class FileValidator:
    """Validates file operations and inputs"""

    @staticmethod
    def validate_file_mask(file_mask: str) -> List[str]:
        """
        Validate and normalize file mask patterns

        Args:
            file_mask: File mask pattern(s) to validate (e.g., "*.jpg, *.png" or "oct*.*")

        Returns:
            List of normalized patterns

        Raises:
            ValueError: If file mask is empty
        """
        file_mask = file_mask.strip()
        if not file_mask:
            raise ValueError("File mask cannot be empty")

        # Split by comma and normalize each pattern
        patterns = []
        for pattern in file_mask.split(','):
            pattern = pattern.strip()
            if not pattern:
                continue
            # If pattern doesn't contain *, add *. prefix for extension matching
            if '*' not in pattern and '?' not in pattern:
                if not pattern.startswith('.'):
                    pattern = '.' + pattern
                pattern = '*' + pattern
            patterns.append(pattern)

        if not patterns:
            raise ValueError("File mask cannot be empty")

        return patterns

    @staticmethod
    def validate_folder_exists(folder_path: str) -> None:
        """
        Validate that a folder exists

        Args:
            folder_path: Path to validate

        Raises:
            ValueError: If folder doesn't exist
        """
        if not os.path.exists(folder_path):
            raise ValueError(f"Folder does not exist: {folder_path}")


class FileScanner:
    """Scans directories for files matching criteria"""

    @staticmethod
    def _matches_any_pattern(filename: str, patterns: List[str]) -> bool:
        """
        Check if filename matches any of the given patterns

        Args:
            filename: Filename to check
            patterns: List of glob patterns

        Returns:
            True if filename matches any pattern
        """
        filename_lower = filename.lower()
        for pattern in patterns:
            if fnmatch.fnmatch(filename_lower, pattern.lower()):
                return True
        return False

    @staticmethod
    def get_files_with_patterns(
        folder_path: str,
        patterns: List[str],
        recursive: bool = False,
        min_size_bytes: Optional[float] = None,
        max_size_bytes: Optional[float] = None,
        max_days_old: Optional[int] = None,
        sort_order: str = "largest",
        include_mtime: bool = False,
    ) -> List[tuple]:
        """
        Scan folder for matching files, apply filters, and return them ordered
        per `sort_order`: "largest" (default, best for parallel load-balancing),
        "smallest" (fast-climbing progress count), "oldest" (oldest modified
        date first), or "directory" (scan order, preserves read locality on
        mechanical drives).

        Returns a list of (full_path, relative_path, size_bytes) tuples, or
        (full_path, relative_path, size_bytes, mtime) when include_mtime is True.
        """
        from datetime import datetime, timedelta

        files = []
        now = datetime.now()
        cutoff = (now - timedelta(days=max_days_old)).timestamp() if max_days_old is not None else None

        def _accept(full_path: str, filename: str):
            if not FileScanner._matches_any_pattern(filename, patterns):
                return False, 0, 0.0
            try:
                st = os.stat(full_path)
            except OSError:
                return False, 0, 0.0
            size = st.st_size
            if min_size_bytes is not None and size < min_size_bytes:
                return False, 0, 0.0
            if max_size_bytes is not None and size > max_size_bytes:
                return False, 0, 0.0
            if cutoff is not None and st.st_mtime < cutoff:
                return False, 0, 0.0
            return True, size, st.st_mtime

        # Internal rows carry modified time for the "oldest" sort and the planner;
        # it is stripped before returning unless the caller asked for it.
        rows = []  # (full_path, rel_path, size, mtime)
        if recursive:
            for root, dirs, filenames in os.walk(folder_path):
                for filename in filenames:
                    full_path = os.path.join(root, filename)
                    ok, size, mtime = _accept(full_path, filename)
                    if ok:
                        rel_path = os.path.relpath(full_path, folder_path)
                        rows.append((full_path, rel_path, size, mtime))
        else:
            for filename in os.listdir(folder_path):
                full_path = os.path.join(folder_path, filename)
                if os.path.isfile(full_path):
                    ok, size, mtime = _accept(full_path, filename)
                    if ok:
                        rows.append((full_path, filename, size, mtime))

        if sort_order == "largest":
            rows.sort(key=lambda x: x[2], reverse=True)
        elif sort_order == "smallest":
            rows.sort(key=lambda x: x[2])
        elif sort_order == "oldest":
            rows.sort(key=lambda x: x[3])  # oldest modified date first
        # "directory" (or anything else): leave in natural scan order
        if include_mtime:
            return rows
        return [(fp, rel, size) for fp, rel, size, _mtime in rows]


class FileCopier:
    """Plans and executes copy / move operations.

    build_plan() decides what happens to every file (see copy_plan.py);
    copy_files() executes that plan. Preview shows the same plan, so what you
    preview is exactly what is copied.
    """

    LARGE_FILE_THRESHOLD = 120 * 1024 * 1024   # chunked I/O above this: cancellable, live progress
    MIN_FILE_PROGRESS_SIZE = 50 * 1024 * 1024  # no per-file progress bar below this
    CHUNK_SIZE = 8 * 1024 * 1024
    MAX_RETRIES = 3
    RETRY_DELAY = 1.5
    # Windows error codes that mean "stop everything": disk full / drive gone / disk corrupt
    _FATAL_WINERRORS = {112, 39, 21, 1117, 1392}

    def __init__(
        self,
        status_callback: Optional[Callable[[str], None]] = None,
        folder_structure: FolderStructure = FolderStructure.FLAT,
        number_duplicates: bool = True,
        progress_callback: Optional[Callable[[int, int, str, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        counters_callback: Optional[Callable[[int, int, int], None]] = None,
        verify_checksum: bool = False,
        incremental: bool = False,
        move_mode: bool = False,
        workers: int = 1,
        transfer_callback: Optional[Callable[[str, str, int], None]] = None,
        fatal_error_callback: Optional[Callable[[str], None]] = None,
        sort_order: str = "largest",
        plan_progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ):
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.counters_callback = counters_callback
        self.transfer_callback = transfer_callback
        self.fatal_error_callback = fatal_error_callback
        self.plan_progress_callback = plan_progress_callback
        self.validator = FileValidator()
        self.scanner = FileScanner()
        self.folder_structure = folder_structure
        self.number_duplicates = number_duplicates
        self.verify_checksum = verify_checksum
        self.incremental = incremental
        self.move_mode = move_mode
        self.workers = max(1, workers)
        self.sort_order = sort_order
        self.last_activity_time: float = time.time()
        self.last_plan: Optional[Plan] = None
        self.planned_skips: int = 0     # files the plan skipped; results only cover files that were attempted

    # ── helpers ──────────────────────────────────────────────────────────────

    def _log_status(self, message: str) -> None:
        """Log status message if callback is set"""
        if self.status_callback:
            self.status_callback(message)

    def _is_cancelled(self) -> bool:
        return bool(self.cancel_check and self.cancel_check())

    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format (e.g. "1.23 MB")."""
        return format_file_size(size_bytes)

    @staticmethod
    def _discard(path: str) -> None:
        """Remove a temp file if it exists."""
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _skip_message(item: PlanItem) -> str:
        """The per-file skip reason written to the log (one line per skipped file)."""
        if item.action is Action.UP_TO_DATE:
            return f"Skipped (unchanged): {item.source_path}"
        if item.action is Action.SAME_CONTENT:
            return f"Skipped (identical): {item.source_path}"
        if item.action is Action.DUPLICATE_SOURCE:
            return f"Skipped (same image as another source): {item.source_path}"
        if item.action is Action.OLDER:
            return f"Skipped (older): {item.source_path}"
        return f"Skipped (duplicate): {item.source_path}"        # NAME_TAKEN

    # ── planning ─────────────────────────────────────────────────────────────

    def build_plan(
        self,
        source_folder: str,
        dest_folder: str,
        file_mask: str,
        preserve_structure: bool = False,
        recursive: bool = True,
        min_size_bytes: Optional[float] = None,
        max_size_bytes: Optional[float] = None,
        max_days_old: Optional[int] = None,
    ) -> Plan:
        """
        Scan the source and work out what to do with every file, without
        writing anything. Raises copy_plan.PlanCancelled if cancelled.
        """
        self.validator.validate_folder_exists(source_folder)
        patterns = self.validator.validate_file_mask(file_mask)

        search_mode = "recursively through all subfolders" if recursive else "in root folder only"
        patterns_str = ", ".join(patterns)
        self._log_status(f"Reading directories {search_mode}...")
        self._log_status(f"Gathering file list — matching: {patterns_str}")
        files = self.scanner.get_files_with_patterns(
            source_folder, patterns, recursive,
            min_size_bytes=min_size_bytes,
            max_size_bytes=max_size_bytes,
            max_days_old=max_days_old,
            sort_order=self.sort_order,
            include_mtime=True,
        )
        if not files:
            self._log_status(f"No files found matching '{patterns_str}'")
            self.last_plan = Plan([], dest_folder)
            return self.last_plan

        order_desc = {
            "largest": "largest to smallest",
            "smallest": "smallest to largest",
            "oldest": "oldest modified date first",
            "directory": "directory order",
        }.get(self.sort_order, "largest to smallest")
        self._log_status(f"Found {len(files)} files — ordering {order_desc}...")
        self._log_status("Comparing with the destination...")

        plan = build_plan(
            files, dest_folder,
            preserve_structure=preserve_structure,
            folder_structure=self.folder_structure,
            number_duplicates=self.number_duplicates,
            incremental=self.incremental,
            cancel_check=self.cancel_check,
            progress=self.plan_progress_callback,
        )
        self.last_plan = plan
        verb = "move" if self.move_mode else "copy"
        self._log_status(
            f"Plan: {plan.copy_count} to {verb} ({format_file_size(plan.bytes_to_copy)}), "
            f"{plan.skipped_count} already handled"
        )
        if plan.leftover_temp_files:
            self._log_status(
                f"Note: {len(plan.leftover_temp_files)} leftover temporary file(s) from an interrupted copy "
                f"were found in the destination (names start with {TEMP_PREFIX} and end with {TEMP_SUFFIX}) "
                f"— they are safe to delete. First: {plan.leftover_temp_files[0]}"
            )
        return plan

    # ── copying ──────────────────────────────────────────────────────────────

    def copy_files(
        self,
        source_folder: str,
        dest_folder: str,
        file_mask: str,
        preserve_structure: bool = False,
        recursive: bool = True,
        min_size_bytes: Optional[float] = None,
        max_size_bytes: Optional[float] = None,
        max_days_old: Optional[int] = None,
        plan: Optional[Plan] = None,
    ) -> List[FileOperationResult]:
        """
        Copy (or move) files from source to destination.

        Args:
            source_folder: Source folder path
            dest_folder: Destination folder path
            file_mask: File mask pattern(s) to match (e.g., "*.jpg, *.png" or "oct*.*")
            preserve_structure: If True, preserve original folder structure
            recursive: If True, search subfolders recursively
            min_size_bytes / max_size_bytes / max_days_old: scan filters
            plan: a plan from build_plan() (e.g. the one shown in Preview). When
                  given, the scan and comparison are skipped and exactly that
                  plan is executed.

        Returns:
            FileOperationResult objects for the files that were attempted.
            Files the plan skipped are counted in self.planned_skips.

        Raises:
            ValueError: If validation fails
            OSError: If folders cannot be accessed
        """
        self.validator.validate_folder_exists(source_folder)
        self.validator.validate_file_mask(file_mask)

        self._log_status("Checking destination folder...")
        os.makedirs(dest_folder, exist_ok=True)

        verb = "move" if self.move_mode else "copy"
        if plan is None:
            plan = self.build_plan(
                source_folder, dest_folder, file_mask, preserve_structure, recursive,
                min_size_bytes=min_size_bytes, max_size_bytes=max_size_bytes,
                max_days_old=max_days_old,
            )
        else:
            self.last_plan = plan
            self._log_status(
                f"Using the previewed plan: {plan.copy_count} file(s) to {verb}, "
                f"{plan.skipped_count} already handled..."
            )
        return self._execute_plan(plan)

    def _execute_plan(self, plan: Plan) -> List[FileOperationResult]:
        # The watchdog measures "time since the last disk activity"; planning can take minutes,
        # so start the clock now rather than at construction.
        self.last_activity_time = time.time()
        todo = plan.to_copy
        planned_skips = plan.skipped_count
        self.planned_skips = planned_skips
        verb = "move" if self.move_mode else "copy"
        verb_past = "moved" if self.move_mode else "copied"

        # One log line per skipped file, with the reason (kept out of the on-screen list).
        for item in plan.items:
            if item.action not in WRITE_ACTIONS:
                self._log_status(self._skip_message(item))

        if self.counters_callback:
            self.counters_callback(0, planned_skips, 0)

        if not todo:
            self._log_status(f"Nothing to {verb} — everything is already at the destination")
            self._log_status(f"Operation completed: 0 {verb_past} ({format_file_size(0)}), "
                             f"{planned_skips} skipped, 0 errors")
            return []

        worker_str = f" ({self.workers} workers)" if self.workers > 1 else ""
        self._log_status(f"Starting {verb} operations{worker_str}...")

        total = len(todo)
        results: List[FileOperationResult] = []

        if self.workers <= 1:
            # ── Sequential path ──────────────────────────────────────────────
            copied_n = skipped_n = errors_n = 0
            for idx, item in enumerate(todo, 1):
                if self._is_cancelled():
                    self._log_status("Operation cancelled by user")
                    break

                filename = os.path.basename(item.source_path)
                show_file_progress = item.size >= self.MIN_FILE_PROGRESS_SIZE

                if self.progress_callback:
                    self.progress_callback(idx, total, filename, 0 if show_file_progress else -1)

                result = self._copy_one(item, idx, total)
                results.append(result)

                if self.progress_callback:
                    self.progress_callback(idx, total, filename, 100 if show_file_progress else -1)

                # Running totals — recounting every result after every file is quadratic.
                if result.cancelled:
                    pass
                elif not result.success:
                    errors_n += 1
                elif result.destination_file is not None:
                    copied_n += 1
                else:
                    skipped_n += 1
                if self.counters_callback:
                    self.counters_callback(copied_n, skipped_n + planned_skips, errors_n)

        else:
            # ── Parallel path ─────────────────────────────────────────────────
            _lock = threading.Lock()
            _counts = [0, 0, 0, 0]  # [completed, copied, skipped, errors]

            def _worker(item: PlanItem):
                result = self._copy_one(item, 0, 0)
                fname = os.path.basename(item.source_path)
                with _lock:
                    _counts[0] += 1
                    self.last_activity_time = time.time()
                    if result.cancelled:
                        pass
                    elif not result.success:
                        _counts[3] += 1
                    elif result.destination_file is not None:
                        _counts[1] += 1
                    else:
                        _counts[2] += 1
                    if self.progress_callback:
                        self.progress_callback(_counts[0], total, fname, -1)
                    if self.counters_callback:
                        self.counters_callback(_counts[1], _counts[2] + planned_skips, _counts[3])
                return result

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {executor.submit(_worker, item): item for item in todo}
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        fname = os.path.basename(futures[future].source_path)
                        self._log_status(f"Error: {fname} — {e}")
                        results.append(FileOperationResult(
                            success=False, source_file=fname, error_message=str(e)
                        ))

        # Summary
        summary = summarize_results(results, planned_skips)
        if self._is_cancelled():
            self._log_status(f"Operation cancelled: {summary.copied} files {verb_past} before cancellation")
        else:
            self._log_status(
                f"Operation completed: {summary.copied} {verb_past} ({format_file_size(summary.bytes_copied)}), "
                f"{summary.skipped} skipped, {summary.errors} errors"
            )
        return results

    def _copy_one(self, item: PlanItem, idx: int = 0, total: int = 0) -> FileOperationResult:
        """
        Carry out one planned write.

        The file is copied to a temporary name next to its destination and only
        renamed into place once it is complete (and verified, if requested). A
        cancel or an error therefore never leaves a half-written destination
        file, and in Move Mode the source is deleted only after a complete copy.
        """
        src = item.source_path
        dst = item.pre_dest
        filename = os.path.basename(src)
        tmp = ""
        try:
            if self._is_cancelled():
                return FileOperationResult(success=True, source_file=filename,
                                           error_message="Cancelled", cancelled=True)

            dest_dir = os.path.dirname(dst)
            os.makedirs(dest_dir, exist_ok=True)
            file_size = os.path.getsize(src)
            self.last_activity_time = time.time()
            tmp = os.path.join(dest_dir, f"{TEMP_PREFIX}{uuid.uuid4().hex[:12]}{TEMP_SUFFIX}")

            show_transfer = self.transfer_callback is not None and file_size >= self.MIN_FILE_PROGRESS_SIZE
            if show_transfer:
                self.transfer_callback(src, filename, 0)

            start_time = time.time()
            try:
                completed = self._copy_to_temp(src, tmp, file_size, filename, idx, total, show_transfer)
            finally:
                if show_transfer:                  # always clear the live-transfer row, even if the copy failed
                    self.transfer_callback(src, filename, -1)
            copy_time = time.time() - start_time

            if not completed:                         # Cancel pressed part-way through this file
                self._discard(tmp)
                return FileOperationResult(success=True, source_file=filename, file_size=file_size,
                                           error_message="Cancelled", cancelled=True)

            checksum_ok: Optional[bool] = None
            if self.verify_checksum:
                checksum_ok = compute_md5(src) == compute_md5(tmp)
                if not checksum_ok:
                    self._discard(tmp)
                    self._log_status(f"CHECKSUM FAILED: {filename}")
                    return FileOperationResult(
                        success=False, source_file=filename,
                        error_message="Checksum mismatch — file may be corrupted",
                        file_size=file_size, copy_time=copy_time, checksum_verified=False,
                    )

            final_path = self._finalize(tmp, dst, overwrite=item.action is Action.REFRESH)
            tmp = ""                                   # now in place
            final_name = os.path.basename(final_path)

            # Move mode: delete the source only after a complete copy is in place.
            if self.move_mode:
                try:
                    if os.path.getsize(final_path) == file_size:
                        os.remove(src)
                    else:
                        self._log_status(f"Warning: source not deleted after move: {filename} — "
                                         f"destination size differs from the source")
                except OSError as del_err:
                    self._log_status(f"Warning: source not deleted after move: {filename} — {del_err}")

            if item.action is Action.NUMBERED or final_path != dst:
                self._log_status(f"Duplicate found: {filename} → {final_name}")
            elif item.action is Action.REFRESH:
                self._log_status(f"Updated (source changed): {src}")

            # Only log large files individually; small files are counted silently
            if file_size >= self.LARGE_FILE_THRESHOLD:
                verb = "Moved" if self.move_mode else "Copied"
                verified_tag = " ✓" if checksum_ok else ""
                self._log_status(f"{verb} (large): {filename} ({self._format_file_size(file_size)}, "
                                 f"{copy_time:.2f}s){verified_tag}")

            return FileOperationResult(
                success=True,
                source_file=filename,
                destination_file=final_name,
                file_size=file_size,
                copy_time=copy_time,
                checksum_verified=checksum_ok,
            )
        except Exception as e:
            self._discard(tmp)
            err_str = str(e)
            if src in err_str:
                side = "reading source"
            elif (tmp and tmp in err_str) or dst in err_str:
                side = "writing destination"
            else:
                side = "copying"
            self._log_status(f"Error {side} — {filename}: {e}")
            return FileOperationResult(success=False, source_file=filename, error_message=str(e))

    def _copy_to_temp(self, src: str, tmp: str, file_size: int, filename: str,
                      idx: int, total: int, show_transfer: bool) -> bool:
        """
        Copy src to tmp, retrying transient (e.g. network) errors.
        Returns False if Cancel was pressed before the copy finished.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                if file_size >= self.LARGE_FILE_THRESHOLD:
                    # Always chunk large files so last_activity_time stays current
                    copied_bytes = 0
                    with open(src, 'rb') as fsrc, open(tmp, 'wb') as fdst:
                        while True:
                            if self._is_cancelled():
                                return False
                            chunk = fsrc.read(self.CHUNK_SIZE)
                            if not chunk:
                                break
                            fdst.write(chunk)
                            copied_bytes += len(chunk)
                            self.last_activity_time = time.time()
                            pct = int(copied_bytes / file_size * 100)
                            if self.progress_callback and total > 0:
                                self.progress_callback(idx, total, filename, pct)
                            if show_transfer:
                                self.transfer_callback(src, filename, pct)
                    shutil.copystat(src, tmp)
                else:
                    shutil.copyfile(src, tmp)
                    shutil.copystat(src, tmp)
                return True
            except OSError as copy_err:
                if self._is_cancelled():
                    return False
                # Unrecoverable errors — retrying more files would be pointless
                winerr = getattr(copy_err, 'winerror', None)
                if copy_err.errno == 28 or winerr in self._FATAL_WINERRORS:
                    reason = (
                        "Destination disk is full" if (winerr in (112, 39) or copy_err.errno == 28)
                        else "Destination drive is not ready or disconnected" if winerr in (21, 1117)
                        else "Destination disk or file is corrupt"
                    )
                    fatal_msg = f"{reason}: {copy_err}"
                    self._log_status(f"FATAL: {fatal_msg}")
                    if self.fatal_error_callback:
                        self.fatal_error_callback(fatal_msg)
                    raise OSError(fatal_msg) from copy_err
                err_str = str(copy_err)
                side = "reading source" if src in err_str else "writing destination" if tmp in err_str else "during copy"
                if attempt < self.MAX_RETRIES - 1:
                    self._log_status(f"Retry {attempt + 1}/{self.MAX_RETRIES - 1}: {filename} ({side}) — {copy_err}")
                    time.sleep(self.RETRY_DELAY)
                else:
                    raise OSError(f"[{side}] {copy_err}") from copy_err
        return True

    def _finalize(self, tmp: str, dst: str, overwrite: bool) -> str:
        """
        Put the finished temp file at its destination and return the final path.

        overwrite=True  (REFRESH): replace the older copy of this same file.
        overwrite=False (NEW / NUMBERED): never replace anything. If the name was
        taken after the plan was made, fall back to the next free numbered name.
        """
        if overwrite:
            try:
                os.replace(tmp, dst)
            except PermissionError:
                import stat as _stat
                os.chmod(dst, _stat.S_IWRITE | _stat.S_IREAD)     # read-only destination: clear the flag
                os.replace(tmp, dst)
            return dst

        target = dst
        stem, ext = os.path.splitext(dst)
        n = 0
        while True:
            try:
                os.rename(tmp, target)        # on Windows this refuses to replace an existing file
                return target
            except FileExistsError:
                n += 1
                target = f"{stem}_{n:03d}{ext}"
