# File Copy Move Manager — Features

## Overview

File Copy Move Manager is a companion tool to File Rename Mover. Where File Rename Mover moves and renames files, this tool **copies or moves files without renaming them**, with advanced filtering, flexible organization, and a visual mode system.

- **Gold theme** = Copy Mode (non-destructive, originals kept)
- **Red theme** = Move Mode (source deleted after successful copy + verify)

---

## 1. Dual Operation Mode

### Copy Mode (default, gold theme)
- Timestamps and attributes are copied with each file
- Source files never modified
- Safe to re-run — files already at the destination are recognised and skipped (see Preview)

### Move Mode (red theme)
- Same copy pipeline; the source is deleted only after a **complete** copy is in place and its size matches
- If the copy or verify fails — or you press Cancel / the watchdog fires part-way through a file — the source is preserved and the temporary partial copy is removed
- Files skipped because they are already at the destination are left where they are
- "Copy Files" / "Copied:" labels update to "Move Files" / "Moved:" throughout the UI
- Mode toggle appears at the top of both tabs and syncs between them

---

## 2. Single Source Tab

One source folder → one destination folder, all settings applied.

Workflow:
1. Browse source + destination
2. Enter file mask(s) and optional filters
3. Set folder organization and duplicate strategy
4. Preview (optional) then Copy/Move

---

## 3. Multi-Source Tab

Run the same copy/move template across **multiple source folders** in sequence.

- Add any number of source folders to a list
- Single destination + single set of options applied to every source
- Each source folder runs as an independent batch; counters accumulate across all
- Useful for consolidating multiple drives or network shares in one pass

---

## 4. File Filtering

### Pattern Masks
- Wildcard support: `*.jpg`, `oct*.*`, `photo_?.png`
- Multiple patterns, comma-separated: `*.jpg, *.png, *.heic`
- Preset dropdown: Images, Videos, Audio, Documents, Archives, Code, Data, All Files (`*.*`)
- Legacy `.jpg` input auto-converted to `*.jpg`

### Size Filter
- Minimum and maximum file size
- Units: B, KB, MB, GB
- Example: copy only files between 1 MB and 4 GB

### Date Filter
- Modified within last N days
- Example: copy only files changed in the last 30 days

---

## 5. Folder Organization

| Option | Destination path example |
|---|---|
| Preserve original structure | `Destination/Photos/2024/vacation.jpg` |
| Flat | `Destination/vacation.jpg` |
| By Year | `Destination/2024/vacation.jpg` |
| By Year/Month | `Destination/2024/08/vacation.jpg` |
| By Year/Month/Day | `Destination/2024/08/15/vacation.jpg` |
| By Date | `Destination/2024-08-15/vacation.jpg` |
| By Month | `Destination/2024-08/vacation.jpg` |

---

## 6. Duplicate Handling

A "duplicate" here means a **different** file that wants the same destination name (identical files are never copied twice). It is common when organizing by date: many folders contain a `photo.png`.

### Number Duplicates (recommended)
Appends `_001`, `_002`, etc. to the destination filename:
```
photo.jpg already exists (different image) → photo_001.jpg
```
Never overwrites; all distinct images are preserved. Numbered copies made by earlier runs are recognised, so re-running does not add more.

### Skip Duplicates
Leaves the existing file untouched and skips the new one. Preview and the completion message count these as **name in use**, so you can see what was left out and turn numbering on to keep them.

Both settings are honoured with Incremental on or off. With **Incremental on** and numbering **off** (and always in **Preserve structure** layouts, where a destination path belongs to exactly one source file) the file with the **newest modified date wins** the name — see *Incremental Backup Mode* below. With numbering **on**, or Incremental off, nothing is ever overwritten.

---

## 7. Preview Window

Click **Preview** to see exactly what a copy would do before anything is written.

- Runs on a background thread with progress; **Cancel** stops the scan
- Every file is compared with what is **already at the destination**. Table columns: Filename · Source Size · Source Path · **Pre-Destination Path** · **Pre-Destination Date/Time** · **Current Destination Path** · **Current Size** · **Current Date/Time** · **Action**
  - *Pre-Destination* = where the file will be written once the folder structure, date folders and `_001` numbering are applied, and the modified date the copy will carry
  - *Current Destination* = the file at the destination now that it is compared with (or "—" when there is none), with its size and modified date
  - All dates are **modified dates** (never created dates — a copy resets a file's created date to "now")
  - *Action* (with a status dot): New · New (numbered) · **Update (newer source)** · Up to date · Same content · Same as another source · **Skipped — file is older** · Skipped — name in use
- Opens on the files that need copying; **"Also show the N files that will not be copied"** adds the rest so you can see exactly what exists (opens that way automatically when there is nothing left to copy)
- Virtual table — stays instant with hundreds of thousands of rows (sorting 255,000 rows takes under a second); numeric/date sorting; resizable columns; hover for full paths and byte sizes
- Summary lines break the plan down by reason; a banner appears when files were skipped because their name is in use
- **Cancel** — abort; **Proceed** — runs exactly the plan you saw (no re-scan, no surprises)
- After a copy without errors the next Preview shows nothing to copy; files that failed stay listed

---

## 8. MD5 Checksum Verification

Optional checkbox on each tab. After every file is copied:

1. MD5 hash computed on source (4 MB chunks)
2. MD5 hash computed on destination copy
3. Mismatch → logged as an error, counted in Errors tally

Adds time but guarantees byte-for-byte integrity. Recommended for archival backups.

---

## 9. Incremental Backup Mode

Optional checkbox. A file is "already there" when the destination has a file (the plain name or its `_001`, `_002` … copies) with:

- the same size, and
- the same modified date — within ±2 s (filesystem rounding) **or exactly 1 hour apart** (daylight-saving artefact in older backups)

If only the date differs but the size matches, the contents are compared (MD5) so identical files are not reported as changed (files over 256 MB are not hashed). Size + date are trusted, also between two *source* files with the same name; turn Incremental off for byte-for-byte checking (same-size files are then always compared by MD5). Skipped files are counted with their reason. Makes repeated runs fast and safe.

### Newest wins (same name, different file)
When a *different* file already has the name (Incremental on, and Number duplicate files off — or a Preserve-structure layout), the **modified dates** decide:

- **Source newer** than the destination copy → it changed → **Update (newer source)**: copied over the older copy
- **Source older** (or the same date) → **Skipped — file is older**: the destination copy stays (a tie never flips between two different files)
- Several different files with one name: the **newest gets the plain name**, the others are older
- A file's date is the date of its **newest copy**, and that copy is the one copied
- If a *newer copy of the version already at the destination* exists at a source, an in-between file does not replace it (the next run would only flip it back)

Convergence: after a copy every name holds its newest version, so the next Preview is empty. Look at **Current Size** before copying — an update many times bigger or smaller than the file it replaces is usually a different rendition (an original versus a resized copy), not an edit.

---

## 10. Network Path Support

Automatic retry on `OSError` during copy:

- Up to **3 attempts** per file
- **1.5 s delay** between attempts
- Transparent to the user unless all 3 fail
- Covers UNC paths (`\\server\share\...`) and slow or flaky network shares

---

## 11. Progress & Status

### Progress Bars
- **Overall**: current file number / total files
- **Per-file**: chunked progress for files ≥ 50 MB; below threshold the bar flashes 0→100 instantly (fast copy, not meaningful to show)

### Live Counters
Copied / Skipped / Errors update after every single file.

### Status Log
- Quiet by default — only errors, warnings, large-file copies, path truncations, and job timing
- Start time shown at job begin; end time + elapsed (HH:MM:SS.mm) on completion
- Capped at 500 entries; oldest entries drop off automatically
- **Clear Status** clickable label to wipe the log between runs

---

## 12. Large File Handling

Files ≥ 120 MB use an **8 MB chunked copy loop**:

- Real-time per-file progress updates
- Responds to Cancel mid-file — the partial temporary file is removed and, in Move Mode, the source is kept
- `shutil.copystat` called after to preserve metadata

Smaller files are copied in one step (no meaningful per-file progress).

Every file — large or small — is written to a temporary `~fcmm_….partial` name next to its destination and renamed into place only when complete (and verified, if checksum verification is on). A leftover temp file from a crash is reported in the log and is safe to delete.

---

## 13. Long Path Handling

Windows MAX_PATH (260 characters) is automatically managed:

- Destination paths that would exceed the limit are shortened
- A `_tr_001` suffix replaces the end of the filename (decided by the planner, so Preview shows the shortened name)

---

## 14. Configuration Persistence

All settings saved to `config.json` on close and restored on next launch:

```json
{
  "default_source_folder": "",
  "default_destination_folder": "",
  "last_extension": "*.jpg",
  "preserve_structure": true,
  "folder_structure": "flat",
  "number_duplicates": true,
  "incremental": false,
  "verify_checksum": false,
  "operation_mode": "copy"
}
```

---

## 15. Copy Order

Files are scanned, filtered and ordered before any copy starts. The **Copy order** dropdown chooses: Largest first (default — best load-balancing across parallel workers), Smallest first, Oldest first (modified date) or Directory order. The planner keeps that order; the copier works through the plan in it.

---

## Technical Architecture

| Module | Classes | Responsibility |
|---|---|---|
| `config.py` | `ConfigManager` | JSON load/save/defaults |
| `copy_plan.py` | `build_plan`, `Plan`, `PlanItem`, `Action` | The planner: decides where every file goes and whether it needs writing (read-only; shared by Preview, Copy and Multi-Source) |
| `file_operations.py` | `FileCopier`, `FileScanner`, `FileValidator`, `FileOperationResult` | Scans, plans (via `copy_plan`) and executes a plan: safe temp-then-rename writes, retries, Move Mode |
| `folder_organization.py` | `FolderOrganizer`, `FolderStructure` | Date/structure sub-folder calculation |
| `ui/main_window.py` | `MainWindow` | Tab host, mode sync between tabs |
| `ui/multi_source_tab.py` | `MultiSourceTab` | Multi-folder batch tab |
| `ui/preview_dialog.py` | `PreviewDialog`, `PlanTableModel` | Plan-vs-destination table |
| `ui/verbs.py` | `mode_verbs` | "Copy"/"Copied", "Move"/"Moved" |
| `ui/styles.py` | `get_stylesheet(mode)`, `COLORS` | Gold + red themes |
| `tests/` | pytest suite | Planner rules, convergence (copy → Preview shows nothing), cancel/Move safety, dialogs |

---

## Comparison with File Rename Mover

| Aspect | File Rename Mover | File Copy Move Manager |
|---|---|---|
| **Primary action** | Move + rename | Copy or Move (toggle) |
| **Theme** | Red (always) | Gold = copy / Red = move |
| **File naming** | Custom patterns (prefix, datetime, etc.) | Original names preserved |
| **Duplicates** | Error or skip | Number automatically |
| **Folder org** | Date-based only | Preserve original OR 6 date options |
| **Multi-source** | No | Yes (Multi-Source tab) |
| **Backup safe** | No (moves originals) | Yes (Copy Mode) |
| **Best for** | Permanent organization | Backups and bulk moves |
