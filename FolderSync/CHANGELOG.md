# Changelog

## [1.1.1] — 2026-10-08

### Fixed
- The built EXE showed PyInstaller's default floppy-disk icon: the code looked for `app_icon.ico` next to the EXE, but the file was never generated, bundled or embedded.

### Added
- New app icon (`app_icon.ico`, magenta two-way sync loop between folders; made with IconMaker).
- Icon is embedded in the EXE (`FolderSync.spec` `icon=`) for Explorer/shortcuts, bundled as data for the window, and the app sets its own `AppUserModelID` so the taskbar shows it instead of python.exe.
- `FolderSync.spec` is gitignored (`*.spec`); the lines needed are `datas` `('app_icon.ico', '.')` and `icon=[...app_icon.ico]` in `EXE(...)`.

## [1.1.0] — 2026-07-08

### Added
- Optional hash verify (BLAKE2b) for matched-size files to catch content differences
- Reverse Diff mode: find files in Destination missing from Source, with confirm-then-delete
- Reason column in results table
- Named sync profiles (save/load/delete Source/Destination/options)
- Post-sync/delete summary report with CSV export
- Watch mode: auto-sync when the Source folder changes (debounced)

## [1.0.0] — 2026-06-27

### Added
- Initial release
- Source / Destination folder selection with browse dialogs
- Include Subfolders toggle for recursive sync
- Compare phase: fast (filename, filesize) diff with sortable results table
- Sync phase: copy missing files preserving subfolder structure
- Progress bar and live log during sync
- Cancel support mid-operation
- Persistent JSON config (last-used paths, window size)
- Dark theme (PyQt6 + custom QSS)
- PyInstaller spec for windowed EXE build
