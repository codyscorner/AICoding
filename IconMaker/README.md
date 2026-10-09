# IconMaker

A PyQt6 desktop tool that batch-generates AI app icons for projects in this repository using a local ComfyUI instance, then converts them to `.ico` format and copies them into each project folder as `app_icon.ico`.

**Current version: 1.1.2**

## Workflow

1. Select apps to process from a checkbox list, and set Candidates / Padding / Corner Radius options
2. The GUI submits text-to-image requests to ComfyUI using a workflow JSON template (one request per candidate, per app)
3. If more than one candidate was generated, a picker dialog shows thumbnails to choose from before continuing
4. Saves the chosen PNG to `IconMaker/output/<AppName>.png`
5. Converts it to a `.ico` file (16, 32, 48, 256 px), applying padding/rounding if configured
6. Copies the `.ico` to the target project folder as `app_icon.ico`
7. Appends the prompt and seed used to `IconMaker/output/prompt_history.json`

## Requirements

```
Python 3.x
PyQt6
Pillow
ComfyUI running locally (default: http://127.0.0.1:8000)
```

```bash
pip install PyQt6 Pillow
```

## Usage

```bash
python main.py
```

Configure the ComfyUI URL and output folder in the GUI's config row. Generated icons are saved to `output/` and distributed to each project folder automatically.

`make_icons.py` also remains usable as a headless script — edit its `NEW_APPS` set to control which apps run without the GUI.

## Files

```
IconMaker/
├── main.py                     — PyQt6 GUI wrapper
├── make_icons.py               — Headless logic: APPS list, ComfyUI helpers
├── qwen_T2Image_2512_API.json  — ComfyUI workflow template
└── output/
    ├── <AppName>.png / .ico    — generated icons
    └── prompt_history.json     — prompt/seed/timestamp log per app
```

## Notes

- No EXE build — this is a dev tool that requires a local ComfyUI instance
- Edit the top of `make_icons.py` to change `COMFY_URL`, `COMFY_OUTPUT`, `ICO_SIZES`, or the `APPS` list (app entries and their prompts)

## Recent Changes

### v1.1.2
- IconMaker now has its own icon (lime anvil + forged tile) and sets it for the window/taskbar, with its own `AppUserModelID`
- `make_icons.py`: `COMFY_URL` can be overridden with the `COMFY_URL` environment variable (the local ComfyUI currently listens on 8188, the script defaults to 8000); loaders are pointed at the installed Qwen-Image 2.1 files because the workflow JSON still names the 2512 ones
- New `APPS` entries: TodoList, S3Browser, FolderSync, IconMaker

### v1.1.1
- `APPS` entry for the renamed ComfyUI Metadata Viewer (was VHS Metadata Parser) now points at the `ComfyUI_Metadata_Viewer` folder

### v1.1.0
- Prompt history: every generated icon's prompt/seed/timestamp is appended per-app to `output/prompt_history.json`; a "View History" button prints an app's past runs to the log
- Candidates per app (1-4): generates that many images per app with different seeds; a picker dialog lets you choose the best before it's converted and copied, and extra candidates are deleted after picking
- Padding % / Corner Radius % options: shrinks the source onto a transparent canvas and/or applies a rounded-rectangle alpha mask before saving the `.ico`
- "Scan for Missing Icons" button lists project folders that aren't in `APPS` and don't yet have an `app_icon.ico`

### v1.0.0
- PyQt6 GUI wrapper around `make_icons.py`
- App selector with checkboxes, Select All / Deselect All
- Config row for ComfyUI URL and output folder
- Generate button, progress label, append-only log
- QThread worker keeps the UI responsive during generation
- Dark theme: background `#0d0d1a`, accent `#5e4bdb`
