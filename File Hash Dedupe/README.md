# File Hash Dedupe

A desktop application that finds and removes duplicate files based on content hash (MD5 or BLAKE2b), using a SQLite hash cache.

## Features

- **SQLite Hash Cache**: every file's full path, size, modified time and hash is stored in `FileHashDedupe_hashes.db` next to the EXE; a rescan only hashes files that are new or changed since the last run
- **Duplicates Decided in SQL**: every copy of a hash gets a rank with `ROW_NUMBER() OVER (PARTITION BY hash ORDER BY <keep rule>)` - rank 1 is kept, every rank above 1 is moved or deleted (the same method as Burn List Creator)
- **Fast Parallel Hashing**: Configurable parallel workers for high-speed file hashing
- **Content-Based Detection**: Identifies duplicates by file content, not just filename
- **Two Dedupe Modes**: Move duplicates to a `Dupes` subfolder, or permanently delete them
- **Recursive Scanning**: Option to scan subdirectories (recycle bins and System Volume Information always skipped)
- **Maximum File Size**: skip files larger than a set size (default 100 MB) so big model files are never hashed
- **Progress Tracking**: Real-time progress bar and status log
- **Cancellable**: Cancel mid-run at any time

## Usage

1. **Select Source Folder**: Browse to the folder to scan for duplicates
2. **Configure Options**:
   - Check "Search subfolders recursively" if needed
   - Check "Permanently delete duplicates" to skip the Dupes folder and delete directly
3. **Click "Find Duplicates"** to begin processing

### Output — Move Mode (default)

- First occurrence of each unique file stays in place (primary)
- All duplicates are moved to `Source Folder/Dupes/`
- Review the Dupes folder and delete when satisfied

### Output — Permanent Delete Mode

- First occurrence of each unique file stays in place (primary)
- All duplicates are permanently deleted — **cannot be undone**
- A confirmation dialog is shown before processing begins

## Building Executable

```bash
pip install pyinstaller
pyinstaller FileHashDedupe.spec --clean --noconfirm
```

## Version History

### v1.4.2
- Recycle bins (`$RECYCLE.BIN`, `RECYCLER`) and `System Volume Information` are never scanned; rows already in the hash cache from those folders are removed when the database opens (schema v2)
- New option "Skip files larger than ___ MB" (on, 100 MB by default): bigger files (models, .safetensors, disk images) are not hashed and never moved or deleted. The limit is applied in the SQL queries, so those files stay listed and any cached hashes for them are kept for when the limit is raised
- Status log reports how many files were ignored for size

### v1.4.1
- Options rows no longer overlap or clip at 125-150% Windows display scaling: the window's minimum height now comes from its layout instead of a hard-coded 760 px, so it can't be shrunk below what the controls need
- More space between Options rows (16 px) and a taller Clear Cache button

### v1.4.0
- Scan rewritten on SQLite (`hash_db.py`): pass 1 lists every file (one row per full path), the size pre-filter runs as a SQL query, pass 2 hashes only candidates without a cached hash, and duplicates are picked with `ROW_NUMBER()` - rank 1 kept, rank > 1 removed
- Hash cache persists between runs, per algorithm (MD5 and BLAKE2b cached separately); a file whose size or modified time changed is re-hashed; moved/deleted duplicates and files that vanished are dropped from the cache
- Cancelling mid-hash keeps every hash finished so far - the next scan picks up where it stopped
- Changing the keep rule in the review screen is a single SQL re-rank
- Compare mode refuses overlapping folders (target inside reference or the other way round), which used to make every target file match itself
- Options box: new "Hash cache" line (cached hashes / files) with a Clear Cache button
- Review screen: compare mode now shows the kept reference (A) file at the top of each group; groups are listed largest files first; dialog is larger and builds faster on big result sets
- Long paths (> 260 chars) handled for hashing, moving and deleting
- First test suite: `tests/test_hasher.py` (16 tests)

### v1.3.1
- Options box spaced out: rows no longer get squeezed together when the window is short — the box keeps its natural height and the Status log shrinks instead
- Hash algorithm / Keep dropdowns are now styled (they were collapsing to thin bars), and the workers spinbox is taller and wider
- Window minimum height raised to 760 px (still fits a 1080p screen)

### v1.3.0
- Preview/review screen before any move or delete — shows every duplicate group with the chosen primary highlighted; keep rule (First alphabetical / Oldest / Newest / Shortest path) can be changed live in the dialog to recompute the survivor without re-hashing
- Size pre-filter pass — files are only hashed if another file shares their exact size, skipping the hash for files that can't possibly have a duplicate (big speed win on large folders)
- Hash algorithm choice: MD5 (default) or BLAKE2b, both stdlib — no new dependency
- CSV report option — writes `dedupe_report_<timestamp>.csv` (group hash, role, path, size, action) alongside the run
- Compare two folders mode — dedupe Folder B against Folder A without ever touching A; matches are found by content hash and only removed from B

### v1.2.0
- Added permanent delete mode — skip Dupes folder and delete duplicates directly
- Fixed UI freeze when processing large duplicate sets (throttled status logging + capped message queue drain per tick)

### v1.1.0
- Configurable hashing worker count
- Config persistence across sessions

### v1.0.0
- Initial release

## Future Enhancements

- [x] Preview/review screen before delete — pick which copy survives (keep oldest/newest/shortest path rules)
- [x] Size pre-filter pass (only hash same-size files — big speed win)
- [x] BLAKE2b option, faster than MD5 (stdlib, no added dependency — chosen instead of xxHash/BLAKE3 to avoid new packages)
- [x] CSV report of duplicate groups
- [x] Compare two folders mode (dedupe B against A without touching A)
