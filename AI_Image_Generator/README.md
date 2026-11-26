# AI Image Studio

**Version:** 3.3.2 | **Status:** Active | **Language:** Python

A four-tab PyQt6 desktop application for AI image generation via ComfyUI (local or a RunPod pod the app starts and stops itself). Built mainly for multi-reference images: Scene Composer feeds up to four reference images to Flux.2 Dev for character-consistent scenes.

## Tabs

- **Text to Image**: Text-to-image generation using any ComfyUI `t2i_*.json` workflow. Supports size presets (512×512 through Super UltraWide), steps, seed, output folder, and a batch queue for running multiple prompts unattended.
- **Scene Composer**: Multi-reference-image composition. Drop up to 4 reference images, describe the scene (refer to them as "image 1", "image 2"… in slot order, gaps skipped), and a ComfyUI `edit_*.json` workflow blends them together. Default: **Flux.2 Dev multi-reference** (`edit_flux2_dev_multiref.json`, 28 steps; `_turbo` = Turbo LoRA, 8 steps). Empty slots are cut out of the workflow automatically.
- **Variations**: Img2img — feed any image back in with a strength (denoise) slider and optional prompt using an `i2i_*.json` workflow. Low strength = subtle variation, high = mostly new image.
- **Library**: Scrollable thumbnail grid of all generated images from all output folders. Preview, favorite (★), filename filter + favorites-only filter, prompt recall, A/B compare, send-to-Variations, delete, open folder. Auto-refreshes on tab switch.

## Connection & RunPod

One connection for the whole app (header badge + **⚙ Settings > Server**): Local ComfyUI (`http://127.0.0.1:8188`) or a RunPod pod.

RunPod pod control is copied from the ComfyUI Video Creator (same modules as the Style Randomizer and Chain Automator — no shared code, so pod fixes are ported by copying):

- **Start Pod / Stop Pod** in the header, with the spend readout. Start works down Settings > RunPod's GPU priority + pod order, keeps trying every N minutes when all pods are busy, and plays the alert sound when one is up.
- **Launch chooser**: pods already running when the app opens can be used, stopped, or left alone.
- **Spend limit** per pod run (no new runs past it; the pod stops when the current run ends), **idle stop** N minutes after the last run, **quit prompt** to stop or leave the pod.
- **Model check & sync** (Settings > Models, RunPod volume via S3): before a pod run, every model the workflow names is looked for on the pod volume and locally; missing ones are uploaded first. Pod-only models (e.g. the Flux.2 text encoder) are only downloaded to this PC if you say so.
- The RunPod API key lives in `api_keys.json` next to the EXE (`runpod_api_key`), never in settings.

## Features

- Size presets covering square, portrait, landscape, Full HD, 2K, 4K, and ultrawide resolutions
- Dark purple theme (`#13131f` background, `#6c5ce7` accent)
- ComfyUI workflow JSON integration (auto-patches prompt, size, seed, steps, denoise, LoadImage nodes) — including Flux.2's `Flux2Scheduler` / `EmptyFlux2LatentImage` (sizes snapped to 16 px)
- Picking a workflow sets the Steps slider to that workflow's own step count
- A rejected workflow shows ComfyUI's own node error (missing model, bad input) instead of a bare HTTP 400
- Background generation thread — UI stays responsive during generation
- **Batch queue** (Text to Image): add multiple prompt jobs, run sequentially; failed jobs are skipped and counted, the queue continues
- **Generation history**: every generation records its prompt, workflow, size, steps, and resolved seed to `generation_history.json` (last 500); the Library shows the prompt for any selected image and **Recall Prompt** restores everything to the originating tab
- **Favorites**: star images in the Library (persisted in settings); gold ★ on cards and a favorites-only filter
- **A/B compare**: pick image A, pick image B, view side-by-side with dimensions/size/date captions
- Settings persisted to `settings.json`; API keys persisted to `api_keys.json` (gitignored)

## Tech Stack

- Python 3.10+
- PyQt6
- Pillow (image resizing + encoding for uploads)
- ComfyUI (local server or a RunPod pod)
- boto3 (model sync with the RunPod network volume)

## Files

```
AI_Image_Generator/
├── ai_image_generator.py       — Main application (tabs, workers, main window)
├── config.py                   — settings.json next to the EXE (app_dir), defaults, per-tab → one connection migration
├── runpod_api.py               — RunPod REST/GraphQL client (copied from Video Creator)
├── model_sync.py               — model check & S3 sync with the pod volume (copied)
├── alerts.py                   — alert sound (copied)
├── ui/
│   ├── pod_control.py          — header Start/Stop Pod widget + launch chooser (copied)
│   ├── pod_worker.py           — pod start/stop/list threads (copied)
│   ├── settings_dialog.py      — Settings: Server / RunPod / Models (copied from Style Randomizer)
│   └── styles.py               — purple theme colours + the copied modules' style rules
├── Comfy_Workflows/            — ComfyUI workflow JSON files (API format)
│   ├── t2i_*.json              — Text-to-Image workflows (flux1dev, flux2_dev, flux2_dev_turbo)
│   ├── edit_*.json             — Scene Composer workflows (flux2_dev_multiref[_turbo], qwen_image_edit_2509)
│   └── i2i_*.json              — Variations (img2img) workflows (none yet)
├── dropped_images/             — Drag-and-drop input staging (with archive/ subfolder)
├── upload_temp/                — Upload staging for the ComfyUI API
├── settings.json               — Settings (gitignored)
├── generation_history.json     — Last 500 generations for prompt recall (gitignored)
├── activity.log                — Pod / model-sync progress lines (gitignored)
└── api_keys.json               — RunPod API key (gitignored, never committed)
```

## Workflow File Naming Convention

| Prefix      | Tab             |
|-------------|-----------------|
| `t2i_*.json`  | Text to Image   |
| `edit_*.json` | Scene Composer  |
| `i2i_*.json`  | Variations      |

## Building

Build with the repo `.venv` (it has boto3), using the spec (excludes torch/tf from the shared venv):

```bash
P:\AI\AICoding\.venv\Scripts\python.exe -m PyInstaller --noconfirm "AI Image Studio.spec"
```

Deploy: copy `dist\AI Image Studio.exe` and `Comfy_Workflows\` to `P:\Apps\AICoded\AI Image Studio\`. Never overwrite the `settings.json`, `api_keys.json` or `generation_history.json` already there. EXE is ~130 MB.

## Changelog

### v3.3.2 — 2026-10-18
- **Fix: the model upload/download progress was wrong for any file over 2 GB.** The progress signal carried the byte counts through a 32-bit integer, so an 18.03 GB upload showed "-1911 MB of 855 MB" and a bar stuck near 99%. The counts now arrive intact: real sizes ("9.02 GB of 18.03 GB"), a bar that matches, and a sensible MB/s and time left. The transfer itself was never affected - only the dialog

### v3.3.1 — 2026-10-08
- The window, dialogs and taskbar now use the app icon (previously only the EXE file had it): app-wide `setWindowIcon`, own `AppUserModelID` so Windows stops grouping it under python.exe. The icon is bundled into the EXE and loaded from PyInstaller's unpack folder, so a stale `app_icon.ico` left beside the EXE can no longer show.
- `AI Image Studio.spec` is gitignored (`*.spec`); it needs `datas=qt_datas + [('app_icon.ico', '.')]` and `icon=['app_icon.ico']`.

### v3.3.0 — 2026-10-03
- **RunPod pod control** ported from the ComfyUI Video Creator (via the Style Randomizer copy): header Start/Stop Pod + spend readout, launch chooser, GPU priority / pod order, keep-trying, spend limit, idle stop, quit prompt, alert sound. New modules `runpod_api.py`, `alerts.py`, `ui/pod_control.py`, `ui/pod_worker.py`
- **Model check & sync** with the pod's network volume (`model_sync.py`, Settings > Models) gates every pod run; the T2I queue checks each of its workflows once up front
- **One connection for the app**: the three per-tab Connection boxes are gone; old per-tab settings migrate automatically (Text to Image's choice wins). New **⚙ Settings** dialog (Server / RunPod / Models)
- **Flux.2 Dev workflows**: `edit_flux2_dev_multiref.json` (4 chained ReferenceLatent references) + `_turbo`, `t2i_flux2_dev.json` + `_turbo`, converted from `Flux2_MultiRef_Character.json`. Flux.2 reference images are uploaded unresized (the workflow scales them to 1 MP); output size goes to the latent + scheduler nodes, snapped to 16 px
- **Empty reference slots are pruned** from the workflow (LoadImage chain removed, ReferenceLatent / Qwen image inputs left to pass through) instead of failing on a placeholder file
- **Fix**: reference images went into LoadImage nodes in text order of their ids (`"436"` before `"78"`), so Qwen edit got Image 1 in its second input. Now numeric order
- **Fix**: settings, history and workflows lived next to `__file__`, which in the one-file EXE is the temp extraction folder — they now live next to the EXE (`config.app_dir()`)
- Picking a workflow sets Steps from the file; HTTP 400 shows ComfyUI's node errors; generation timeout 10 → 30 min (cold pod model load); new size presets 832×1248, 1024×1536, 1248×832

### v3.2.0
- Replaced RunPod Serverless (API key + endpoint ID, async job submission/polling, base64 image transfer) with **RunPod (Pod)**: enter a Pod's proxy URL and it's used directly as the ComfyUI HTTP API endpoint, same as local — removed `RunPodWorker`/`RunPodEditorWorker` entirely since `ComfyWorker`/`EditorWorker` now cover both modes via `ConnectionWidget.active_url`
- **Full-size image viewer**: double-click a Library thumbnail to open it at native size (capped to 90% of the screen) in a dialog showing dimensions/file size/modified date; Esc closes
- Library grid/preview split is now a draggable `QSplitter` instead of a fixed-width panel

### v3.1.0 — 2026-07-07
- **Batch queue** (Text to Image): Add to Queue / Run Queue / remove / clear; jobs run sequentially with per-job status; failures are skipped and counted at the end
- **Generation history + prompt recall**: all three generating tabs log prompt/workflow/size/steps/resolved-seed per image to `generation_history.json`; Library shows the prompt and "↩ Recall Prompt" restores settings to the originating tab and switches to it
- **Variations tab** (img2img): new `i2i_*.json` workflow convention; source image slot (drag & drop or sent from Library), optional prompt, strength slider mapped to KSampler denoise (0.05–1.00), size/steps/seed, Local + RunPod support
- **Favorites in Library**: ☆/★ toggle button, gold star on thumbnail cards, "★ Favorites only" filter checkbox; persisted in settings
- **A/B compare in Library**: "⇆ Set A" then "⇆ Compare with A" opens a resizable side-by-side dialog with dimensions/file size/date under each image
- Library now also scans the Variations output folder; added "🔄 Variations" button to send any Library image to the Variations tab
- Random seeds are now resolved before submission so history records the actual seed used

### v3.0.2
- Fix preview panel cut off: lower left scroll area minimum width (370→280) so stretch ratio (1:2) can give preview adequate space
- Lower preview label minimum size (400×400→200×200) so it doesn't resist shrinking
- Lower window minimum size (1200×820→800×600) so Qt layout engine can apply stretch factors correctly at smaller sizes

### v3.0.1
- Fix Connection widget gap: replaced `QStackedWidget` with show/hide widgets so Local mode doesn't reserve RunPod's extra height
- Fix left panel clipping: wrap both tab left columns in `QScrollArea`
- Fix URL field: replaced `QTextEdit` (height-clipping) with `QLineEdit`
- Fix Scene Composer image slots: changed from 4-wide row to 2×2 grid to fit the narrower left panel

### v3.0.0
- Renamed "Image Editor" tab to "Scene Composer"
- Added `ConnectionWidget` per-tab: toggle between Local ComfyUI and RunPod Serverless
- Added `RunPodWorker` (async job submission + polling + base64 image decode)
- Added `RunPodEditorWorker` (embeds reference images as base64 for RunPod upload)
- Added **Library tab**: scrollable 4-column thumbnail grid, preview panel, delete, info
- Added `QLineEdit` stylesheet + scrollbar styling
- Version bump to 3.0.0

### v2.0.0
- Full rewrite; both tabs now ComfyUI API based; FLUX local diffusers removed
- Text to Image tab with workflow picker, size presets, steps, seed
- Image Editor tab with 4 reference image slots, drag & drop, EditorWorker

### v1.x
- Single-tab FLUX local diffusers app (deprecated)

## Future Enhancements

- [x] Generation history with prompt recall (click a Library image to restore its prompt/settings) — v3.1.0
- [x] Batch queue: line up multiple prompts and walk away — v3.1.0
- [x] Favorites/rating in the Library tab — v3.1.0 (favorite toggle; numeric rating not needed)
- [x] Img2img variations tab (feed a Library image back in with strength slider) — v3.1.0
- [x] Side-by-side A/B compare of two generations — v3.1.0
- [x] RunPod pod control + model sync (ported from Video Creator) — v3.3.0
- [ ] An `i2i_*.json` workflow so the Variations tab can run (Flux.2: one reference + denoise, or a Flux.1 img2img)
