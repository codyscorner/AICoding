# Changelog — Desktop Video Browser

## [1.3.3] — 2026-10-17

### Added
- Right-click a folder in the tree for "Open in Explorer" (opens that folder in a Windows Explorer window, e.g. to copy its files to a thumb drive) and "Copy Folder Path". Acts on the folder under the cursor without changing the current selection or reloading the file list.

## [1.3.2] — 2026-10-17

### Fixed
- "Open Folder..." now opens its dialog in the folder highlighted in the tree view. It previously passed no start directory, so Windows fell back to the process's working directory — in the built EXE, the EXE's own folder. Falls back to the currently loaded folder if nothing is highlighted.

## [1.3.1] — 2026-09-07

### Added
- "Delete" added to the file list's right-click context menu. Prompts with a confirmation dialog ("This action cannot be undone") before removing the file from disk. If the file being deleted is the one currently loaded in the player, the player releases it first so Windows doesn't block the delete with a file-lock error.

## [1.3.0] — 2026-09-07

### Added
- Sort dropdown above the file list: Name (A-Z/Z-A), Date Modified (Newest/Oldest), Size (Largest/Smallest). Selected sort mode persists across restarts.
- Click the folder path label at the bottom of the file list to copy the current folder path to the clipboard (brief "Copied!" confirmation); right-click it for a "Copy Folder Path" menu item too.
- Right-click a file in the list for a context menu: Copy Full Path, Copy File Name, Show in Explorer (selects the file in a Windows Explorer window).

## [1.2.0] — 2026-09-05

### Added
- Explorer-style folder tree navigation pane (`ui/folder_tree_panel.py`) on the left side of the window, backed by `QFileSystemModel`/`QTreeView`. Shows every drive, expands/collapses like Windows Explorer, and supports native arrow-key navigation between sibling and parent folders.
- Folder tree stays in sync with the file list and the "Open Folder..." button/drag-and-drop: selecting a folder in the tree loads it into the file list, and opening a folder any other way expands and highlights it in the tree. The last-opened folder is restored and highlighted in the tree on startup.

### Changed
- Flattened project layout: moved app.py, version.py, settings.json, core/, ui/, assets/, and the PyInstaller spec out of the nested `video_browser/` subfolder into the project root, matching the layout of every other project in the repo. Removed the now-empty `video_browser/` folder.
- Fixed icon-path lookups in app.py and ui/main_window.py that assumed the old nesting depth.
- Window default size increased to 1450×750 to fit the new three-pane layout (tree / file list / player).

### Fixed
- Settings persistence, the window icon, and the dark theme stylesheet were all resolved via `__file__`, which points into PyInstaller's temporary extraction folder in the built EXE rather than the EXE's real folder — so `settings.json` was never actually saved anywhere permanent, and the icon/stylesheet loads were silently failing. Added `core/paths.py` with `get_app_dir()` (EXE's own folder, for persistent settings) and `resource_path()` (bundled read-only resources), and bundled `app_icon.ico`/`ui/dark_theme.qss` as PyInstaller data files so they're actually included in the build.
- The folder tree could silently overwrite the remembered last-opened folder on startup: `QFileSystemModel`/`QTreeView` sometimes set their own "current" row (e.g. the drive the app happens to be running from) once the drive list finishes populating, and the tree was treating that the same as a real user click. It now only reports a folder change on an actual mouse click or arrow-key press, not on Qt's own internal selection changes.
- The EXE's own icon (`assets/icons/app.ico`) was a 19-byte placeholder stub, not a real icon — PyInstaller's icon conversion failed on it. Replaced with a real copy of the working `app_icon.ico`.
- Added the standard ML-package exclude list to the PyInstaller build (spec and `build_exe.bat`) so packages from the shared venv (torch, pandas, etc.) never leak into this app's EXE.

## [1.1.0] — 2026-06-21

### Added
- Seek/progress slider with scrub support (click or drag to jump to any position)
- Volume slider in the toolbar (0–100%)
- Keyboard shortcuts: Left/Right arrows to seek ±10s, M to mute/unmute
- More supported formats: .webm, .wmv, .flv, .m4v, .ts
- Full dark theme (replaced placeholder QSS with complete widget coverage)
- .gitignore to exclude build/dist artifacts and __pycache__

---

## [1.0.0] — 2026-06-10

### Added
- Initial release
- Split-pane layout: file list (left) + embedded video player (right)
- Play / Pause / Stop / Fullscreen controls
- Drag-and-drop folder loading
- Settings persistence (last folder, window geometry)
- Dark gray theme
- PyInstaller EXE build script
