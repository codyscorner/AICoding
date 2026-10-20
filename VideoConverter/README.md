# Video Converter

Standalone video format converter. Drop files or browse a folder, pick a format preset, and convert — designed for re-encoding to photo-frame and device-compatible formats.

## Features

- **Drag & drop**: drop individual files or a folder directly onto the window
- **Browse Files**: multi-select file picker for one or more video files
- **Browse Folder**: scans one folder level only (no recursive subfolders) and adds all video files found
- **Three format presets**:
  - AVI — Xvid: widest digital photo frame compatibility
  - MP4 — H.264 Baseline (Baseline/L3.1 + yuv420p): universal device compatibility
  - MOV — H.264: QuickTime / Apple device compatibility
- **Output Folder**: defaults to same folder as source; can be changed per batch
- **Suffix box**: blank = same filename with new extension; filled = `filename_suffix.ext`
- **Auto-collision avoidance**: if output file already exists, appends `_1`, `_2`, etc.
- Per-file status in the table: Pending → Converting… → Done / Error (color coded)
- Background conversion thread — UI stays responsive; Cancel stops mid-batch
- Dark theme consistent with the ComfyUI Chain Automator family

## Supported Input Formats

MP4, AVI, MKV, MOV, WMV, FLV, WebM, M4V, TS, MPG, MPEG

## Requirements

- Python 3.11+
- PyQt6
- FFmpeg on PATH

```
pip install PyQt6 pyinstaller
```

## Usage

```
python main.py
```

## Building the EXE

```
python build_exe.py
```

Output: `dist\VideoConverter.exe`, copied to `P:\Apps\AICoded\Video Converter\`

## Changelog

### v1.1.0
- Per-file progress percent (parses ffmpeg's `Duration:`/`time=` stderr output), shown inline in the Status column
- Custom preset editor: "Custom Preset…" combo entry opens a dialog for codec (H.264/H.265/Xvid/MPEG-4), CRF or explicit bitrate, and width (auto-scaled height); saved presets persist in `video_converter_config.json`
- Trim on convert: optional Start/End fields (`mm:ss`, `hh:mm:ss`, or plain seconds) applied via `-ss`/`-t`
- Recursive folder scan option ("Include subfolders" checkbox) for both Browse Folder and folder drag-and-drop
- Parallel conversions with a worker-count cap (1-8, default 1); conversion moved to a `ThreadPoolExecutor` inside the worker thread, overall progress bar now tracks completed jobs instead of started jobs

### v1.0.0
- Initial release: drag-and-drop + browse-files + browse-folder input, three format presets, suffix control, background conversion, per-file status table

## Future Enhancements

All planned enhancements shipped in v1.1.0.
