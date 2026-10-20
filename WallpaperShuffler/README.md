# Wallpaper Shuffler

A lightweight Windows system-tray app that sets a new wallpaper every time you log in or unlock your PC, cycling through a folder in random order without repeating until all images have been shown.

## Features

- **Random rotation**: Displays images in shuffled order
- **No-repeat guarantee**: Cycles through all images before showing any image twice
- **Login and unlock**: Starts in the tray at Windows login via Run key (no admin, no scheduled task) and changes the wallpaper at launch and on every unlock
- **Manual control**: "Change Now" in the tray menu or the settings window
- **Settings window**: Configure folder, fit mode, and startup behavior
- **Portable**: Single EXE with config stored next to it
- **Scalable**: Handles 1 image to 1000+ images efficiently
- **Format support**: PNG, JPG, JPEG, BMP (WebP not supported by Windows Wallpaper API)

## Usage

### Open Settings
Run `WallpaperShuffler.exe` with no arguments. If the tray instance is already running, its settings window comes to the front; otherwise a tray instance starts and opens settings.

```
WallpaperShuffler.exe
```

### Start in Tray (used by the Run key)
Starts in the system tray, changes the wallpaper immediately, then changes it again on every workstation unlock.

```
WallpaperShuffler.exe --tray
```

### Apply Next Wallpaper (Headless, for scripts)
Runs silently, picks the next image, sets wallpaper, and exits.

```
WallpaperShuffler.exe --apply
```

Or

```
WallpaperShuffler.exe --next
```

### Settings Window
- **Image Folder**: Select any folder containing images
- **Fit Mode**: Choose how the wallpaper fills your screen (Fill, Fit, Stretch, Center, Tile, Span)
- **Change Now**: Immediately apply the next wallpaper
- **Start in tray at login**: Adds/removes the HKCU Run key (`--tray`)
- Closing the window hides it to the tray; use Exit in the tray menu to quit

## Installation

1. Download `WallpaperShuffler.exe` and place it in `P:\Apps\VibeCoded\Wallpaper Shuffler\`
2. Run the executable
3. Select your images folder (default: `D:\Pictures\Wallpaper\Seasonal\Halloween 26`)
4. Check "Run at Login" to enable automatic startup

## Configuration

Settings are stored in `state.json` next to the EXE:

```json
{
  "folder": "D:\\Pictures\\Wallpaper\\Seasonal\\Halloween 26",
  "queue": ["path1.jpg", "path2.png", ...],
  "lastShown": "path.jpg"
}
```

The `queue` tracks remaining images in the current cycle to prevent repeats.

## Building

```bash
dotnet build WallpaperShuffler.sln
```

### Publish Single-File EXE

```bash
cd src\WallpaperShuffler
dotnet publish -c Release --self-contained
```

## Testing

Run unit tests:

```bash
dotnet test WallpaperShuffler.sln
```

Tests verify (14 tests):
- 6 consecutive calls return each of 6 images exactly once
- Cycle restart shows every image again and never opens with the one on screen
- No back-to-back repeat across 200 calls on a 4-image folder
- Single-image folders always return that image
- 100-image cycles complete without repeats
- A file added mid-cycle is shown before the cycle restarts; deleted files are skipped
- Sync populates the table without changing status; state survives a new process
- Switching folder discards the old table
- Empty folders, missing folders and unsupported types are handled gracefully

## Recent Changes

### v1.1.0 (2026-10-09)
- Resident tray app: wallpaper changes at login and on every unlock (SessionSwitch), tray menu, single instance brings settings to front

### v1.0.2 (2026-10-09)
- App icon (amber picture cards + shuffle arrow on navy) wired for EXE, title bar and taskbar

### v1.0.1 (2026-10-09)
- Fixed mid-cycle repeats: state is now a per-file status table (Unused/Used)
- Folder and fit mode are saved and used by the login run
- Center fit mode fixed; status line correct on launch; version in window title

### v1.0.0 (2026-10-09)
- Initial release
- Shuffle-bag algorithm (no repeats until all shown)
- Settings window with navy theme
- Login automation via Run key
- Manual "Change Now" and "--next" features
- Comprehensive unit tests
- Supports PNG, JPG, JPEG, BMP formats
- Scales to 1000+ images

## How the Shuffle Bag Works

Think of `files` in `state.json` as a two-column table: path and status.

1. **Sync**: Delete rows whose file is gone; insert new files on disk as `Unused`
2. **Query**: Select all `Unused` rows
3. **Reset**: If that query is empty, set every row back to `Unused` (cycle restart) and drop the image currently on screen from the pool
4. **Pick**: Choose one row at random, mark it `Used`, record it as `lastShown`, set the wallpaper

Because shown files are marked rather than removed, a new file is never confused with an already-shown one.

## Architecture

- **ShuffleBag.cs**: Status-table shuffle logic with state persistence (folder, fit mode, file table)
- **AppPaths.cs**: Version constant, portable paths (EXE folder, state.json, error.log), icon loader and taskbar AppUserModelID
- **app_icon.ico**: app icon, embedded in the EXE
- **WallpaperApi.cs**: P/Invoke to Windows API for setting wallpaper, registry access for fit mode
- **TrayApplication.cs**: ApplicationContext owning the tray icon, SessionSwitch hook, shared ShuffleBag and the settings window
- **RunKeyManager.cs**: Manages the HKCU Run-key entry (`--tray`) for login start
- **SettingsForm.cs**: WinForms UI with navy theme (Color.FromArgb 20, 30, 48)
- **Program.cs**: Entry point, launch modes (--tray / none / --apply), single-instance mutex + show-settings event
