# Wallpaper Shuffler Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-10-09

### Changed
- Now a resident system-tray app. The Run key launches `WallpaperShuffler.exe --tray` at
  logon; the tray instance changes the wallpaper immediately and again on every
  workstation unlock (lock screen, Windows Hello, resume-with-lock) via
  `SystemEvents.SessionSwitch`. v1.0.x only changed at logon because a Run key never
  fires on unlock.
- Tray menu: Change Now, Settings..., Exit. Double-click the tray icon for Settings.
- Running the EXE with no arguments opens Settings; if a tray instance is already running
  it shows that instance's window instead of starting a second one (named event).
- Closing the Settings window hides it; Exit in the tray menu quits.
- Existing Run key values from v1.0.x (`--apply`) are rewritten to `--tray` the next time
  Settings opens.
- `--apply` / `--next` remain as one-shot headless modes for scripts.
- No scheduled task is used or created.

### Files
- New `TrayApplication.cs` (ApplicationContext: tray icon, session-switch hook, shared
  ShuffleBag, settings window lifetime). `SettingsForm` now takes the TrayApplication.

## [1.0.2] - 2026-10-09

### Added
- App icon: amber picture-card stack with shuffle arrow on navy (generated with OpenArt
  Nano Banana 2, converted with IconMaker's `convert_to_ico`, 16/32/48/256).
  Wired in three places: `ApplicationIcon` in the csproj (EXE, Explorer, shortcuts),
  embedded resource loaded onto the settings form (title bar), and
  `SetCurrentProcessExplicitAppUserModelID` (taskbar grouping).

## [1.0.1] - 2026-10-09

### Fixed
- Shuffle bag no longer repeats images mid-cycle. The old queue could not tell an
  already-shown file from a new file on disk and re-inserted it every call.
- Center fit mode is now selectable (Fill and Center shared enum value 0).
- Status line shows the real remaining count on launch instead of 0.

### Changed
- State is now a file table: `state.json` holds `{ path: "Unused" | "Used" }` per image.
  Each call syncs the table with disk, picks a random Unused row, marks it Used; when
  no Unused rows remain every row is reset to Unused (cycle restart) and the image
  currently on screen is excluded from the opener.
- Folder and fit mode are saved in `state.json`; the login run (`--apply`) uses them.
  `config.json` removed.
- `state.json` and `error.log` live directly next to the EXE (no subfolder).
- Window title shows the version; status line shows remaining/total and last shown.
- csproj uses `Microsoft.NET.Sdk` (NETSDK1137 warning gone).

### Tests
- 14 tests (was 11): added reset-after-cycle, no back-to-back repeats over 200 calls,
  sync without status change, persistence across instances, folder switch discards table.
- Fixed the file-added test, which only passed because of the repeat bug.

## [1.0.0] - 2026-10-09

### Added
- Initial release of Wallpaper Shuffler
- Shuffle-bag algorithm: cycles through all images before repeating
- Settings window with navy theme (matches VideCoding app palette)
  - Image folder picker
  - Wallpaper fit mode selector (Fill, Fit, Stretch, Center, Tile, Span)
  - "Change Now" button for manual wallpaper changes
  - "Run at Login" checkbox to enable/disable automatic startup
  - Status line showing remaining images in current cycle
- Windows login automation via HKCU Run key (no admin rights required)
- Command-line interface:
  - `--apply` / `--next` for headless operation
  - No arguments to open settings window
- Image format support: PNG, JPG, JPEG, BMP
  - Case-insensitive extension matching
  - Skips unsupported formats (WebP, TXT, etc.)
- Portable configuration: `state.json` stored next to EXE
- Single-instance mutex to prevent concurrent runs during login
- Comprehensive unit test suite (11 tests)
  - Shuffle-bag correctness (no repeats, cycle restarts)
  - Scale tests (100-image cycles)
  - Edge cases (empty folder, missing folder, single image)
  - File management (add/remove files mid-cycle)
  - File type filtering (ignores unsupported formats)
- Error handling and logging
  - Retries with delay when shell not ready at login
  - Graceful handling of missing/deleted files
  - Error logging to `error.log`

### Technical Details
- Platform: .NET 10 (net10.0-windows)
- UI Framework: WinForms
- Dependencies: Newtonsoft.Json for state persistence
- Build: Single-file self-contained executable
- Wallpaper API: P/Invoke SystemParametersInfo
- Registry: HKCU Control Panel\Desktop for fit mode, HKCU Run key for startup
