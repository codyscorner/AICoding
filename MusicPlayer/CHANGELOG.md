# Changelog

All notable changes to Music Player are recorded here.

## Unreleased
- **Icon-only buttons now have a short text label.** Buttons that showed only a symbol (↻, …, 🎲, 🗑 and so on) now read e.g. "↻ Refresh" or "Browse" in regular-weight, regular-size text; their fixed widths were dropped so they size to their label. Covers: ◄◄ Prev, ▶ Play / ❚❚ Pause, ►► Next, 🔀 Shuffle, 🔁 Repeat / 🔂 Repeat 1, and the playlist ＋ New, ✎ Rename, 🗑 Delete. Sidebar starts a little wider (250 px) to fit them.

## [1.0.0] - 2026-07-03
### Added — Phase 6: shortcuts, Explorer drag-in, first EXE
- **Keyboard shortcuts** (when the list has focus): Space = play/pause,
  Enter = play selected, ←/→ = seek ∓5s, Ctrl+←/→ = previous/next, Del = remove.
- **Drag files/folders from Explorer** into the track list to add them to the
  Library (`iter_paths` handles a mix of files+folders; `ScanWorker` now takes a
  list of sources).
- `Player.seek_relative` for the arrow-key seeking.
- Packaged as a standalone Windows app with PyInstaller (icon bundled via
  `resource_path`); build output to `P:\Apps\AICoded\Music Player\`.

## [0.8.0] - 2026-07-03
### Added — Export playlist to a folder
- Right-click a playlist (or Library) in the sidebar ▸ **Export…** to copy the
  actual audio files to any folder (e.g. a USB drive). `core/export.py` +
  `ui/export_dialog.py`.
- Export options: **Flat** (all files in one folder, same-named files
  auto-disambiguated as "name (2)") or **Preserve original subfolders**; and
  **Skip** vs **Overwrite** when a file already exists.
- Optional **.m3u** playlist file written in the destination (relative paths,
  #EXTINF with duration + "Artist - Title"). Deliberately no car-specific format.
- Copy runs on a worker thread with a cancelable progress dialog.

## [0.7.0] - 2026-07-02
### Added — App icon
- App icon (`assets/icon.png` + multi-size `assets/icon.ico`, 16–256px) generated
  via local ComfyUI (dark-navy musical-note, matches the theme). Set as the window
  icon in `main.py`; `icon.ico` is ready for the PyInstaller `--icon` flag.

### Added — Configurable Library root + drag-to-playlist + removal rules
- **Library folder** (menu ▸ Library ▸ Set Library Folder… / Rescan Library):
  point the Library at a root folder and it lists every song beneath it
  (recursive), replacing prior contents. Stored in settings; rescan anytime.
- **Drag tracks onto a playlist**: select rows in the list and drag them onto a
  playlist in the sidebar to add them (`PlaylistSidebar` drop target).
- **Remove from the active list**: Delete key or right-click ▸ Remove from list.
  Works on named playlists only.
- **Library is protected**: it mirrors your files, so it can't be hand-removed or
  cleared or deleted. The only way a track leaves the Library is the missing-file
  prompt.
- **Missing-file prompt**: playing a track whose file is gone asks whether to
  remove it — and if yes, it's removed from the Library *and every playlist* that
  referenced the same path (`playlist.remove_path_everywhere`).

## [0.6.0] - 2026-07-02
### Added — Phase 5: Named playlists
- **Left sidebar** listing a special **Library** view plus your saved playlists;
  click one to load it (replaces the current list). New / Rename / Delete buttons.
- **Add to playlist** in the track right-click menu: pick an existing playlist or
  "New playlist…" to create one from the selected tracks (dedups by path).
- Named playlists are stored one-JSON-per-playlist under the app data folder
  (`core/playlist.py`: list/save/load/delete/rename/add_to_playlist); names are
  URL-quoted so any characters are a safe, reversible filename.
- Editing a view (reorder/remove/clear/add-folder) saves back to the right place —
  the Library saves to the session, a named playlist saves to its own file.
- Right-clicking an unselected row now selects it first.

## [0.5.0] - 2026-07-02
### Added — Phase 4: Playlist power
- **Drag-and-drop reorder** (`ui/playlist_view.PlaylistTable`): drag rows to a new
  position; the list renumbers and the new manual order is saved to the session.
- **Right-click context menu**: Play, Remove from list, Reveal in Explorer,
  Properties (metadata dialog), and Clear playlist.
- **Repeat** (off / all / one) and **Shuffle** buttons in the transport bar.
  Repeat-one replays the current track at its natural end; repeat-all wraps at the
  ends. Shuffle plays every track once before repeating (bag + history for
  Prev/Next); both settings persist across launches.
- Removing/reordering/clearing auto-saves the session.

## [0.4.0] - 2026-07-02
### Added — Session persistence (Phase 5, brought forward)
- `core/playlist.py`: the exact playlist (all files + cached tags, in order) is
  auto-saved to `session.json` in the app data folder and restored on startup, so
  a list assembled from several folders survives a restart. Missing files are
  dropped on load.
- Startup now restores the saved session instead of re-scanning only the single
  last-added folder (the old behavior that lost multi-folder playlists). The last
  folder is still used as the Add Folder dialog's starting directory.
- Session is saved after each folder scan completes.

## [0.3.1] - 2026-07-02
### Fixed
- `run.bat` now launches with the project venv's python (`..\.venv\Scripts\
  python.exe`) instead of whatever `python` is on PATH. Double-clicking the .bat
  ran in a cmd shell that resolved a different global python without tinytag, so
  the app silently fell back to filenames and showed blank Artist/Album/Time.

## [0.3.0] - 2026-07-02
### Added — Phase 3: Metadata
- Tag reading via **tinytag** (`core/library.read_tags`): Title / Artist / Album /
  Duration pulled from each file; Title falls back to the file name when untagged.
- New playlist columns: **Title / Artist / Album / Time** (Time and Size sort by
  real numeric value). Search now matches title/artist/album/path.
- Embedded **album art** for the now-playing track shown as a thumbnail in the
  transport bar (`read_album_art`, hidden when a file has no art).
- **Background scanning** (`core/scanner.ScanWorker` on a `QThread`): tag reading
  on slow drives no longer freezes the UI. Tracks stream into the list in batches
  with a live "Scanning… N found" status; Add Folder is disabled during a scan and
  the list is sorted/finalized when done.

### Fixed
- Cancelling an in-flight scan (e.g. starting a new one) could let the old scan's
  queued signals cancel the new scan or mutate the list; cancelled scans are now
  fully detached and stay silent.

## [0.2.3] - 2026-07-02
### Changed
- Scanner now skips files smaller than 10 KB (`MIN_TRACK_SIZE_BYTES`), so empty
  and corrupt junk files never enter the playlist.

## [0.2.2] - 2026-07-02
### Fixed
- Name column text was rendering dark/unreadable on non-playing rows: the
  now-playing highlight reset other rows with an invalid `QColor()` (black).
  Non-playing names now clear the foreground role and inherit the theme's white;
  only the currently playing row is blue + bold.

## [0.2.1] - 2026-07-02
### Added
- Playback error handling: when a file can't be opened (empty/corrupt, e.g. 0-byte
  MP3s), the player now shows a status message and auto-skips to the next track
  instead of stalling silently. A guard stops the run if many files fail in a row
  so a folder of bad files can't loop forever.

## [0.2.0] - 2026-07-02
### Added — Phase 2: Playback
- `core/player.py`: `Player` wrapper over `QMediaPlayer` + `QAudioOutput`
  exposing play/pause/stop/seek/volume and position/duration/ended signals.
- `ui/transport_bar.py`: bottom transport — ◄◄ / ▶❚❚ / ►► buttons, seek slider
  with elapsed/total time, volume slider, now-playing label.
- Double-click a row to play; now-playing row shows a ▶ marker and blue bold name.
- Auto-advance to the next track at end of media; Next/Prev follow the visible
  (sorted/filtered) row order and skip hidden rows.
- `settings.py`: remembers last folder, recursive toggle, and volume; the last
  folder is re-scanned automatically on launch.
- Slider + now-playing styling added to the dark-blue theme.

### Fixed
- Playlist now pins a predictable ascending #-order after populate (Qt was
  applying a descending sort when sorting was re-enabled).

## [0.1.0] - 2026-07-02
### Added — Phase 1: Skeleton
- Project scaffold: `main.py`, `ui/`, `core/` packages, `requirements.txt`.
- Dark-blue theme (`ui/theme.py`) applied app-wide via Qt stylesheet.
- Folder scanner (`core/library.py`): walks a directory with optional recursion,
  collects audio files (MP3, WAV, FLAC, M4A, AAC, OGG) as `Track` records with
  name, size, and format.
- Main window (`ui/main_window.py`):
  - Toolbar: **Add Folder**, **Include subfolders** toggle, live **Search** box.
  - Playlist table: #, Name, Size, Format, Path — with header-click sorting
    (Size sorts by real byte count via `NumericItem`).
  - Duplicate paths are skipped when adding folders.
  - Status bar shows track count / filter matches.
