# IMDB Photo Downloader

Downloads all gallery photos from any IMDB title or actor/actress page into organized named subfolders.

## Features

- Supports both title pages (`/title/tt...`) and actor/actress pages (`/name/nm...`)
- Batch queue: paste multiple URLs (one per line), downloads each in turn into its own named subfolder
- Auto-names the download subfolder from the title/person name
- Files named `<Title>_0001.jpg` to avoid conflicts when copying across folders
- Scrolls gallery to load all lazy-loaded images (bypasses the ~72 image limit)
- Optional full-resolution mode: visits each photo's mediaviewer page for the largest available image (slower)
- Skips already-downloaded files on re-run
- Automatic retry with exponential backoff on network failure for each image download
- Writes `manifest.csv` and `manifest.json` per subfolder listing every image's filename, source URL, caption, and status
- Persistent settings saved between sessions: root folder, full-resolution default, window size
- Clickable folder link opens Explorer when download completes
- Search IMDB by movie/show/actor name (no URL needed) — uses IMDB's public autocomplete API, results flagged with 📷 when IMDB has poster art for them; double-click a result to add its URL to the queue

## Requirements

```
pip install PyQt6 playwright requests beautifulsoup4
python -m playwright install chromium
```

## Usage

**Run from source:**
```
python imdb_downloader.py
```

**Or use the batch launcher:**
```
IMDB_Photo_Downloader.bat
```

1. Set your **Root Folder** — all downloads go into named subfolders here
2. Paste any IMDB URL (title or actor/actress)
3. Hit **Download**

## Examples

```
https://www.imdb.com/title/tt0111161/        ← movie
https://www.imdb.com/title/tt2543796/        ← TV show
https://www.imdb.com/name/nm1760388/         ← actor/actress
```

## Output Structure

```
Root Folder/
  Girl Meets World (TV Series 2014-2017)/
    Girl_Meets_World__TV_Series_2014_2017__0001.jpg
    Girl_Meets_World__TV_Series_2014_2017__0002.jpg
    ...
  America Olivo/
    America_Olivo_0001.jpg
    ...
```

## Changelog

### v1.2.8
- The window, dialogs and taskbar now use the app icon (previously only the EXE file had it): app-wide `setWindowIcon` plus its own `AppUserModelID`, so Windows stops grouping it under python.exe. The icon is bundled into the EXE and loaded from PyInstaller's unpack folder.
- `IMDB_Photo_Downloader.spec` is gitignored (`*.spec`); it needs `datas=[('app_icon.ico', '.')]` and the existing `icon=` line.

### v1.2.7
- Widened the per-image download pacing from a sub-second gap to a "someone is actually looking at the photo" delay: never under 2s, usually 2-6s, occasionally lingering up to 10s (`random.triangular(2.0, 10.0, 4.0)`). Only applies between actual downloads — skipped/cached files aren't delayed. This only affects per-image pacing; scroll/page-navigation jitter from v1.2.6 is unchanged.

### v1.2.6
- Replaced fixed, identical delays (between scrolls, gallery pages, mediaviewer visits, and image downloads) with randomized jitter. Uniform timing on every single request is itself a bot fingerprint on top of the headless-Chromium signals already masked in v1.2.4 — randomized pacing looks less mechanical and is gentler on IMDB's servers. Applied to both `imdb_downloader.py` and `imdb_photos.py`. Skipped (already-downloaded) files no longer get an artificial delay since they don't hit the network.

### v1.2.5
- Fixed settings (root folder, full-res default, window size) not persisting in the packaged EXE — `SETTINGS_FILE` was anchored to `Path(__file__).parent`, which resolves inside PyInstaller's ephemeral `_MEI` extraction folder when frozen instead of next to the persistent EXE. Now anchors to `sys.executable`'s directory when frozen, matching the pattern used elsewhere in this codebase.

### v1.2.4
- Fixed gallery scrapes returning 0 images on some titles: IMDB now serves an AWS WAF CAPTCHA ("Human Verification") page to headless browsers instead of the gallery. Masking `navigator.webdriver`, adding `--disable-blink-features=AutomationControlled`, and using a realistic viewport avoids the challenge so the real gallery HTML loads.
- Fixed a crash in the standalone `imdb_photos.py` CLI script where `extract_title_id()`'s `(id, type)` tuple was passed straight into `scrape_media_gallery()` instead of being unpacked.

### v1.2.3
- Renamed the "Clear Results" button to "Clear List" per feedback.

### v1.2.2
- Moved the "Clear Results" button down to the full-resolution checkbox row and widened it; it now only clears the results list, leaving the search text box untouched.

### v1.2.1
- Added a small "Clear" button next to the title search box to dismiss search results without running a new search.

### v1.2.0
- Added a "Find" search box: look up a movie/show/actor by name via IMDB's public autocomplete endpoint instead of pasting a URL. Results show year, type, and a 📷 indicator when IMDB has poster art for that entry (a quick signal, not a guarantee, that its media gallery has photos too). Double-click a result to append its URL to the queue.
- Settings now also persist the full-resolution checkbox default and window size across sessions, in addition to the root folder.

### v1.1.1
- Fixed "Executable doesn't exist" Playwright launch error in the packaged EXE — the frozen app was looking for Chromium inside the ephemeral PyInstaller `_MEI...` temp extraction folder instead of the persistent browser cache. Now pins `PLAYWRIGHT_BROWSERS_PATH` to `%LOCALAPPDATA%\ms-playwright` before Playwright is imported, so a one-time `playwright install chromium` on the machine works across every run of the EXE.

### v1.1.0
- Batch queue: URL field is now a multi-line box, one URL per line, downloaded sequentially
- Full-resolution option (checkbox): follows each thumbnail's mediaviewer link and pulls the largest available image via `og:image`, falling back to the gallery-derived URL if unavailable
- `manifest.csv` / `manifest.json` written to each output subfolder: index, filename, source URL, caption (from image alt text), and status (downloaded/skipped/failed)
- Downloads now retry up to 3 times with exponential backoff before being marked failed
- Internal: scraping now returns per-image caption + mediaviewer link, not just a flat URL list

### v1.0.0
- Initial release
- Title and actor/actress URL support
- Lazy-load scrolling to get all images past the 72-image limit
- Persistent root folder setting
- Named subfolders with conflict-safe filenames
- Clickable Explorer link on completion

## Future Enhancements

- Ideas not yet built: concurrent/parallel downloads across the URL queue, an image-count preview before committing to a full-res run, filtering search results by type (movie/TV/person only).
