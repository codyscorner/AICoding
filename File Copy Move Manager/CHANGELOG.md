# Changelog

All notable changes to File Copy Move Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.5.3] - 2026-10-22

### Changed
- **The Recycle Bin is never scanned.** `$RECYCLE.BIN` (and its pre-Vista name `RECYCLER`) and `System Volume Information` are skipped at any depth, on both tabs, for Preview, Copy and Move. On the D:\ video backup the Recycle Bin had contributed 613 deleted Filmora preview videos (246 "new", 367 "older"), many sharing the names `preview.mp4` / `previewVideo.mp4`.
- 1 new test (153 in total).

### Note
- `*.ts` in the Video extension list also matches **TypeScript code**: D:\ had 5,791 `.ts` files under `node_modules` and no `.ts` videos. Remove `*.ts` from the extension box when backing up a drive that holds code.

## [3.5.2] - 2026-10-22

### Changed
- **Preview no longer prints "Nothing to do:" under a heading that says there are files to copy.** The line under the heading lists only what will be written (New / numbered / Update). "Nothing to copy …" appears only as the heading when nothing needs copying.
- **The list contains only files that need action**, also when there are none (it used to switch to showing every skipped file automatically). The skipped files are still one click away on the **Also show the N files that will not be copied** box, which now carries their breakdown (e.g. `up to date 42 · same image as another source 10 · file is older 2,759`).
- 1 new test (152 in total).

## [3.5.1] - 2026-10-22

**"Newest wins" — your update rule.** With Incremental on, a file whose name is already at the destination is now compared by **modified date** (never the created date: copying resets a file's created date to "now", so only the modified date means the same thing on both sides of a copy).

### Added
- **Source newer than the destination copy → the file changed → it is copied over the older copy.** Preview calls it **Update (newer source)**; the row shows the planned path/date next to the file it will replace, now with both sizes.
- **Source older than the destination copy → "Skipped — file is older"** (new reason, instead of "name in use"). A tie (same date, different bytes) keeps the destination copy, so two different files can never flip-flop.
- **Current Size column** in Preview (and "Source Size" for the other side), so a "newer" file that is 15x bigger than the one it replaces — a different rendition, not a re-save — is visible at a glance.
- When several *different* files share one name, the **newest** one gets the plain name (previously the oldest did); with numbering on the older ones become `name_001`, `name_002` …
- A version's date is the date of its **newest copy**, and that is the file copied (so the destination carries the newest date).
- Sources that match a destination copy that is about to be replaced are shown as "older" in the same Preview (not "up to date"), so Preview before and after the copy reads the same.
- Tooltips on the date columns say "Modified date (not the created date)"; "older" rows say which newer file they lost to.

### Changed (behaviour)
- Applies with **Incremental on and Number duplicate files off** (your saved profile) in any layout, and always in Preserve-structure layouts. With **Number duplicate files on** nothing is ever overwritten (a different file with the same name is kept as `name_001`, whatever its date). With Incremental off no dates are compared.
- Preserve-structure layouts no longer overwrite a destination copy that is *newer* than the source (they used to replace it with the older file).
- 21 new tests (151 in total), including repeated runs in which files are re-saved and added between runs: after every run the next Preview is empty and no source is both different and newer than its destination file.

### Docs
- README: dropped the "Already in the backup elsewhere" and "SQLite hash cache" roadmap items. Duplicate detection across folders belongs to the separate hash-dedupe app. Added a note explaining why date folders can make a second copy of a re-stamped file, and that Keep folder structure is the layout that doesn't drift.

---

## [3.5.0] - 2026-10-22

**Preview and Copy now share one planner, so after a copy the next Preview shows nothing.** Before this, an Incremental run into a date-organized destination could never finish: different images with the same file name (and month) fought over one destination file, each run swapped which one was there, and Preview kept listing ~15–19 thousand files no matter how often you copied. On a real 255,382-image backup it also meant thousands of distinct images were missing from the backup.

### Added
- **Preview compares what will be written with what is there now.** Columns: Filename, Size, Source Path, **Pre-Destination Path**, **Pre-Destination Date/Time** (the path after folder structure, date folders and numbering are applied, and the date the copy will carry), **Current Destination Path**, **Current Date/Time** (the file at the destination now), and an **Action** (New, New (numbered), Update (overwrite), Up to date, Same content, Same as another source, Skipped — name in use) shown with a status dot. It opens on the files that actually need copying; a checkbox adds everything else so you can see exactly what exists. Sorting by size/dates is numeric; columns are resizable; destination paths cut their left side so the date folder and file name stay visible; hover for full paths and sizes.
- **`copy_plan.py` — the planner** (`build_plan`). It decides, for every source file, where it will be written and whether it needs writing. Preview shows its plan, Copy executes exactly that plan, and the Multi-Source tab uses it too (one rule set for both tabs).
- **Numbered copies are recognised.** `photo.png`, `photo_001.png`, `photo_002.png` … at the destination all count as "already there", so earlier numbered copies are never copied again.
- **Daylight-saving aware.** A date that differs by exactly one hour (±2 s) counts as the same date. On the test backup this alone explained 8,820 false "changed" files.
- **Content check when only the date differs.** Same-size files with another date are compared by MD5 (files over 256 MB are not hashed in Incremental mode) so identical files are not reported as changed.
- **Honest summaries.** Preview and the completion message break skips down by reason (already up to date / same content / same image as another source / name in use) instead of one bare number. When every remaining file is skipped because its *name is in use by a different file*, Preview says so instead of claiming everything is already at the destination.
- Preview can be cancelled while it scans; its status shows progress ("Comparing file contents… 1,200 of 5,888").
- A note is logged if a leftover `~fcmm_*.partial` temp file from an interrupted copy is found at the destination.
- **Automated tests** (`tests/`, 130): every matching rule, randomized convergence across all option combinations, cancel/move safety, and the Preview dialog.

### Changed (behaviour — please read)
- **Incremental never overwrites a different file that happens to share a name** in Flat / By-Date layouts. Previously it silently replaced it, which is how images were lost from the backup. In Preserve-structure (mirror) layouts, where a destination path belongs to exactly one source file, a changed file is still updated in place.
- **"Number duplicate files" is honoured with Incremental on** (it used to be ignored). With it **off**, a name already used by a *different* file means the new file is **skipped, never overwritten**, and it is counted and explained. Turn numbering on to keep both as `name_001`, `name_002` …
- Incremental still means "size + date are enough", also between two source files (same name, size and date = same file). Switch Incremental off for byte-for-byte checking.
- **Number-duplicates mode is now repeatable.** It used to add another identical `photo_002`, `_003` … on every re-run (it only compared against the plain name).
- Copies are written to a temporary `~fcmm_….partial` name next to their destination and renamed when complete, so a cancel or failure never leaves a half-written file under the real name.
- Multi-Source: the planner replaces the separate incremental pre-filter; parallel workers can no longer overwrite or falsely skip each other (each destination path has exactly one writer).

### Fixed
- **"Copyd" is now "Copied"** — in the Preview heading, the Copied counter label and the Multi-Source "Total Copied" label (new `ui/verbs.py` holds the verb forms in one place).
- **Move Mode could delete the source and leave a truncated copy** if Cancel (or the watchdog) hit in the middle of a file of 120 MB or more. The source is now deleted only after a complete copy is in place and its size matches.
- **Multi-Source with Incremental on crashed** with `name 'self' is not defined` as soon as any file was already up to date.
- The single-worker copy loop recounted every finished file after each file (quadratic); on a 255,000-file run that was roughly 23 minutes of pure counting. Counters are now running totals.
- The live-transfer row stayed on screen if a large copy failed.
- Cancel during Preview did nothing; it now stops the scan.

---

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
