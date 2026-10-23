# File Copy Move Manager

A powerful dual-mode tool for batch **copying** or **moving** files with flexible folder organization, advanced filtering, and incremental backup support.

## Version 3.5.2

**Gold theme = Copy Mode | Red theme = Move Mode** — instantly distinguishable from the companion File Rename Mover (always red).

---

## What's New

### v3.5.2 — Preview lists only what needs doing
- The list shows only the files that will be copied; "Nothing to …" appears only when that list is empty (it no longer shows up under a heading that says there *are* files to copy).
- The counts of skipped files (up to date, file is older …) moved onto the **Also show the N files that will not be copied** box, which still adds them to the list on request.

### v3.5.1 — "Newest wins": newer source updates, older source is skipped
- With **Incremental on**, a file whose name is already at the destination is compared by **modified date** (never the created date — a copy resets that to "now"): a **newer source is copied over the older copy** (Preview: *Update (newer source)*), an **older source is skipped** (*Skipped — file is older*).
- Applies with *Number duplicate files* **off** (and always in Preserve-structure layouts). With numbering **on**, nothing is ever overwritten.
- Preview gains a **Current Size** column (next to *Source Size*), so a "newer" file that is 15× bigger than the one it replaces — a different rendition rather than a re-save — stands out.
- The newest of several different files with one name gets the plain name; a file's date is the date of its newest copy.

### v3.5.0 — Preview you can trust: copy, then Preview shows nothing
- **Preview compares the plan with what is at the destination now** — Pre-Destination Path / Date-Time (where the file will be written once folder structure, date folders and `_001` numbering are applied) next to Current Destination Path / Date-Time (what is there now), plus an Action for every file. It opens on the files that actually need copying; tick the box to see everything else too.
- **One planner for Preview, Copy and Multi-Source** (`copy_plan.py`) — what you preview is exactly what is copied, so after a clean copy the next Preview is empty.
- **Different images with the same name are never overwritten any more** — with *Number duplicate files* on they are kept as `name_001`, `name_002` …; with it off the later file is skipped and Preview says so.
- Numbered copies from earlier runs are recognised, one-hour daylight-saving date gaps are ignored, and same-size files with another date are compared by content before being called "changed".
- Fixes: **"Copyd" → "Copied"**; Move Mode could delete the source when Cancel hit mid-way through a large file; Multi-Source + Incremental crashed (`name 'self' is not defined`); the single-worker loop recounted results after every file.
- Copies are written to a temporary name and renamed when complete — a cancel or error never leaves a half-written file.
- 130 automated tests (`tests/`).

### v3.4.0 — Copy Order Control
- **Copy order dropdown** (both tabs) — choose how files are processed: **Largest first** (new default), Smallest first, Oldest first (modified date), or Directory order (as found)
- **Largest-first default** balances work across the parallel worker pool and eliminates the "idle worker tail" where most workers finish while one grinds the last few huge files; smallest-first keeps the progress count climbing fast; directory order preserves read locality on mechanical drives
- All date-driven behavior (age filter, date folder structure, oldest-first sort) consistently uses **modified** date — preserved across copies, unlike created date

### v3.3.7–v3.3.12 — Logging & Profiles
- **Saved profiles** — store a full set of settings and recall it from a dropdown; profiles are mode-agnostic (work for Copy and Move)
- **Per-file skip reasons in the log** — every skipped file is recorded with its reason (`duplicate`, `identical`, `unchanged`) so you can see exactly why files were skipped
- **Timestamped log per launch** — each run writes its own `FileCopyMoveManager_YYYY-MM-DD_HH-MM-SS.log`; the full path is shown in the status window on completion
- **Run-settings header** — every log opens with the complete set of settings used for that run, making it self-documenting and reproducible

### v3.3.0–v3.3.6 — Move Mode, Watchdog & Live Transfers
- **Copy/Move toggle** on each tab — Copy Mode (gold) vs Move Mode (red); the whole UI repaints to signal the active mode; in Move Mode source files are deleted after a successful copy + verify
- **Live Transfers panel** — files ≥ 50 MB get their own labeled progress row that appears/disappears as transfers start and finish
- **Watchdog / freeze detector** — auto-cancels with a clear warning if no disk I/O occurs for 45 s (e.g. an unresponsive drive)
- **Sequential multi-source** — sources process one at a time to avoid overwhelming USB controllers, while workers-per-source keep copying parallel within each source

### v3.3.0 — Move Mode
- **Copy/Move toggle** on each tab — switch between Copy Mode (gold theme) and Move Mode (red theme) with a single button; the entire UI repaints to signal the active mode
- In **Move Mode** source files are deleted after a successful copy + verify
- Mode is persisted to `config.json` and restored on next launch

### v3.1.0 — Preview, Checksum & Incremental Backup
- **Preview window** — scan files before any copy/move starts; sortable table shows filename, size, and full path; cancel or proceed
- **MD5 checksum verification** — optional; compares source vs destination hash after each file; mismatches logged as errors
- **Incremental backup mode** — skips files where destination already matches source by size + mtime (±2 s); safe to re-run repeatedly
- **Network path retry** — automatic 3-attempt retry with 1.5 s delay on `OSError`; works transparently for UNC paths and slow shares

### v3.0.0 — Multi-Source Tab & Performance
- **Multi-Source tab** — run the same copy/move template across multiple source folders in one pass
- All-files preset (`*.*`), errors counter, quiet status log, status box cap (500 entries), per-file progress threshold (≥ 50 MB)

---

## Features

### Two Operation Modes
| | Copy Mode | Move Mode |
|---|---|---|
| **Theme** | Gold / yellow | Red |
| **After copy** | Source intact | Source deleted |
| **Safety** | Non-destructive | Destructive — verify before use |

### Two Tabs
- **Single Source** — one source folder → one destination
- **Multi-Source** — list of source folders → one destination, same settings applied to each

### File Filtering
- **File mask / patterns** — wildcard support (`*.jpg`, `oct*.*`), comma-separated, with presets (Images, Videos, Audio, Documents, Archives, Code, Data, All Files)
- **File size filter** — min and max with unit selector (B / KB / MB / GB)
- **Date filter** — modified within last N days

### Folder Organization
| Mode | Result |
|---|---|
| Preserve structure | Exact hierarchy reproduced at destination |
| Flat | All files in one folder |
| By Year | `2025/file.jpg` |
| By Year/Month | `2025/12/file.jpg` |
| By Year/Month/Day | `2025/12/08/file.jpg` |
| By Date | `2025-12-08/file.jpg` |
| By Month | `2025-12/file.jpg` |

### Duplicate Handling
When a *different* file already has the name a file wants (common when you organize by date, because many folders hold a `photo.png`):
- **Number duplicates** — the new file is saved as `photo_001.png`, `photo_002.png` … (default, safest). Numbered copies from earlier runs are recognised, so re-running never adds more.
- **Skip duplicates** — leaves the existing file untouched and skips the new one. Preview and the completion message count these as *name in use* so you can see what was left out.

Identical files are never copied twice, in either setting. With **Incremental on** and numbering **off** the file with the **newest modified date wins** the name (see *Newest wins* below); with numbering **on**, or Incremental off, nothing is ever overwritten.

### Preview (what "up to date" means)
Click **Preview** to see the plan before anything is written. Every file is compared with what is already at the destination; it needs copying only when nothing there already represents it. Existing files count as "already there" when:

| Setting | A file is already there when … |
|---|---|
| **Incremental on** | a file with the same size and the same date exists (within 2 s, or exactly 1 hour apart for daylight saving). If only the date differs, the contents are compared so identical files are not reported as changed. Size + date are trusted, also between two source files. |
| **Incremental off** | a file with identical contents exists (MD5; only same-size files are compared) — nothing is trusted. |

"Existing file" includes `name_001`, `name_002` … made by earlier runs. After a copy with no errors, Preview shows nothing to copy; files that failed stay listed.

**Newest wins** (Incremental on, and Number duplicate files off — or a Preserve-structure layout). When a *different* file already has the name, the two are compared by **modified date**:

| Source vs. the copy at the destination | Result |
|---|---|
| Source is **newer** | **Update (newer source)** — it changed, so it is copied over the older copy |
| Source is **older** (or the same date) | **Skipped — file is older** — the destination copy stays |

When several different files share one name the newest gets it, so after a copy every name holds its newest version and the next Preview is empty. A file's date is that of its newest copy. Check the **Current Size** column before copying: an update that is many times bigger or smaller than the file it replaces is usually a different rendition (for example an original versus a resized copy), not an edit.

### Copy Order
- **Largest first** (default) — best load-balancing for parallel workers
- **Smallest first** — fastest-climbing progress count
- **Oldest first** — by modified date
- **Directory order** — as found on disk; preserves read locality on HDDs

### Progress & Status
- Overall progress bar (file count)
- Per-file progress bar for files ≥ 50 MB
- **Live Transfers panel** — dedicated progress row per active large-file transfer
- Live counters: Copied / Skipped / Errors (update after every file)
- Quiet status log — only errors, warnings, large-file copies, and job timing
- Start + end timestamps with elapsed time (HH:MM:SS.mm)
- Log capped at 500 entries; oldest drop off automatically

### Logging
- One timestamped log file per launch — never overwrites a previous run
- Opens with a full **run-settings header** (every setting used)
- **Per-file skip reasons** recorded (duplicate / identical / unchanged)
- Full log path shown in the status window on completion

### Reliability
- **Watchdog** auto-cancels if a drive stops responding (no I/O for 45 s)
- **Saved profiles** — recall a full settings set from a dropdown
- Sequential multi-source processing to protect USB controllers

### Copy Quality
- **Safe writes** — each file is copied to a temporary `~fcmm_….partial` name and renamed into place only when complete; a cancel or error never leaves a half-written file, and in Move Mode the source is deleted only after a complete copy is in place
- **Chunked I/O** — 8 MB chunks for files ≥ 120 MB; real-time progress and Cancel support
- **MD5 verification** (optional) — the copy is hash-checked before it is put in place
- **Incremental mode** (optional) — skip files that are already there (see *Preview* above)
- **Network retry** — 3 attempts, 1.5 s delay on `OSError`
- **Long path handling** — paths exceeding the Windows 260-char limit are shortened with a `_tr_001` suffix
- **Metadata preserved** — timestamps and attributes are copied with the file

### Configuration Persistence
All settings auto-saved to `config.json` on close and restored on next launch.

---

## Usage

### Running from Source
```
python main.py
```

Requires Python 3.10+ and PyQt6:
```
pip install PyQt6
```

### Basic Workflow
1. Choose **Copy Mode** or **Move Mode** (button at top of each tab)
2. Select source folder and destination folder
3. Enter file pattern(s) — e.g. `*.jpg`, `*.mp4, *.mov`
4. Set optional filters (size, date)
5. Choose folder organization and duplicate handling
6. Click **Preview** to review files first, or **Copy/Move Files** to start immediately

---

## Project Structure

```
File Copy Move Manager/
├── main.py                  # Entry point
├── config.py                # JSON configuration manager
├── copy_plan.py             # The planner — decides what happens to every file (Preview + Copy + Multi-Source)
├── file_operations.py       # FileCopier (executes a plan), FileScanner, FileValidator
├── folder_organization.py   # FolderOrganizer, FolderStructure enum
├── profiles.py              # ProfileManager — saved settings profiles
├── ui/
│   ├── main_window.py       # MainWindow — tab host, mode sync
│   ├── multi_source_tab.py  # MultiSourceTab — multi-folder batch
│   ├── preview_dialog.py    # PreviewDialog — plan vs. destination table
│   ├── save_profile_dialog.py    # Save-profile dialog
│   ├── manage_profiles_dialog.py # Manage-profiles dialog
│   ├── verbs.py             # "Copy"/"Copied", "Move"/"Moved" in one place
│   └── styles.py            # Gold + red themes, get_stylesheet(mode)
├── tests/                   # pytest: planner, copier, Preview, both tabs (python -m pytest tests)
├── app_icon.ico
├── config.json              # User settings (auto-generated)
├── README.md
├── CHANGELOG.md
└── FEATURES.md
```

---

## Use Cases

### 1. Photo Library Backup (non-destructive)
- Mode: Copy | Preserve structure | Incremental
- Re-run as many times as needed: unchanged files are skipped, changed files are updated in place, and Preview shows nothing when everything is backed up

### 2. Consolidate by Date
- Mode: Copy | By Year/Month | Number duplicates | Incremental
- Pulls scattered files into a chronological hierarchy; same-named different images are kept as `name_001` …
- Re-run any time — copies are recognised, so only new files are added

### 3. Archive and Clear (move)
- Mode: Move | Preserve structure | Number duplicates
- Files land at destination and are removed from source

### 4. Multi-Drive Consolidation
- Multi-Source tab | Flat | Number duplicates
- Point at five drives; all files land in one output folder with automatic numbering

---

## Version History

| Version | Date | Highlights |
|---|---|---|
| 3.5.2 | 2026-10-22 | Preview lists only the files to copy; "Nothing to …" only when there are none; skip counts on the "Also show" box |
| 3.5.1 | 2026-10-22 | "Newest wins": newer source updates, older source skipped ("file is older"); Current Size column |
| 3.5.0 | 2026-10-22 | Shared planner; Preview compares Pre-Destination with Current Destination; no more overwritten same-name images; "Copied" typo; Move/Cancel + Multi-Source fixes; tests |
| 3.4.2 | 2026-10-08 | New app icon + taskbar identity |
| 3.4.1 | 2026-06-30 | Total bytes copied reported on completion |
| 3.4.0 | 2026-06-29 | Copy order dropdown (largest-first default); modified-date consistency |
| 3.3.12 | 2026-06-29 | Log header uses plain `=` (cp1252-safe) |
| 3.3.11 | 2026-06-29 | Run-settings header written to log |
| 3.3.10 | 2026-06-29 | Timestamped log file per launch |
| 3.3.9 | 2026-06-29 | Per-file skip reasons logged; log path on completion |
| 3.3.7 | 2026-06-29 | Saved profiles |
| 3.3.6 | 2026-06-28 | Watchdog, live transfers, sequential multi-source, incremental fix |
| 3.3.1 | 2026-06-28 | Docs sync + build bump |
| 3.3.0 | 2026-06-28 | Move Mode, red theme, mode persistence, renamed from File Copy Manager |
| 3.2.0 | 2026-06-28 | File type presets sorted alphabetically |
| 3.1.2 | 2026-06-21 | Preview → Proceed reuses already-scanned file list (no re-scan) |
| 3.1.1 | 2026-06-21 | Preview respects Incremental mode |
| 3.1.0 | 2026-06-21 | Preview window, MD5 checksum, incremental backup, network retry |
| 3.0.0 | 2026-04-24 | Multi-Source tab, All Files preset, errors counter, quiet log |
| 2.1.0 | 2026-04-19 | PyQt6 migration from tkinter |
| 2.0.3 | 2026-04-03 | Live counters, path truncation, file logging |
| 2.0.1 | 2026-03-29 | Accurate per-file progress for large files |
| 2.0.0 | 2026-01-21 | Background threading, Cancel, file type presets |
| 1.2.0 | 2026-01-01 | Wildcard pattern filtering, multiple patterns |
| 1.1.0 | 2025-12 | Dual progress bars, size + date filters |
| 1.0.0 | 2025-12-08 | Initial release |

---

## Roadmap

- **Preview on the Multi-Source tab** — the planner already powers its runs; only the dialog is missing
- **Command-line interface** — headless mode for scripting / scheduled tasks (low priority, not started)

**Not planned here: duplicate detection across folders.** Date folders are chosen from each file's *modified* date, so a file whose date is re-stamped (by an edit or by a tool that resets dates) lands in a new month folder and is copied again; the earlier copy stays where it is. This app only compares a file with the destination it is headed for. Finding and removing byte-identical files across the whole backup is the job of the separate hash-dedupe app. For a backup with no drift, use the **Keep folder structure** layout: each file's destination follows its source path, so a re-stamped file updates in place (as long as the source folders aren't reorganised).

## Related Projects

- **File Rename Mover** — companion tool for moving and renaming files with custom patterns (always red theme)

## Author

**Cody's Corner** — [@codyscorner](https://github.com/codyscorner)

Contributions with AI assistance by Claude (Anthropic)
