# ComfyUI Workflow Chain Automator

Version: 3.12.0

Automates a chain of ComfyUI segments (up to 10), stitching the outputs into a single final video. Supports both local ComfyUI and RunPod deployments.

## Features

- Chains multiple ComfyUI workflow segments automatically
- Segment count driven by your workflow config — no hardcoded limits (max 10)
- **Batch mode**: run N images simultaneously — one model load per segment, N outputs (uses `LoadImageListFromDir //Inspire`); every segment's batch workflow is validated when the chain is selected (and at startup) — a missing or unwired list loader disables Start Batch / Auto Run and shows exactly which file/node to fix, instead of a late "expected N videos, got 1"
- **LoRA check & sync**: every LoRA a chain names is verified in the local LoRA folder (Settings > Folders) and, in RunPod mode, on the pod's volume via RunPod's S3 API (Settings > RunPod Volume). Missing-locally blocks Start with the file/segment named; missing-on-pod is uploaded from the local folder on Start (or via the ⇅ LoRAs button) before the batch runs. Module: `lora_sync.py`
- Dual workflow sets: `workflow_segment_XX_batch.json` in chain subfolder
- Split-pane UI: image browser (with sort) on the left, controls on the right
- Background image loading — UI appears instantly, thumbnails load progressively
- Persistent image thumbnail cache (`thumbnails` subfolder in the image folder, auto-synced) — large folders load in seconds; switching chain templates re-filters in place with no rescan
- 200px letterboxed thumbnails with black padding (no cropping)
- Starting image sort: Name A→Z / Z→A, Newest First, Oldest First
- Segment progress dots, per-segment timing, and live log
- **Live step progress** via ComfyUI websocket — progress bar advances with each sampler step and shows an ETA once a segment has completed (falls back to HTTP polling if the websocket is unavailable)
- Cancel interrupts the job on the ComfyUI server (no orphaned RunPod generations)
- Daily log file (`ComfyUI_Chain_Log_mm_dd_yyyy.txt`) written to final video folder — run separator, per-image list, segment times, zip info
- RunPod support — batch images uploaded via ComfyUI upload API, videos downloaded automatically
- **RunPod pod control** (v3.11.0, ported from ComfyUI Video Creator): start/stop your own pods from the app — launch prompt or chooser for pods already running, GPU-model-first priority order, Keep Trying when every pod is busy, header spend/balance readout, per-run spend limit, idle stop after the last batch, quit prompt. API key in `api_keys.json` next to the EXE (`{"runpod_api_key": "..."}`); the pod chain is logged to `runpod_pod.log`. Modules: `runpod_api.py`, `alerts.py`, `ui/pod_control.py`, `ui/pod_worker.py`
- FFmpeg local last-frame extraction (`-sseof -0.1`) for smooth segment transitions
- Final video stitched with FFmpeg and archived as a zip
- Built-in video player with playlist — plays all batch results back-to-back after completion
- Alert sound (optional, Settings > Prompts & Sound) — plays when a batch or Auto Run finishes and for RunPod pod events
- Library tab with video browser, sort options, multi-select, **Play Selected** playlist, and delete
- **Settings button in Library**: re-embeds each segment's ComfyUI prompt graph into the final stitched video (ffmpeg concat normally strips it) and shows prompts/sampler/model settings per segment for a single selected video
- Every batch zip includes a `prompts.txt` — plain-text summary of every segment's prompts/sampler/video settings, readable in Notepad without opening any file individually
- **Auto Run mode**: processes an entire folder of images automatically, N at a time, with no pop-ups between batches; configurable batch size; graceful **Stop After Batch** button
- **MiniMax H3 workflow support**: handles ComfyUI's native `SaveVideo` output node and `BasicScheduler`-driven samplers; segments with generated audio are stitched with their audio tracks (video-only WAN chains unchanged)
- Single-segment chains skip ffmpeg entirely — the raw downloaded video is copied to the final name (no pointless re-encode)
- Mixed segments are normalized (resolution/SAR/fps/pixel format) before concat, preventing warp artifacts when a chain mixes workflow templates with different output settings
- **Prompt history** per workflow JSON (`<name>.prompt_history.json`) with searchable reload in the Generate tab and Segment Editor
- Bundled `ffmpeg.exe` ships next to the EXE; the app resolves ffmpeg as configured path → app-local copy → system PATH, so a moved/deleted ComfyUI install can't break stitching or thumbnails
- Library videos whose thumbnails can't be generated show a placeholder tile instead of being hidden

## Requirements

- Python 3.11+
- PyQt6
- requests
- websocket-client (live step progress; app falls back to polling without it)
- FFmpeg — configured in Settings, or an `ffmpeg.exe` next to the EXE, or on PATH (checked in that order)

Install dependencies:
```
pip install PyQt6 requests websocket-client pyinstaller
```

## Usage

**Run from source:**
```
python main.py
```

**Standalone EXE** (built with PyInstaller):
```
dist\ComfyUI_Chain_Automator.exe
```

The EXE looks for `main_config.json` in the same folder as the executable.

## Configuration

Edit `main_config.json` or use the ⚙ Settings button in the app.

| Key | Description |
|-----|-------------|
| `comfyui_url` | Local ComfyUI server URL |
| `runpod_url` | RunPod proxy URL |
| `mode` | `local` or `runpod` |
| `input_dir` | Folder containing starting images |
| `workflow_dir` | Folder containing workflow JSON files |
| `workflows` | Array of segment definitions (see below) |
| `final_video_dir` | ROOT output folder for stitched videos — the active chain's name is appended as a subfolder automatically |
| `zip_output_dir` | Output folder for zip archives |
| `ffmpeg_path` | Path to ffmpeg executable |
| `batch_dir_local` | Local folder for staging batch images (local mode) |
| `batch_dir_runpod` | RunPod path for batch output reference |
| `runpod_input_dir` | Absolute path to ComfyUI's input folder on RunPod |
| `runpod_gpu_order` / `runpod_pod_order` | Pod start preference: GPU models best first, then pod ids within a model (a preference, never a whitelist — every pod is still tried) |
| `runpod_spend_limit` / `runpod_idle_stop_min` | Per-run spend limit in USD (0 = off) and idle-stop minutes after the last batch (0 = off) |
| `runpod_retry_interval_min` / `runpod_retry_window_min` | Keep Trying sweep interval and give-up window |
| `runpod_auto_prompt` / `runpod_auto_stop_on_exit` | Ask to start a pod on launch; ask to stop the connected pod on quit |
| `alert_sound_path` / `alert_sound_enabled` | The one alert sound (batch done, Auto Run done, pod found, gave up) |
| `s3_delete_outputs_after_download` / `s3_output_prefix` | RunPod mode: delete each segment video from the pod volume (via S3) right after it is downloaded and its size matches (default off), and ComfyUI's output folder inside the bucket (default `runpod-slim/ComfyUI/output/`) |

The RunPod **API key** is not in this file: put `{"runpod_api_key": "..."}` in `api_keys.json` next to the EXE (or set `RUNPOD_API_KEY`). The pod this app started is remembered in `runpod_session.json`, and the pod chain is logged to `runpod_pod.log`, both next to the EXE.

### Workflow segment definition

```json
{
  "segment": 1,
  "json_file": "workflow_segment_01.json",
  "input_node_id": "97",
  "input_type": "image"
}
```

- `input_type`: `image` (segment 1) or `video` (segments 2+)
- `input_node_id`: The ComfyUI node ID that receives the input

## Building the EXE

```
python build_exe.py
```

Output: `dist\ComfyUI_Chain_Automator.exe`

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.
