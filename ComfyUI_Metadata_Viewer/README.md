# ComfyUI Metadata Viewer

*Formerly **VHS Metadata Parser**. Renamed in v1.4.0 once it read more than VHS videos.*

A desktop tool that reads the ComfyUI prompt and workflow stored inside any ComfyUI output file (images, videos, audio) or in a saved `.json` / `.txt` export. You can check a file's seed, prompts, models and sampler settings, and copy its full workflow, without loading it into ComfyUI.

**Current version: 1.4.0**

## Features

- **Reads any ComfyUI output:**
  - **Images:** PNG from `SaveImage` (the `tEXt` / `iTXt` / `zTXt` chunks), WebP from `SaveAnimatedWEBP` (EXIF), JPEG and GIF from custom savers
  - **Videos:** MP4 / MOV / M4V / MKV / WebM / AVI from `VHS_VideoCombine` and other video savers
  - **Audio:** FLAC / MP3 / Opus / OGG / WAV / M4A from `SaveAudio`
  - **Exports:** saved workflow `.json`, and API-format prompts in `.json` or `.txt`
  - **Any other file:** scanned for embedded `prompt` / `workflow` JSON, so unusual savers still work
- **Explorer right-click entry:** **Tools → Add "Open in ComfyUI Metadata Viewer" to Explorer right-click menu**
  - Adds the entry for every file type, per user (no admin rights needed)
  - On Windows 11 it's under **Show more options**, or Shift + right-click
  - If the EXE moves, open it once from its new location and the entry updates to point there
- Drag-and-drop or File > Open (which also takes a file path on the command line)
- **Tabs:**
  - **Media Settings:** width/height, frames, duration, frame rate, format, CRF, audio, input images
    - **File Header** shows the real size (and duration for MP4/MOV) read from the file itself. It's used whenever the workflow only links to a size, e.g. Flux.2 edit with `GetImageSize`.
  - **Prompts:** a Prompt Sections table that splits each prompt into readable parts (shots, dialogue, camera, soundscape, music, JSON keys), plus the raw positive and negative text
  - **Models:** CLIP, VAE, UNET / checkpoint, LoRAs
  - **Sampler:** steps, CFG, sampler, scheduler, **seed**, denoise, model-sampling shift. Handles `KSampler*`, and `SamplerCustomAdvanced` with the seed taken from `RandomNoise`.
  - **Other Settings:** every node input not shown on the other tabs
  - **Workflow:** the full ComfyUI workflow JSON, with copy and save buttons
  - **Raw JSON:** everything found in the file
- **Batch / Search:**
  - Scan a folder (optionally including subfolders) of any of the file types above
  - Filter by file name, LoRA, model, sampler, **seed** or prompt text
  - Diff two files side by side
  - Export the summary to CSV
- Works with WAN 2.x, MiniMax H3 and Flux.2 workflows, including subgraph node IDs such as `68:8`
- Dark blue-green theme; packaged as a standalone Windows EXE

## Requirements

```
Python 3.x
PyQt6
```

No other packages are needed. All file formats are read with the Python standard library.

## Usage

```bash
run.bat                      # or: python comfyui_metadata_viewer.py
run.bat path\to\image.png    # open a file on launch
```

1. Drag any ComfyUI output onto the drop zone, or right-click it in Explorer.
2. Browse the tabs. The seed is on the **Sampler** tab.
3. Use the **Workflow** tab to copy or save the workflow for reuse in ComfyUI.

A file queued through the API (Video Creator, scripts) usually carries only the `prompt` block, not the `workflow`. For those, every tab except Workflow is filled in.

## Build EXE

```bash
pyinstaller ComfyUI_Metadata_Viewer.spec
```

Deploy `dist/ComfyUI_Metadata_Viewer.exe` to `P:\Apps\AICoded\ComfyUI Metadata Viewer\`.

## Recent Changes

Full history in [CHANGELOG.md](CHANGELOG.md).

- **1.4.0:** renamed from VHS Metadata Parser; reads PNG / WebP / JPEG / GIF, more video containers, audio, and any other file; Explorer right-click entry; Seed column in Batch / Search; File Header row for all formats
- **1.3.1:** rebuild release shipping the v1.3.0 fixes (MP4-header dimension fallback, layout fixes, `run.bat`, optional command-line file argument)
- **1.3.0:** MiniMax H3 workflow support, generic link resolution, Prompt Sections table, Other Settings tab
- **1.2.0:** Batch / Search tab with live filter, diff view, CSV export
- **1.1.0:** migrated from PyQt5 to PyQt6, dark blue-green theme
- **1.0.0:** initial release
