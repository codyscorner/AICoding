# Changelog

All notable changes to File Copy Move Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.4.2] - 2026-10-08

### Changed
- **New app icon** (coral stack of two pages with a forward arrow). The old icon was a blue folder with an arrow that looked almost the same as another app's; every app icon is now unique. Generated with IconMaker.
- Own `AppUserModelID` so the taskbar groups/shows this app instead of python.exe, and the icon is set app-wide so every dialog gets it too.
- This is the first EXE build since 2026-06-29, so it also ships **v3.4.1** (total bytes copied on completion), which was committed but never deployed.

## [3.4.1] - 2026-06-30

### Added
- **Total bytes copied is now reported on completion** — every run now shows how much data was actually copied/moved (auto-scaled B / KB / MB / GB / TB), so you can compare the size of one run against another. It appears in:
  - the **completion popup** (e.g. `Total Copied: 142 (3.71 GB)`),
  - the **status window** (a dedicated `Total copied: N files | 3.71 GB` line, the `Complete!` progress line, and the multi-source `All sources complete` banner),
  - the **per-source line** in the multi-source tab (each source shows its own copied size),
  - the **log file** (`Operation completed:` line now includes the byte total).
- Size totals also appear when a run is cancelled or auto-cancelled by the watchdog, reflecting the data copied up to that point.

---

## [3.4.0] - 2026-06-29

### Added
- **Copy order dropdown** — both tabs now let you choose the order files are processed: **Largest first** (new default), Smallest first, Oldest first (modified date), or Directory order (as found). The choice is saved and written into the run-settings log header.
- **Largest-first is the new default** — for parallel copies it balances work across the worker pool and eliminates the "idle worker tail" where most workers finish while one grinds the last few huge files. Smallest-first remains available for a fast-climbing progress count; Directory order preserves read locality on mechanical drives.

### Notes
- Date-based behavior is consistent on **modified date**: the age filter, the date folder structure (Year / Year-Month), and the new "Oldest first" sort all use the file's modified time. Modified time is preferred over created time because copying a file resets its created date but preserves its modified date.

---

## [3.3.12] - 2026-06-29

### Fixed
- **Log header separators now use plain `=`** — the box-drawing `═` (U+2550) used in the run-settings header isn't in the log file's Windows code page (cp1252), so it was being written as literal `═` escapes. Replaced with `=` so the header is readable in the log.

---

## [3.3.11] - 2026-06-29

### Added
- **Run settings header in the log file** — when an operation starts, the full set of settings for the active tab is written to the top of the log: mode, source(s), destination, file mask, recursive, preserve structure, folder structure, number-duplicates, incremental, verify-checksum, workers, and the size/date filters. Makes every run self-documenting and reproducible. Single-Source and Multi-Source each log their own header (Multi-Source lists every source folder).

---

## [3.3.10] - 2026-06-29

### Changed
- **Timestamped log filename** — each app launch now writes to its own `FileCopyMoveManager_YYYY-MM-DD_HH-MM-SS.log` instead of a single reused `FileCopyMoveManager.log`, so previous run logs are preserved and sort chronologically. The completion status line still prints the full path to the current run's log.

---

## [3.3.9] - 2026-06-29

### Added
- **Per-file skip reasons in the log file** — every skipped file now writes a reason line to `FileCopyMoveManager.log`: `Skipped (duplicate)` (name collision, numbering off), `Skipped (identical)` (byte-identical content, numbering on), and `Skipped (unchanged)` (incremental size + mtime match). The incremental "unchanged" skip — previously completely silent — is now recorded, and the Multi-Source incremental pre-filter logs each file it drops before workers start. All copier events (skips, duplicate renames, retries, errors) are routed to the log file even when filtered out of the on-screen status list.
- **Log file path shown on completion** — both tabs now print the full path to `FileCopyMoveManager.log` in the status window when an operation finishes, so the per-file skip details are easy to find.

---

## [3.3.6] - 2026-06-28

### Changed
- **Multi-Source tab reverted to sequential source processing** — sources now run one at a time (first source completes fully before the second starts); workers-per-source still applies so copying within each source remains parallel; this eliminates simultaneous I/O across multiple USB drives which was causing hard system resets

---

## [3.3.5] - 2026-06-28

### Fixed
- **Read-only destination files** — when overwriting an existing file that has the read-only attribute set, the app now automatically clears the read-only flag and retries instead of failing with Permission denied
- **Clearer error messages** — errors now say "reading source" or "writing destination" so you can immediately tell which drive/side the problem is on

---

## [3.3.4] - 2026-06-28

### Fixed
- **Incremental mode now overwrites changed files** — previously a file that existed at the destination but had different size or mtime was incorrectly skipped as a "duplicate" when *Number duplicate files* was unchecked; it now overwrites the destination copy as intended. The "number duplicates" duplicate-numbering logic is skipped entirely when incremental mode is on.

---

## [3.3.3] - 2026-06-28

### Added
- **Live Transfers Panel** — a dynamic "Active Large-File Transfers" section appears above the progress bar whenever a file ≥50 MB is being copied; each active transfer gets its own row with filename and a live progress bar; rows appear/disappear automatically as transfers start and finish
- **Watchdog / freeze detector** — a background thread monitors disk I/O activity every 10 seconds; if no bytes have been written for 45 seconds, the operation is auto-cancelled with a clear warning dialog ("drive may be unresponsive") so the app never hangs silently due to a frozen drive

### Changed
- Large files (≥120 MB) now always use chunked I/O regardless of whether a progress callback is set, ensuring the watchdog always has accurate activity timestamps even in multi-source parallel mode

---

## [3.3.2] - 2026-06-28

### Added
- **Incremental pre-filter** — when Incremental mode is on, the full file list is scanned and stat-compared against the destination *before* any workers start, so workers only receive files that genuinely need copying; eliminates per-file lock contention during the skip phase

### Fixed
- Workers per source setting was not being saved or loaded correctly on the Multi-Source tab (was sharing the single-source `"workers"` config key); now uses its own `"multi_workers"` key

---

## [3.3.1] - 2026-06-28

### Changed
- Version bump for build release
- README, FEATURES.md, and PROJECT_SUMMARY fully rewritten to reflect current feature set (Move Mode, Multi-Source tab, Preview, checksum, incremental, network retry)
- Created `FileCopyMoveManager.spec` for PyInstaller builds

---

## [3.3.0] - 2026-06-28

### Added
- **Move Mode** — toggle between Copy Mode (gold theme) and Move Mode (red theme) using the COPY MODE / MOVE MODE buttons at the top of each tab; in Move Mode the source file is deleted after a successful copy+verify
- **Red theme** — `RED_COLORS` palette and mode-aware `get_stylesheet(mode)` function in `ui/styles.py`; the entire app repaints when the mode changes
- **Mode persistence** — last-used mode saved to `config.json` and restored on next launch
- Mode-aware UI: action button changes between "Copy Files" / "Move Files", window title reflects current mode, counters update "Copied:" → "Moved:" accordingly

### Changed
- Project renamed from **File Copy Manager** to **File Copy Move Manager** — folder, title, log filename, and all in-code references updated
- Version bumped to 3.3.0

---

## [3.2.0] - 2026-06-28

### Changed
- File type preset dropdown entries sorted alphabetically (Archives, Audio, Code, Data, Documents, Images, Videos) in both the Single Source and Multi Source tabs

---

## [3.1.2] - 2026-06-21

### Fixed
- Preview → Proceed to Copy no longer re-scans the source folder; the file list determined during preview is passed directly to the copy engine, eliminating wasted iteration through files that were already known to be skippable

---

## [3.1.1] - 2026-06-21

### Fixed
- Preview window now respects Incremental backup mode — files already at the destination with matching size and mtime (±2 s) are excluded from the preview list, so only files that would actually be copied are shown

---

## [3.1.0] - 2026-06-21

### Added
- **Preview window** — "Preview" button scans files on a background thread and shows a sortable table (Filename / Size / Full Path) before any copy starts; user can cancel or proceed
- **MD5 checksum verification** — optional "Verify copied files" checkbox computes MD5 hash of source and destination after each copy; mismatches are logged and counted as errors
- **Incremental backup mode** — optional checkbox skips destination files that already match source by size and mtime (±2 s tolerance), avoiding redundant copies
- **Network path retry logic** — copy operations automatically retry up to 3 times with a 1.5 s delay on `OSError`, supporting UNC paths and slow network shares transparently

### Changed
- Copy Options section now includes Incremental and Verify Checksum checkboxes
- `incremental` and `verify_checksum` settings persisted to `config.json`
- `_start_copy` refactored into `_build_copy_options` + `_execute_copy` so the Preview flow can reuse the same copy path
- Status log now surfaces Retry attempts and CHECKSUM FAILED messages

### Technical
- Added `ui/preview_dialog.py` — `PreviewDialog(QDialog)` with sortable QTableWidget
- Added `_compute_checksum()` to `FileCopier` — MD5 in 4 MB chunks
- `FileOperationResult` extended with `checksum_verified: Optional[bool]`
- Preview scan runs on a daemon thread using the existing queue/QTimer pattern

---

## [2.0.1] - 2026-03-29

### Fixed
- Current File Progress bar now accurately shows progress for large files
- Files under 120 MB use fast `shutil.copy2` (progress flashes 0→100 as expected)
- Files 120 MB and over use a 4 MB chunked copy loop with real-time progress callbacks
- Chunked copy respects Cancel button mid-file
- Preserves file metadata (`copystat`) when using chunked copy

## [1.0.1] - 2025-12-08

### Changed
- Updated window size to 1000x870 (matches File Rename Mover for consistency)
- Updated minimum window size to prevent UI clipping
- Fixed browse button visibility issues

## [1.0.0] - 2025-12-08

### Added
- Initial release of File Copy Manager
- Batch file copying with extension filtering
- Preserve original folder structure option
- Custom folder organization options:
  - Flat (all files in one folder)
  - By Year, Year/Month, Year/Month/Day
  - By Date, By Month
- Automatic duplicate file numbering (file_001.jpg, file_002.jpg, etc.)
- Option to skip duplicates instead of numbering
- Yellow and black theme for easy visual distinction from File Rename Mover
- Configuration persistence (remembers last used settings)
- Real-time status logging
- Scrollable UI optimized for 900x700 resolution
- Comprehensive error handling and validation
- Type hints and docstrings throughout codebase

### Technical
- Object-oriented architecture with separation of concerns
- ConfigManager for JSON-based configuration persistence
- FileCopier for copy operations with duplicate handling
- FolderOrganizer for flexible folder structure management
- YellowBlackTheme for distinctive UI appearance
- Uses shutil.copy2 to preserve file metadata

---

## Version Numbering

- **Major** (X.0.0): Breaking changes, major rewrites
- **Minor** (1.X.0): New features, backward compatible
- **Patch** (1.0.X): Bug fixes, minor improvements
