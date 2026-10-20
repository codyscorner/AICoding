# Burn List Creator — Build Plan

A Windows desktop app that scans one or more folders/drives, hashes every file into a local
SQLite database, finds duplicates by content, and produces a **deduplicated burn list** split
into disc-sized sets (DVD / DVD-DL / Blu-ray / BD-DL) so an archive can be burned with no
duplicate files.

Feed this file to VS Code / Claude Code as the build spec. Build phase by phase; each phase
ends with something runnable and an acceptance check.

---

## 1. Goals and non-goals

**Goals**
- Hash large folder trees quickly, and *incrementally* (rescans only re-hash changed files).
- Keep ALL copies in the database (backups may contain 3-4 copies of the same image — that is fine);
  only the burn list is deduplicated.
- Pick one canonical copy per hash using user-controlled priority rules.
- Split the deduplicated set into discs that fit the chosen media, with a safety margin.
- Export per-disc output the user can burn with Windows' built-in burner / ImgBurn / etc.
- Remember what has already been burned so the *next* archive skips it.
- Verify a burned disc against the database.

**Non-goals**
- No burning engine inside the app (v1). It stages files / writes lists; the user's burn tool burns.
- No deleting or modifying source files. Ever. The app is read-only against sources.

---

## 2. Stack and project rules (match the rest of the repo)

- **Python + PyQt6**, single-file portable EXE via PyInstaller.
- **SQLite** via stdlib `sqlite3` (needs >= 3.25 for window functions; Python 3.8+ bundles this).
  Assert `sqlite3.sqlite_version_info >= (3, 25)` at startup.
- Source folder: `P:\AI\VideCoding\Burn_List_Creator\`
- Deploy EXE to: `P:\Apps\AICoded\Burn_List_Creator\Burn_List_Creator.exe`
  (overwrite in place; keep the replaced EXE as `Burn_List_Creator_<YYYYMMDD_HHMMSS>.exe.bak`, never overwrite a .bak).
- **Config and DB live next to the EXE** (portable): `settings.json`, `burnlist.db`. Never `%APPDATA%`.
  In dev (not frozen) use the project folder. Resolve with `sys.frozen` / `sys.executable`.
- **Navy blue theme** by default: copy the `COLORS` palette from the TodoList v1.1.0 app. Do not use purple.
- Status readouts = solid light text with a coloured `●` dot in front, never tinted text.
- **Fit 1920x1080**: split long forms into two equal columns; verify with an offscreen `grab()`.
- Every project keeps `README.md` (with a "Recent Changes" section) and `CHANGELOG.md`.
  Commit both. No `README.txt`, no `PROJECT_SUMMARY.md`.
- **Bump the version (main.py + README + CHANGELOG) before every EXE build.** Start at `0.1.0`.
- **Build with the shared `.venv`** and the standard `--exclude-module` list (torch, tensorflow, etc.),
  otherwise the EXE balloons ~10x. Don't name any local module after a PyPI package that has a
  PyInstaller contrib hook (e.g. do not name a file `workflow.py`).
- `*.spec` is gitignored in this repo.
- Icon: generate through the IconMaker pipeline (3-part wiring: icon file, spec, window icon).

---

## 3. Architecture

Keep the core free of Qt so it is testable and usable from a CLI.

```
Burn_List_Creator/
  main.py                 # entry, version, theme, single-instance, sqlite version check
  core/
    db.py                 # connection, schema, migrations (PRAGMA user_version), queries
    hasher.py             # file hashing (BLAKE2b), quick-hash, chunk reader
    scanner.py            # walk + incremental hash engine (thread pool), cancel, progress
    planner.py            # dedupe ranking, exclusions, bin packing into discs
    exporter.py           # stage/copy, lists, manifests, scripts
    verifier.py           # hash a mounted disc and compare to the DB
    media.py              # media presets and capacities
    paths.py              # exe-relative paths, long-path (\\?\) helpers
  ui/
    main_window.py        # tabs
    sources_tab.py
    scan_tab.py
    duplicates_tab.py
    burnset_tab.py
    discs_tab.py          # history of burned discs + verify
    settings_dialog.py
    theme.py
  tests/                  # pytest, temp dirs, no GUI
  README.md  CHANGELOG.md  PLAN.md
```

**Threading rules**
- Scanning/hashing/verify run in worker threads (`QThread` + a Qt-free engine class with a
  `progress_cb` and a `threading.Event` cancel flag).
- Hashing uses `ThreadPoolExecutor` (hashlib releases the GIL on large buffers). Default workers = 4,
  configurable (spinning disks do better with 1-2; SSD/NVMe with more). **One DB writer** only:
  workers return results via a queue, a single thread batches INSERT/UPDATEs.
- **Never emit file byte counts through `pyqtSignal(int)`** — it overflows at 2 GB (this bit
  Style Randomizer / Video Creator). Use `pyqtSignal(object)` or `float` for byte counts.

---

## 4. Database schema (SQLite)

Set on connect: `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;`
Track schema version with `PRAGMA user_version` and a migration list in `db.py`.

```sql
CREATE TABLE roots (
    id        INTEGER PRIMARY KEY,
    path      TEXT NOT NULL UNIQUE,       -- absolute scan root, e.g. D:\Backups\Image1
    label     TEXT,                       -- friendly name
    priority  INTEGER NOT NULL DEFAULT 100, -- lower = preferred as the canonical copy
    enabled   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE files (
    id         INTEGER PRIMARY KEY,
    root_id    INTEGER NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
    relpath    TEXT NOT NULL,             -- relative to root
    size       INTEGER NOT NULL,
    mtime_ns   INTEGER NOT NULL,
    hash       TEXT,                      -- NULL until computed (hex BLAKE2b-256)
    hashed_at  TEXT,
    last_seen  INTEGER NOT NULL,          -- scan_id that last saw it
    missing    INTEGER NOT NULL DEFAULT 0,-- file vanished since last scan
    UNIQUE(root_id, relpath)
);
CREATE INDEX idx_files_hash ON files(hash);
CREATE INDEX idx_files_size ON files(size);

CREATE TABLE scans (
    id INTEGER PRIMARY KEY, started TEXT, finished TEXT,
    files_seen INTEGER, files_hashed INTEGER, bytes_hashed INTEGER, errors INTEGER
);

CREATE TABLE scan_errors (            -- unreadable files, permission, path too long
    scan_id INTEGER, root_id INTEGER, relpath TEXT, message TEXT
);

CREATE TABLE discs (                  -- one row per burned (or planned) disc
    id INTEGER PRIMARY KEY, label TEXT NOT NULL, media TEXT, created TEXT,
    status TEXT NOT NULL DEFAULT 'planned',   -- planned | staged | burned | verified
    verified_at TEXT, notes TEXT
);

CREATE TABLE disc_files (             -- the canonical file chosen for each hash on a disc
    disc_id INTEGER REFERENCES discs(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    file_id INTEGER REFERENCES files(id),
    size INTEGER NOT NULL,
    disc_path TEXT NOT NULL,          -- path as written on the disc
    PRIMARY KEY (disc_id, hash)
);
CREATE INDEX idx_disc_files_hash ON disc_files(hash);
```

**Ranking view** (a view, not a stored flag, so it can never go stale):

```sql
CREATE VIEW file_ranked AS
SELECT f.*, r.priority AS root_priority, r.path AS root_path,
       ROW_NUMBER() OVER (
           PARTITION BY f.hash
           ORDER BY r.priority ASC, f.mtime_ns ASC, length(f.relpath) ASC, f.relpath ASC
       ) AS dup_rank,
       COUNT(*) OVER (PARTITION BY f.hash) AS copies
FROM files f
JOIN roots r ON r.id = f.root_id
WHERE f.hash IS NOT NULL AND f.missing = 0 AND r.enabled = 1;
```

`dup_rank = 1` is the file to archive. Filter it in an outer query/CTE (window results can't be
used in the same-level `WHERE`).

"Already archived" = a hash present in `disc_files` whose disc status is `burned` or `verified`.

---

## 5. Hashing and scanning rules

- **Algorithm:** `hashlib.blake2b(digest_size=32)`, 4 MB chunk reads (`readinto` a reusable buffer).
  Store lowercase hex. Put the algorithm name in a `meta` table / settings so it can change later.
- **Incremental:** for each walked file, if `(size, mtime_ns)` match the DB row, skip hashing and
  just update `last_seen`. Otherwise (new or changed) re-hash.
- **Size pre-filter (optional speed mode, default OFF):** only full-hash files whose size is shared
  with at least one other file. Files with a unique size cannot be duplicates, but they STILL need a
  hash if they are going to be burned/verified — so in this mode hash them lazily at export time.
  Keep default = hash everything; it is simpler and the cache makes rescans cheap.
- **Walking:** `os.scandir` recursive, do not follow symlinks/junctions (avoid loops). Use the
  `\\?\` long-path prefix for paths over 240 chars.
- **Exclusions** (Settings, one pattern per line, `fnmatch`): defaults `Thumbs.db`, `desktop.ini`,
  `$RECYCLE.BIN`, `System Volume Information`, `*.tmp`. Plus optional min-size and max-size filters.
- **Missing files:** after a scan of a root, rows not seen this scan get `missing=1` (kept, not deleted,
  so history/disc references survive). Rows come back to `missing=0` if they reappear.
- **Errors** (access denied, locked, path too long, read error mid-file) go to `scan_errors`; the scan
  continues. Show an error count with a "view errors" button.
- **Progress:** files done / total (after an initial fast count pass), bytes done, MB/s, ETA, current
  file. Cancel must stop within about a second and leave the DB consistent (commit per batch of ~500).

---

## 6. Dedupe and disc planning

**Canonical selection:** `dup_rank = 1` from `file_ranked`. Priority order is user-editable in the
Sources tab (drag rows or priority spinbox) — e.g. "Master" first so the burn list prefers it.

**Skip already burned:** checkbox "Exclude files already on a burned disc" (default ON) — drop any
hash that exists in `disc_files` for a `burned`/`verified` disc. This is what makes incremental
archives possible.

**Media presets** (`media.py`), usable bytes after a safety margin (default 2%, configurable, plus a
fixed filesystem overhead allowance per file/dir of ~4 KB):

| Preset | Nominal | Notes |
|---|---|---|
| DVD-5 | 4.7 GB (4,700,000,000 B) | |
| DVD-9 (DL) | 8.5 GB (8,540,000,000 B) | |
| BD-25 | 25 GB (25,025,000,000 B) | |
| BD-50 (DL) | 50 GB (50,050,000,000 B) | |
| Custom | user bytes | |

**Splitting algorithm:** first-fit-decreasing bin packing by file size across discs (cheap, good
enough). Files bigger than one disc are reported as "too large for media" and listed, not silently
dropped. Option "Keep folders together" (v2): pack by top-level folder instead of per file.

**Disc layout on the disc:** preserve the source structure as `<RootLabel>\<relpath>` so the disc is
browsable and the manifest can map back. Warn if any resulting name exceeds the target filesystem's
limits (use UDF for DVD/BD — long names fine; warn on names > 255 chars or illegal characters).

---

## 7. Export outputs (per disc, in a chosen output folder)

For disc `Archive_2026-10-20_01`:
- `Archive_..._01\` — **staging folder** with the files copied (default) so the user drags it into
  the burn tool. Copy with progress, MB/s, ETA, cancel; verify each copied file's size (full re-hash
  optional).
- `Archive_..._01_files.txt` — plain list of source paths to burn.
- `Archive_..._01_manifest.csv` — `hash, size, disc_path, source_path`.
- `Archive_..._01_skipped_duplicates.csv` — every duplicate NOT burned and which kept file it
  duplicates (so a restore can reconstruct all names).
- `Archive_..._01.sha256`-style checksum file (BLAKE2b list) **also written onto the disc root**
  as `MANIFEST.csv` so the disc is self-verifying later.
- Optional: `.bat` / robocopy script as an alternative to the staging copy.

Writing the export also creates the `discs` + `disc_files` rows with status `staged`. The user
marks a disc `burned` manually after burning (button), which is what makes "skip already burned" kick in.

---

## 8. UI (tabs, navy theme)

1. **Sources** — table of roots (path, label, priority, enabled). Add folder / drive (multi-add),
   remove, reorder. Two-column compact layout.
2. **Scan** — Start / Cancel, "Rescan all", per-root rescan; progress bar, files, MB/s, ETA, current
   file, error count. Status line = `●` dot + text.
3. **Duplicates** — summary tiles: total files, unique hashes, duplicate files, GB reclaimable.
   Table of duplicate groups (hash short form, copies, size, paths); expanding a group shows every
   copy with the kept one marked. Right-click: open containing folder, copy path, "make this the
   kept copy" (writes a per-hash override table `keep_overrides(hash, file_id)` used by the ranking).
4. **Burn Set** — choose media, margin, exclusion options → **Build plan**. Shows disc-by-disc
   breakdown (files, GB used, % full), too-large list, totals, and how many duplicates are skipped.
   **Export selected disc / all discs** button with output folder picker.
5. **Discs** — history of discs (label, media, status, date, file count). Buttons: mark burned,
   **Verify disc…** (pick the drive/folder), delete plan (planned/staged only).
6. **Settings** (dialog) — worker count, chunk size, exclusions, safety margin, default media,
   default output folder, hash algorithm (read-only for now).

Must fit 1080p; tables get sortable headers and a type-to-filter box (match other apps).

---

## 9. Verify disc

Pick a mounted disc (or any folder). Read `MANIFEST.csv` from its root, re-hash each listed file on
the disc, compare to the stored hash, report OK / MISSING / MISMATCH counts and list failures. On
success set the disc status to `verified` and stamp `verified_at`. Run in a worker thread with the
same progress/cancel behaviour.

---

## 10. Build phases (do in order)

**Phase 1 — Core + CLI (no GUI)**
- `paths.py`, `db.py` (schema, migrations, view), `hasher.py`, `scanner.py`.
- Tiny CLI in `main.py --cli`: `add-root`, `scan`, `dupes`, `plan`.
- Tests: temp dir with known duplicate files -> correct hashes, correct `dup_rank`, rescan skips
  unchanged files, changed file re-hashes, deleted file flagged `missing`, unreadable file lands in
  `scan_errors`, scan cancel leaves a consistent DB.
- *Accept:* scanning two folders with planted duplicates yields the right duplicate groups and a
  rescan hashes zero bytes.

**Phase 2 — Planner + exporter**
- `media.py`, `planner.py` (ranking query, exclusions, already-burned filter, first-fit-decreasing),
  `exporter.py` (staging copy, lists, manifest, skipped-duplicates CSV, disc rows).
- Tests: bin packing never exceeds capacity; every unique hash appears exactly once across discs;
  oversize file reported; manifest round-trips.
- *Accept:* CLI `plan` + `export` on a test tree produces correct per-disc folders and manifests.

**Phase 3 — GUI shell**
- Navy theme, tabs, Sources + Scan tabs wired to the engine with threaded progress.
- *Accept:* add a drive, scan it, see live MB/s + ETA, cancel works, UI never freezes.

**Phase 4 — Duplicates + Burn Set + Discs tabs**
- Duplicate groups browser with keep-override, plan builder UI, export UI, disc history,
  mark-burned.
- *Accept:* full workflow from the UI: scan -> review dupes -> pick BD-25 -> export -> mark burned
  -> next plan excludes those files.

**Phase 5 — Verify, polish, ship**
- Verify disc, scan-errors viewer, Settings dialog, long-path handling pass, 1080p offscreen check.
- README.md (+ Recent Changes), CHANGELOG.md, icon via IconMaker, bump version, PyInstaller build
  with `.venv` + excludes, deploy to `P:\Apps\AICoded\Burn_List_Creator\`, keep timestamped `.bak`.
- *Accept:* EXE runs standalone from the deploy folder, creates `settings.json` and `burnlist.db`
  next to itself, completes the full workflow on a real folder.

---

## 11. Decisions already made (don't re-ask)

- Keep duplicates in the DB; dedupe only at plan time, via a **view** with `ROW_NUMBER()`.
- BLAKE2b-256 over SHA-256 (faster, in stdlib).
- App never burns and never modifies sources; it stages + lists.
- Config and DB are portable, next to the EXE.

## 12. Open questions for the user (defaults chosen if unanswered)

- Default canonical-copy preference: **root priority, then oldest mtime** (changeable).
- Preferred burn tool for the staging folder: assume Windows built-in "Burn to disc" / ImgBurn.
- Want an optional **fast mode** (size pre-filter) on by default? Default: **off**.
