# ComfyUI Video Creator

Version: 2.17.0

Single-shot ComfyUI API workflow runner with a dark red theme. Pick an image, a video to extend, or nothing but a prompt (text → video), pick a workflow JSON, press Run, and the finished video lands in a local folder — from a local ComfyUI or a RunPod pod.

This is a **separate app from the ComfyUI Workflow Chain Automator**. It shares no code with it, so changes to one never affect the other.

## Features

- **Image → Video tab** — thumbnail grid of a chosen image folder (sort by name/date; thumbnails cached in `<folder>/thumbnails`), workflow dropdown, prompt editor, Run. **Select several images and Create queues one run per image**, same prompt and settings, in grid order
- **Video → Extend tab** — thumbnail grid of a chosen video folder. **Select several videos and Extend queues one run per video**, same prompt and settings, in grid order. The selected video feeds the workflow as either:
  - its **last frame** (extracted with ffmpeg) into a `LoadImage` node or a folder loader — works with any image-to-video workflow, or
  - the **whole file** into a `LoadVideo` / `VHS_LoadVideo` node (MiniMax H3 reference workflows etc.)

  Auto-detected from the workflow, with a manual override. Optionally the new clip is **appended to the source video** (`<name>_extended_<stamp>.mp4`). With Append ticked the clip is generated at the source video's own frame size, and the workflow about to run is retuned to save in the source's codec (`video/h265-mp4` → `video/h264-mp4`, checked against the server's own option list; the file on disk is untouched), and the stitch normalizes size, fps, SAR, pixel format and audio format for both parts — a clip of a different shape is padded, never stretched, and a silent clip gets matching silence rather than muting the whole file
- **Text → Video tab** — no browser, no source: the run panel and its prompt editor take the whole tab. Pick a **prompt-only workflow** (one with no `LoadImage` / `LoadVideo` / folder-loader node — anything with one is refused here with a reason, since it would run against whatever file name is baked into that node), write the prompt or let the 🪄 AI Rewriter build one from a rough idea, type an **Output name** (there's no source to name the clip after: `rain_walk` → `rain_walk_<workflow>_<stamp>.mp4`, blank → `T2V_…`), **Create Video**. LoRAs, seed/steps/megapixels/length, Turbo, history, the queue and Reuse Settings all work exactly as on the other tabs
- **Finished sources are hidden, per workflow** — on the Image and Extend grids a file is hidden once the workflow selected on that tab has made a video from it that is still in the Library (other workflows' videos don't count, so the same image can be tried on workflow 2; switching workflow re-filters at once; point the Library at an empty folder and everything reappears), so the picker shows what is left to do. Tick **Show all** to see everything again (not remembered between launches). A source whose video was deleted comes back. The status line reads `181 images · 57 done hidden · 3 selected`
- **Extend tab: keep track of one set of extensions at a time** — below Sort / Show all the Extend grid has **📚 Send to Library** (moves the selected, finished videos into the Library, inside the active workflow's folder, so they appear in the Library tab and count as that workflow's results), **Hide** / **Unhide**, and **Hide short clips**. A source is hidden automatically as soon as an extension of it finishes (remembered in `extend_hidden.json` next to the config; **Show all** brings it back). With *Append* ticked an extension saves a short clip and a complete video; **Hide short clips** (on by default) drops the short clip once its complete video is beside it, and never hides a clip that has no complete video
- **Delete from the grid** — every thumbnail browser can delete: the 🗑 button in the folder row, right-click → Delete, or the Del key. Files (and their cached thumbnails) go to the **Recycle Bin**, so a bad generation is one click away from gone without opening Explorer. A file the built-in player is showing is closed first, then deleted
- **Workflow dropdown** — every API-format `.json` under the Workflows folder (subfolders included). **Type any part of a name to filter it** — matching runs anywhere in the relative path, not just from the start, so `makeout` narrows 77 workflows to 2. Batch-style workflows using `LoadImageListFromDir //Inspire` also work: the single image is staged into a fresh run folder and the loader pointed at it
- **⧉ Clone workflow** — copy the selected workflow to a new name (and any subfolder) and switch to the copy, so you can experiment without touching a workflow that already works. Optionally seeds the clone with the prompts, LoRAs and settings currently on screen, and optionally copies its prompt history
- **✚ New blank workflow** (Image → Video and Text → Video tabs) — copies the template picked for that tab in Settings → Prompts under a new name, with every prompt (positive and negative) emptied, every LoRA switched off (stack slots set to None, single loaders to strength 0; the MiniMax Turbo LoRA is left to the Turbo toggle) and no history, then switches to it. The template file is never changed
- **Prompt editor** built from the workflow (CLIPTextEncode positive/negative, MiniMax H3 prompt, PrimitiveStringMultiline); edits apply per run, or "Save to workflow" writes them into the JSON. Each prompt has an **⤢ Expand** button for a large separate editor window, and the Prompts / Options split is draggable
- **LoRA picker** — one row per LoRA node in the workflow (`LoraLoaderModelOnly`, rgthree `Lora Loader Stack`, `MiniMaxH3TurboLoRA`…): editable dropdown of LoRA files from your LoRAs folder (or fetched from the connected server with ⇣ Server) plus strength spinner(s). A "Next run →" line always shows the LoRAs, seed and length about to be used. The list status shows both counts at once ("N from folder · M from server") instead of one replacing the other
- **Every dropdown in the app** only changes by opening it (click, or Enter/F4) — scrolling the mouse wheel over one, or pressing Up/Down while it merely has focus, no longer silently changes its value out from under you
- **Prompt history with settings** — every run appends prompts + seed + length + LoRAs/strengths + mode + source to the workflow's `<name>.prompt_history.json` (shared with the Chain Automator) and attaches the result file name when done. 📜 History searches entries and reloads the prompt alone or prompt + settings
- **Seed** random-per-run or fixed; **Steps** applied to every sampler node (WAN hi/lo splits rescaled proportionally); **Megapixels** applied to every `megapixels` input (`ImageScaleToTotalPixels` etc.); **Length / Duration** control when the workflow exposes one
- Extend-tab thumbnails show each video's **last frame**, the extension's starting point
- **Library tab** — finished videos (Output folder by default; **each workflow saves into its own subfolder** and a *Workflow* selector — *All*, *Unsorted* or one workflow, optionally following the workflow on the active tab — picks which to list; **🗂 Sort into workflow folders…** moves older loose videos into theirs after showing the plan): sort, multi-select, Play (playlist), Delete, **Archive** (move to a separate folder for later, cleans up its cached thumbnail), Open Folder, **Send to Extend**, **🔁 Reuse Settings** (when a video didn't turn out: switches to the tab it was made on and reloads its workflow/prompt/LoRAs/seed/steps so you can tweak and retry — for Image → Video the starting image is pulled from the video's own first frame via ffmpeg rather than the original upload, which is rarely still on disk, and shown as a small preview; for Video → Extend the recorded source video is reselected, or the Video folder is rescanned if it's moved; for Text → Video there's nothing to select, the prompt and settings just come back. The retry itself isn't logged to history, since the video already carries the prompt it ran with), filename search + Year/Month/Day date-created filter, and a *Produced by* pane with the prompt/LoRAs/seed/length behind the selected video (from the prompt history), plus **how long it took to generate** — the whole run, the ComfyUI render part alone, and the sampler's step count with its average seconds per step — for every video made from v2.2.0 on
- **Run queue you can actually see** — all three run tabs share one queue (ComfyUI runs a single prompt at a time), so pressing Create/Extend while something's running lines the new run up behind it. **📋 View Queue** opens a live list of what's running and what's waiting — **the frame each run starts from** (the source image, or the source video's last frame) plus tab, workflow, source file and a wrapped three-line prompt per row (settings and the full prompt on hover) — and lets you reorder rows, drop one, or clear the lot. Queueing a run that repeats one already running or waiting (same workflow, source, prompt, LoRAs, seed, steps, megapixels and length) asks first instead of quietly spending the render time twice
- **Local or RunPod** server with separate URLs, "Test connection", and automatic download of the result to the Output folder
- **Model check & sync (RunPod)** — before a RunPod run, every model file the workflow names (checkpoints, diffusion models, VAEs, text encoders, CLIP vision, upscalers, LoRAs) is looked for in the local models folder and on the pod volume via RunPod's S3 API; files the pod lacks are uploaded from here (files only on the pod bring up a *Model missing locally* box: the pod run can start without them, download only if you also want to run locally; Settings → Models can make that automatic) with sizes verified, and the run starts by itself when done. Cancel aborts the file in flight. Settings → Models holds the S3 details (Import from S3 Browser config) and the local models root (blank = parent of the LoRAs folder). Module: `model_sync.py`
- **RunPod pod control** — start and stop your pods from the app instead of the RunPod console. On launch it offers to bring a pod up, tries your pods **in priority order — by GPU model first, so every RTX 6000 is tried before any A100** — and uses the first that actually works, then writes the proxy URL into the config itself. Only existing pods are started; nothing is ever created or terminated. Crucially it rejects a pod that resumes **with no GPU attached** — RunPod pins a stopped pod to one physical machine and, if that machine's card has been rented out meanwhile, starts it GPU-less (HTTP 200, RUNNING, ComfyUI answering, billing, everything on CPU) — stopping it and moving to the next candidate. If every pod is busy you're offered a switch to Local. The header shows **live spend and time remaining** (`2h 17m  |  $4.80 / $10.00  |  4h 41m left`) with an optional **session limit** that warns at 80%, then blocks new runs, lets the current one finish and stops the pod. An optional **idle stop** stops the pod a set time after the queue finishes (DONE) if no new run starts — for overnight queues that end early. On quit you're asked about whichever pod is connected — Yes stops it, No leaves it running (and billing) so the next launch can reconnect to it. The pod the app started is recorded next to the EXE so a crash is caught and cleaned up on the next launch. If any pod is already running when the app launches — one you left up on purpose, or one another app such as the Chain Automator is using — a chooser lists them with live GPU, uptime and spend, and you pick: use it, start another (the running ones are left out of the search; if nothing else can be started you're offered the running one instead), stop it, or skip. A pod started outside the app is never stopped automatically — the spend limit only blocks new runs on it; it is stopped only if you answer Yes on the quit prompt
- **Keep trying until a pod frees up** — because the pods are pinned to specific machines, all of them being busy is normal. Rather than giving up, the app can re-sweep the list every few minutes for a set window (default: every 10 minutes for 2 hours) and **play a sound of your choosing** the moment one comes up, raising the window since the pod starts billing then. The same sound plays if the window expires with nothing found, so you get an answer either way without watching the screen
- Live step progress over the ComfyUI websocket (polling fallback), Cancel that interrupts the server, built-in video player, run log

- **↻ Lists / F5** — rescans every list from disk and the server (workflow dropdowns on all tabs, LoRAs from folder and server, Image/Video folders, Library) so a file renamed while the app runs shows under its new name; a selected LoRA the list no longer has is flagged red until you pick its new name
- **Prompt history you curate** — every run is recorded with the prompt, LoRAs, seed, steps and length it used, in `<workflow>.prompt_history.json` beside the workflow (the same sidecar the Chain Automator writes). The 📜 History window has four tabs — **★ Favorites / Recent / All / Archived** — with a multi-select (Ctrl/Shift-click, Ctrl+A) then **Archive (N)** to move many entries to Archived at once, **Unarchive** there to bring them back; Delete works on the selection too. **Nothing is ever removed from the file** unless you press Delete. **Favorites live in their own file**, `<workflow>.prompt_favorites.json`: starring copies the prompt + settings there, so deleting or archiving history never loses a favorite. Favorites are per template (the workflow JSON), with an *All templates* view across the lot. Row previews skip the boilerplate preamble a template's runs all share, so the preview shows what actually differs between runs

## Requirements

- Python 3.11+
- PyQt6, requests, websocket-client, Pillow
- ffmpeg — configured in Settings, or an `ffmpeg.exe` next to the EXE, or on PATH

```
pip install PyQt6 requests websocket-client pillow pyinstaller
```

## Usage

**From source:** `run.bat` (or `python main.py`)

**EXE:** `P:\Apps\AICoded\ComfyUI Video Creator\ComfyUI_Video_Creator.exe`

1. ⚙ Settings (tabbed: **Server / Folders / RunPod / Prompts**) → on *Server* choose Local/RunPod and the URL and press *Test connection*; on *Folders* set Images, Videos, Workflows and Output.
   - On *RunPod*, the pod list fills itself in when the tab opens. Put your preferred **card model** at the top of *GPU priority* — the pod list below is the order the chain will actually use, so you can read it straight off.
2. Image → Video: click an image, pick a workflow, adjust the prompt/seed/length, **Create Video**.
3. Video → Extend: click a video, pick a workflow, choose the input mode (Auto is fine), tick *Append the new clip*, **Extend Video**.
4. Text → Video: pick a prompt-only workflow (no image or video loader node), write the prompt — or a rough idea plus 🪄 AI Rewriter — type an output name, **Create Video**.
5. Results appear in the Results list — double-click to play, or Open Folder.
6. Library: review everything in the Output folder, play a selection back-to-back, delete misses, send a clip back to Extend, or Reuse Settings to retry it on the tab it was made on.

## Configuration

`video_creator_config.json` sits next to the EXE (next to `main.py` from source) and is written by the Settings dialog.

| Key | Description |
|-----|-------------|
| `mode` | `local` or `runpod` |
| `comfyui_url` / `runpod_url` | Server URL for each mode |
| `image_dir` / `video_dir` | Folders shown on the two tabs |
| `workflow_dir` | Folder scanned (recursively) for workflow `.json` files |
| `output_dir` | Where finished videos are downloaded |
| `loras_dir` | ComfyUI `models/loras` folder that fills the LoRA dropdowns |
| `library_dir` | Folder shown on the Library tab (blank = the Output folder) |
| `image_blank_template` / `text_blank_template` | Workflow (relative to `workflow_dir`) that ✚ New copies on the Image → Video / Text → Video tab (blank = button shows where to set it) |
| `text_output_name` | Output name last typed on the Text → Video tab (blank = `T2V`) |
| `output_per_workflow` | Save each workflow's videos in `<Output>/<workflow path>/` (default on) |
| `library_follow` | Library's Workflow selector follows the workflow on the active tab (default on) |
| `archive_dir` | Where the Library's Archive button moves videos to |
| `staging_dir_local` | Local folder for staging an image for folder-loader workflows (blank = app `temp`) |
| `runpod_input_dir` | Absolute path of ComfyUI's `input` folder on the pod (folder-loader workflows) |
| `ffmpeg_path` | Optional explicit ffmpeg path |
| `video_input_mode` | `auto`, `last_frame` or `upload_video` |
| `extend_stitch` | Append the new clip to the source video |
| `runpod_gpu_order` | GPU models in priority order, e.g. RTX 6000 before A100. Outranks `runpod_pod_order`; a model not listed sorts last (blank = no card preference) |
| `runpod_pod_order` | Pod IDs in priority order *within* a GPU model (blank = whatever the account lists) |
| `runpod_auto_prompt` | Offer to start a pod when the app launches |
| `runpod_auto_stop_on_exit` | On quit, ask whether to stop the connected pod (any pod in use, including one adopted from the launch chooser); off = never ask |
| `runpod_spend_limit` | USD per pod run before new runs are blocked (0 = off) |
| `runpod_idle_stop_min` | Stop the connected pod this many minutes after the queue finishes (DONE) with nothing new started; 10-minute steps, 0 = off |
| `runpod_retry_interval_min` | Minutes between sweeps when every pod is busy |
| `runpod_retry_window_min` | Give up looking after this long |
| `alert_sound_path` | Sound played when a pod is found, when giving up, and when a queue of 2+ runs finishes |
| `alert_sound_enabled` | Play the alert sound |
| `s3_delete_outputs_after_download` | RunPod mode: delete each result from the pod volume (via S3) right after it is downloaded and its size matches (default off) |
| `s3_output_prefix` | ComfyUI's output folder inside the bucket (default `runpod-slim/ComfyUI/output/`) |

The RunPod **API key** is not in this file — it lives in `api_keys.json` next to the app (key `runpod_api_key`), or in the `RUNPOD_API_KEY` environment variable, which takes precedence. `video_creator_config.json` is preserved and copied on every deploy, so a secret in it would travel with the build.

Workflows must be **API exports** (Workflow > Export (API) in ComfyUI); the normal UI save format is rejected with a message.

## Output naming

`<source stem>_<workflow>_<YYYYMMDD_HHMMSS>.mp4` — `<workflow>` is the workflow's subfolder name when it lives in one, otherwise the file stem. A clip made on the Video → Extend tab carries `_EXT` just before the timestamp (`<stem>_<workflow>_EXT_<stamp>.mp4`) so extensions stand out in the output folder. Stitched extensions are `<source stem>_extended_<stamp>.mp4`. When the source is a video the app first strips the workflow label and timestamp an earlier run appended, so a chain of extensions keeps one stable base name instead of growing by ~50 characters a pass; names this app didn't write (a camera-style `IMG_20260101_120000.mp4`) are left alone. A Text → Video clip has no source, so it takes the Output name typed on the tab (`<name>_<workflow>_<stamp>.mp4`), or `T2V_<workflow>_<stamp>.mp4` when that's blank. Every name is capped to keep the full path under 250 characters.

The file goes in `<Output>/<workflow path without .json>/` (e.g. `Series 1/MiniMax_Makeout_On_Bed_Ext1/`) unless *Save each workflow's videos in its own folder* is turned off in Settings → Folders.

## Building the EXE

```
build.bat
```

Builds with the repo `.venv`, deploys `ComfyUI_Video_Creator.exe`, `app_icon.ico` and `ffmpeg.exe` to `P:\Apps\AICoded\ComfyUI Video Creator\` and refreshes the Start Menu shortcuts. Bump `VERSION` in `main.py` (and this README + CHANGELOG) before every build.

## Project layout

| File | Purpose |
|------|---------|
| `main.py` | Entry point, version, icon/config discovery |
| `config.py` | Portable config next to the EXE |
| `workflow_tools.py` | Load/validate API workflows, detect input/prompt/seed/length/output nodes, patch them |
| `comfy_client.py` | Upload, queue, websocket/poll wait, history, download, interrupt |
| `run_worker.py` | Background thread for one run: feed source → queue → wait → download → optional stitch |
| `remote_cleanup.py` | Delete a downloaded result from the RunPod volume over S3 (size-verified, opt-in) |
| `media_tools.py` | ffmpeg discovery, last frame, thumbnails, probe, concat |
| `workflow_folders.py` | Per-workflow Library folders + the one-time plan/move that sorts loose videos into them (no Qt) |
| `processed.py` | Which sources one workflow has already turned into a video that is still in the Library |
| `file_ops.py` | Recycle-Bin delete (shell `SHFileOperation`) + thumbnail-cache cleanup |
| `ui/` | Dark red theme, thumbnail browsers, run panel, queue view, clone dialog, settings dialog, video player, main window |

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
