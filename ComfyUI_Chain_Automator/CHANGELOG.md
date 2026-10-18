# Changelog — ComfyUI Workflow Chain Automator

### v3.12.0
- **Delete segment videos from the pod volume once they are downloaded** (new `remote_cleanup.py`, same module as ComfyUI Video Creator v2.15.0). ComfyUI never removes its finished videos from `<ComfyUI>/output` on the network volume, and the volume is billed per GB, so every batch left its segment clips behind. New checkbox in **Settings → RunPod Volume (S3)**: *Delete each segment video from the pod volume after it is downloaded* (**off by default**) plus *Output Prefix* (default `runpod-slim/ComfyUI/output/`)
- Safety rules: deleted only if the object is on the volume, the local copy is not empty, and **the local size equals the volume's size**; otherwise the pod copy is kept and the log says why. Only real `output` files, `..` paths refused, and the empty `Merge/<run>` folder is removed after its last file (pruned bottom-up, only when a listing shows it empty). RunPod mode only; failures are logged (`Deleted … from the pod volume` / `Pod cleanup: kept …`) and never fail the batch. Both download paths (history outputs and the "already exists" fallback) are covered

### v3.11.4
- Fix: in a multi-image batch the segments could swap between videos (video A's segment 2 attached to video B and vice versa). Outputs are paired back to images by position, but the Inspire `LoadImageListFromDir` node in the batch workflows was set to `sort_method: None`, which returns raw directory-listing order — arbitrary on the pod's Linux filesystem — so on a segment the pod listed `002_...` before `001_...` and every output after it was matched to the wrong image. The batch run now forces the loader to `Alphabetical (ASC)` (staged files are zero-padded `001_`, `002_`, ...), whatever the workflow JSON says. Not specific to MiniMax; WAN chains could hit it too

### v3.11.3
- **The video player loads the whole clip into memory before playing it**, so the first play no longer skips and pauses. Streaming an MP4 straight off disk makes the decoder seek between the index and the audio/video chunks; on a hard drive or a just-written file that stutters until the OS has cached it. The player now reads the file sequentially on a background thread (shows "Loading…"), then plays from RAM, and reads the next clip in a playlist while the current one plays so the changeover is smooth too. Files over 1 GB or unreadable ones fall back to streaming. Playing from memory also means the player no longer holds the video file open

### v3.11.2
- The app now always starts on top. Qt's `raise_()`/`activateWindow()` are silently ignored by Windows' foreground lock when the launch came from a shortcut/Stream Deck, so the window opened behind others. Startup now uses the same Alt-tap + `SetForegroundWindow` helper as ComfyUI Video Creator, re-applied at 0 / 200 / 800 ms so the startup pod prompt can't leave it behind

### v3.11.1
- Fix: stitching MiniMax H3 segments (video + audio) failed with "Media type mismatch between the 'Parsed_format' filter output pad 0 (video) and the 'Parsed_concat' filter input pad 1 (audio)". Two causes, both in `_stitch`:
  - ffmpeg's concat filter needs its inputs interleaved per segment (`[v0][a0][v1][a1]`); the stitch passed every video pad followed by every audio pad (Video Creator's `concat_videos` already did it right). Silent WAN chains were unaffected
  - Segment size/fps normalization was silently skipped: it relied on `ffprobe`, which isn't shipped next to the EXE (only `ffmpeg.exe` is), so differently-sized segments (e.g. 832x640 then 896x704) reached concat unscaled. It now falls back to reading size/fps from `ffmpeg -i`
- Stitch quality, matching Video Creator: segments with a different aspect are fitted inside the first segment's frame and padded with black instead of stretched, dimensions are forced even, and every segment's audio is resampled to one common 48 kHz stereo format before concat

### v3.11.0
- **RunPod pod control, ported from ComfyUI Video Creator (its v1.7.0 → v2.12.0 pod work, copied not shared).** The app now talks to RunPod's control plane itself (REST v2 via `requests`, no new dependency): on launch it offers to start a pod, tries your pods **GPU model first, then pod order**, and uses the first one that actually comes up, writing the proxy URL into `main_config.json` and switching to RunPod mode by itself. Only existing pods are started — nothing is created or terminated. New modules `runpod_api.py`, `alerts.py`, `ui/pod_worker.py`, `ui/pod_control.py`
  - **Header readout + Start/Stop Pod button** between the title and ⚙: uptime, spend so far, account balance, with a coloured ● for the spend state (green / amber at 80% of the limit / red at the limit) and the idle-stop countdown when it is armed
  - **Launch chooser when pods are already running** (yours from last time, or one the Video Creator / console started): Use selected, Start another, Stop selected, Skip — a pod this app didn't start is adopted but never auto-stopped
  - **Keep Trying** when every pod is busy (every 10 min for 2 h by default), with the alert sound when a pod is found or the window expires; the window raises itself when a retry succeeds because the pod is billing from then on
  - **Spend limit** per pod run: warns at 80%, blocks new batches at 100%, lets the running batch finish, then stops a pod the app started itself. **Idle stop**: a countdown that starts when a batch (or Auto Run) ends and nothing else starts, so an overnight run that finishes early does not bill for hours; a new batch cancels it
  - **Quit prompt** for any connected pod — Yes stops it then quits, No leaves it running (recorded, so the next launch says "you left X running" rather than claiming a crash), Cancel stays
  - All the hard-won rules survive the port: the zero-GPU resume trap (RUNNING + `gpu.count ≥ 1` + non-empty `runtime.gpus` or it is stopped and the next pod tried), 60 s grace for a RUNNING pod whose runtime block hasn't reported yet, 30 s grace before an EXITED reading is believed, only 401/403/429 abort the chain (a 400 on the action endpoint is capacity, a 404 only skips that pod), saved order is a preference never a whitelist, pod log in `runpod_pod.log` next to the EXE
  - **API key** lives in `api_keys.json` next to the EXE (`{"runpod_api_key": "..."}`), gitignored repo-wide, or `RUNPOD_API_KEY` in the environment — never in `main_config.json`, which is copied around on deploy. Workflows still go to the pod with no key (the ComfyUI proxy is unauthenticated); the key is only for start/stop/list
- **Settings is now tabbed** — Server (+ Batch Processing) / Folders (+ FFmpeg) / RunPod (pod control: account balance, GPU priority list, pod order list with ↻, spend limit, idle stop, keep-trying interval + window, ask-on-launch, stop-on-exit, Test API key; the pod list fills itself in on open, on a thread) / RunPod Volume (the S3 LoRA group, unchanged) / Prompts & Sound. The two-column layout of v3.10.1 had no room for the two pod lists; the dialog is 1120×735, well inside 1080p
- **One alert sound.** The Completion Sound group is now **Alert Sound** and the same file plays when a batch finishes, when Auto Run ends (it used to finish silently), when a pod is found after Keep Trying, and when the app gives up looking. An existing `completion_sound_path` / `completion_sound_enabled` is migrated into `alert_sound_path` / `alert_sound_enabled` on first load and the old keys dropped. Test button added
- When a pod comes up (or goes away) the Generate tab's mode badge refreshes and the pod-side LoRA check re-runs against the new pod, so the "missing on pod" list is right before the first batch
- `_generation_running` counts a LoRA upload that will auto-start a batch as busy, so neither the spend-limit stop nor the idle stop can fire in the middle of one

### v3.10.5
- The end-of-batch playback of fresh results now also closes itself after the last video, so every player in the app auto-closes

### v3.10.4
- Library: the video player closes itself when the last selected video finishes (Play Selected playlist or a double-clicked single video) instead of sitting on the final frame until dismissed. The end-of-batch playback of fresh results is unchanged and still stays open

### v3.10.3
- Build fix: `build_exe.py` / `build.bat` now switch to the repo `.venv` Python automatically (and refuse to build if boto3 still can't be imported). A hand-run build with the system Python had produced an EXE without boto3, so the deployed app showed "boto3 is not installed in the Python running this app" for the pod LoRA check even though it was the EXE

### v3.10.2
- ⇅ LoRAs button no longer clips its text — it gets compact padding instead of the global 10px/11pt button padding that needs ~40px in the 30px chain row
- Pod LoRA check reports "boto3 is not installed in the Python running this app" (instead of a raw ModuleNotFoundError) when the app is run from source with a Python that lacks boto3; `run.bat` now launches with the repo `.venv` (which has boto3) when it exists, falling back to `python`

### v3.10.1
- Settings dialog re-laid out in two equal columns (1400 px wide, ~660 px tall) so it fits a 1080p screen — the single-column form had grown past the bottom of the display and hid the OK/Cancel buttons. Left: ComfyUI Server, Folders, Batch Processing, FFmpeg. Right: RunPod Volume (S3), AI Prompt Writer, Completion Sound. 1080p is the minimum supported screen size

### v3.10.0
- LoRA check on chain select / startup / ↻: every `lora_name` / `lora_NN` a chain's batch workflows reference is looked up in the local LoRA folder (Settings > Folders > LoRAs — points at the portable ComfyUI install you actually run). A LoRA missing locally blocks Start Batch and the message names the LoRA, the segment file, the folder searched, and the two fixes (drop the file in, or pick another LoRA in the segment editor). Capitalization mismatches are warned about because the Linux pod is case-sensitive
- RunPod mode: the pod's `models/loras` folder is listed through RunPod's S3-compatible API in the background (new Settings group "RunPod Volume (S3)": AWS profile, endpoint, region, bucket, LoRA prefix, with "Import from S3 Browser config" and "Test connection"). LoRAs the pod lacks are shown under the Chain selector with their total size; Start Batch asks to upload them from the local folder first and starts the batch automatically once the pod confirms every file. New ⇅ LoRAs button uploads on demand. Uploads retry with backoff, survive RunPod's slow server-side multipart merge, and verify the landed size. Cancel stops the upload after the current file
- If S3 isn't configured (or unreachable) in RunPod mode the pod check degrades to a warning rather than blocking; the whole LoRA check can be turned off in Settings
- New module `lora_sync.py`; boto3 is now a build dependency (build with the repo `.venv`)

### v3.9.5
- Chain validation in the UI: as soon as a chain is picked from the Chain dropdown (and at startup for the chain that comes up pre-selected, and after ↻ / Settings), every `workflow_segment_*_batch.json` in that folder is checked. Problems are shown in a red status line under the selector and in a scrollable dialog that names the file, the offending node id, what it is fixed to / what it feeds, and the exact fix (add or connect the `Load Image List From Dir (Inspire)` node, remove the plain `Load Image`, Export (API) over the file). Start Batch and Auto Run stay disabled until the chain validates, and Start re-checks the files right before launching in case they changed
- Batch pre-flight check (worker safety net): before uploading or queuing anything, the worker loads every batch segment and verifies the batch workflow can actually fan out. A missing `LoadImageListFromDir //Inspire` node, or one whose output no other node consumes (e.g. the video node is still fed from a plain `LoadImage`), previously made ComfyUI run the graph once and the run died late with a misleading "expected N output videos, ComfyUI returned 1 … One or more images failed on the server". Both cases now stop before segment 1 even starts, with a clear error naming the workflow file and telling you to wire the list loader's output into the image-scale / first-frame input and re-export the API JSON
- Batch log now warns when a batch workflow still contains a plain `LoadImage` node, since the batch never patches it and anything it feeds gets the same fixed image for every item

### v3.9.4
- Fix: Library showed an empty grid for a folder full of videos when the configured ffmpeg no longer existed (it lived inside the since-deleted ComfyUI venv) — thumbnail generation failed silently and the loader skipped every video without a thumbnail. Videos with no thumbnail now show a flat placeholder tile instead of being hidden
- ffmpeg path is now resolved with fallbacks everywhere (Library thumbnails, stitching, frame extraction, conversion): configured path if it exists → `ffmpeg.exe` next to the app → system PATH. An `ffmpeg.exe` is now deployed alongside the EXE so the app no longer depends on ComfyUI's venv copy

### v3.9.3
- Library: browsing for the Video Folder and picking the active chain's own folder (instead of its parent root) made the library look in an empty doubled `<chain>/<chain>` path — the picker now detects this and steps up to the parent automatically, with a dialog explaining the adjustment

### v3.9.2
- Fix: batch crashed with `[Errno 22] Invalid argument` while building a zip archive when a source image (or other archived file) carried a corrupted/out-of-range file timestamp — Python's zipfile chokes converting such an mtime on Windows. Archive writes now fall back to a manually built zip entry stamped with the current time instead of failing the whole batch

### v3.9.1
- Library: deleting a video now un-marks its source image as processed in that chain's registry, so it reappears in the Chain tab's image list to redo — a deleted video is treated as a bad generation, not a finished one
- Stitch: segments are now normalized (scale/setsar/fps/pixel format, matched to the first segment) before ffmpeg's concat filter — a chain mixing segments with different resolution/fps/SAR previously produced a rippling "underwater" warp in the stitched output even though each segment played back fine on its own
- Stitch: single-segment chains no longer go through ffmpeg at all — the raw downloaded video is copied straight to the final filename, skipping a pointless re-encode (and the artifacts/crashes it could introduce)
- Safety: Image folder can no longer be pointed at the app's own `thumbnails` cache subfolder (checked both in the folder browser and at batch start) — those are small downscaled previews, and sending them to ComfyUI for generation produced blurry/distorted output once upscaled

### v3.9.0
- Segment Editor: prompt/negative-prompt text boxes were fixed at a small 9pt font with no way to enlarge them. Added a "Text Size" spinbox (7-24pt) next to the dialog title that live-resizes both prompt editors and persists the chosen size to config (`segment_editor_font_size`) so it's remembered next time Quick Edit is opened

### v3.8.9
- **Prompt history**: every workflow JSON now gets a sibling `<name>.prompt_history.json` file recording saved positive/negative prompts with a timestamp
- Generate tab: new "💾 Save to History" and "📜 History" buttons next to the prompt fields — Save appends the current prompt for the selected workflow, History opens a searchable list of past prompts with a live preview and an "Use" button that loads the picked entry straight back into the prompt fields
- Segment Editor: new "📜 History" button alongside Save — clicking Save now also appends the segment's current prompt to its history file; History opens the same searchable dialog to reload / delete past entries for that segment's workflow
- New `ui/prompt_history.py` — shared `append_history()`/`load_history()` helpers and the `PromptHistoryDialog` widget used by both tabs

### v3.8.8
- Fixed the app sometimes launching behind other windows instead of on top — `main()` now calls `raise_()`/`activateWindow()` right after `show()`, plus a second pass 200ms later once the event loop and the window's first paint have settled, since Windows' foreground lock can still leave a just-shown window behind others painted after it

### v3.8.7
- Fixed the v3.8.6 phase-tick fix still hitting a false 100% ("Step 44/44") once every post-sampler phase had merely *started* — the "Saving video..." stage alone can take one to three minutes (more with a larger image batch), so counting it done the instant it began still froze the bar at 100% for that whole stretch. Phase ticks now fire on the *next* transition instead — entering phase N+1 (or the prompt finishing) is what marks phase N complete — so the bar holds at e.g. 43/44 through the entire save and only reaches 44/44 when the file is actually finished

### v3.8.6
- Fixed the step bar reading a false "100% / Step 30/30" while MiniMax H3 was still decoding audio/video and saving — sampler progress hits 100% well before the file is actually written, and nothing updated the bar during that stretch. The segment's expected step total (`segment_plan`) now folds in one unit per post-sampler stage (VAE decode video, VAE decode audio, encode, save) detected in the workflow, and each stage ticks the bar forward as it starts (new `phase_progress` signal) — so e.g. "Step 30/30" becomes "Step 30/34" the moment sampling finishes, climbing to 34/34 only once the file is actually done

### v3.8.5
- Added log feedback for the post-sampling stretch on MiniMax H3 (VAE video decode, VAE audio decode, video encode, save) — the websocket goes quiet between the last sampler step and the finished file with nothing but a generic "Running... (Xm)" line, which reads as a hang; each of those stages now logs its own status line as ComfyUI enters it
- Fixed the segment/step progress bars being wrong on MiniMax H3 batches — `_sampler_steps()` (used to compute each segment's expected total step count) only recognized nodes with "sampler" in their class_type and a `steps` input, but H3's `SamplerCustomAdvanced`/`KSamplerSelect` pair carries no `steps` field of its own; the count lives on the upstream `BasicScheduler` node instead. With no plan, the segment bar fell back to mirroring the raw single-pass step fraction (so a 3-image batch showed the *current image's* pass progress as if it were the whole segment's, e.g. stuck bouncing between the wrong percentages instead of advancing across all 3). `BasicScheduler` is now treated as a step source too, so H3 segments get the same accurate whole-segment plan WAN already had

### v3.8.4
- Fixed the final stitched video having no audio on MiniMax H3 chains — `_stitch()` hardcoded `-an` (strip audio) into every ffmpeg concat, which was harmless for WAN's video-only segments but was silently dropping H3's native synced audio track too. It now probes each segment for an audio stream first and, when every segment has one, concats `[v]`+`[a]` pairs and encodes with AAC instead of discarding it; silent (WAN) chains are unaffected

### v3.8.3
- Segment Editor now exposes MiniMax H3's clip length as a **Duration (seconds)** control (1-15s) — H3 doesn't take a raw frame count like WAN; it drives length off a `PrimitiveFloat` node titled "Float (duration)" that feeds a math expression, so that node's `value` is now editable directly instead of only being reachable by hand-editing the JSON

### v3.8.2
- Fixed the Segment Editor showing no prompt box at all for MiniMax H3 chain segments — it only recognized `CLIPTextEncode` nodes, but H3 nodes (`MiniMaxH3ImageToVideo` and other mode variants) pack the whole structured prompt into a single `prompt` field instead; it's now matched by class_type prefix and rendered as one "Prompt" box (H3 has no separate negative) instead of the WAN-style Positive/Negative pair
- `metadata_parser.py`'s prompt extraction (Library "Settings" viewer, `prompts.txt` in batch zips) picks up the same H3 `prompt` field so those views aren't blank for H3-generated videos either
- Fixed batch runs failing with "No output videos in history" on MiniMax H3 chains — output-node discovery only recognized `VHS_VideoCombine`, but H3 workflows use ComfyUI's native `SaveVideo` node, whose result is reported under ComfyUI's `images` history key (not `videos`/`gifs`). Batch output collection and the per-segment `filename_prefix` patch now also recognize `SaveVideo`

### v3.8.0
- **New "Prompt Writer" tab**: type a rough idea and get back a properly structured video-generation prompt via the Anthropic Claude API
- Pick a target model — **WAN 2.2** (plain descriptive prompt) or **MiniMax H3** (structured `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music` format, with a mode selector for T2VA/I2VA/FL2VA/L2VA/Ref2VA)
- H3 system prompts are built from bundled reference guides (`resources/h3_base_guide.txt`, `resources/h3_ref_guide.txt`) so the structure matches MiniMax's own documented prompt spec
- New `prompt_llm_worker.py` calls the Anthropic Messages API on a background thread (no new dependency — reuses `requests`)
- "Send to Generate Tab" pushes the generated prompt straight into the Generate tab's Positive prompt field and switches views
- New Settings → "AI Prompt Writer" field for your own Anthropic API key (`anthropic_api_key` in config, masked input); the tab disables itself with an inline hint until a key is set

### v3.7.4
- **Library "Settings" button**: select a single video and view the prompt, sampler, video, and model settings used to generate it, one tab per chain segment
- **`prompts.txt` in every batch zip**: each per-image zip archive now includes a plain-text summary of every segment's prompts/sampler/video settings, so they can be checked in Notepad without opening any file individually
- Fixed a gap where the final stitched video carried no generation metadata at all — ffmpeg's concat re-encode strips the ComfyUI metadata VHS_VideoCombine embeds in each segment clip; `_stitch()` now extracts every segment's prompt graph before the source clips are discarded, re-embeds them into the final video via an ffmpeg ffmetadata file (avoids the command-line length limit a multi-segment JSON blob could hit as a raw `-metadata` argument), and hands them off to `_zip_segments()` for the text summary
- New `metadata_parser.py` — shared byte-scan extraction (same technique as the standalone VHS_Metadata_Parser tool), a read-only `SegmentMetadata` view for pulling prompts/sampler/video/model settings out of a segment's prompt graph (used by the Settings dialog), and `build_prompts_text()` for the zip's plain-text summary
- Only applies to videos stitched from now on — videos created before this update have no embedded metadata to show

### v3.7.3
- **Exact per-segment step totals read from the workflow JSON**: before queueing each segment the worker counts the sampler nodes and their *executed* steps (KSamplerAdvanced honors `start_at_step`/`end_at_step`, so WAN 2.2's hi/lo pair with steps=4 counts as 2+2) and multiplies by the images in the batch — new `segment_plan` signal carries (passes, total steps)
- Step bar now fills once across the whole segment showing cumulative progress (`Step 5/16` for 4 images × 4 steps) instead of refilling per sampler pass; segment bar and ETA use the same exact fraction, accurate from segment 1 (no more learning from the first segment)
- Workflows with no readable sampler nodes fall back to the previous behavior (per-pass step bar, pass count learned from the first completed segment)

### v3.7.2
- **Per-chain processed registry**: each completed batch records its images in `thumbnails/processed_chains.json` inside the image folder, keyed by chain folder name — so the app remembers what each chain has processed even after the finished videos are moved out of the chain's output folder
- Filtering hides an image if it has a video in the active chain's output folder **or** appears in that chain's registry; other chains are unaffected, so the same images stay available to process with every other workflow
- 'Show all' still reveals everything, so a registry-hidden image can always be re-run deliberately
- Registry snapshot is taken at batch start (image folder, chain, selection), so switching chains while a batch runs records against the right chain

### v3.7.1
- **Separate step progress bar** below the segment bar: fills with the current sampler step (step 1/2 → 50%, step 2/2 → 100%) and resets when a new sampler pass starts, so the within-step motion has its own bar
- **Segment bar no longer bounces backwards**: each sampler pass in a segment restarts ComfyUI's raw step counter, which used to yank the segment bar back mid-segment; the bar now counts passes (learned from the first completed segment) and only ever moves forward
- ETA projection uses the same forward-only in-segment fraction, so the time-left estimate no longer oscillates within a segment

### v3.7.0
- **Image thumbnails are now cached on disk** in a `thumbnails` subfolder inside the image folder (same pattern as the Library's video thumbnails); each load does a quick sync — generates thumbs for new/changed images (mtime compare), deletes thumbs whose source image is gone — so a 1000-image folder loads in seconds instead of re-decoding every picture
- **Switching chain folders no longer rescans the image folder** — the grid keeps its loaded thumbnails and just shows/hides images to match the new template (hidden = already has a video for that chain); switching templates back and forth is instant
- 'Show all' and post-batch refresh use the same in-place show/hide instead of reloading; processed images are hidden (not removed), so switching templates brings them back without a rescan
- Auto Run selects its next batch from visible images only
- Changing the image folder itself still reloads the grid (new folder, new thumbnails); each folder keeps its own `thumbnails` cache

### v3.6.1
- **Stitched filenames now carry a batch timestamp** (`photo_20260709_141530.mp4`, one shared stamp per batch run) — re-running a same-named source image after cleaning out a folder can no longer collide with or be mistaken for an earlier batch's video when moving files elsewhere; the zip archive inherits the timestamped name too
- The "hide already-processed images" filter and post-batch grid removal strip the timestamp when matching videos back to source images, so filtering behaves exactly as before

### v3.6.0
- **Live step progress**: the worker now listens on ComfyUI's websocket (`/ws?clientId=...`) and the progress bar advances with every sampler step instead of jumping once per segment; the label shows `Segment k/n — step 12/30`
- **ETA**: once at least one segment has completed this session, the label projects time remaining for the whole chain (`~7m 20s left`), using per-segment wall times from earlier batches where available
- Websocket is best-effort: if it can't connect or drops mid-run, the worker logs it and falls back to the previous HTTP polling loop; quiet stretches (model load) are covered by a history heartbeat so a missed finish can't hang the run
- New dependency: `websocket-client` (optional — polling fallback works without it)
- Build: PyInstaller spec now excludes torch/tensorflow/etc. from the shared venv (smaller EXE); `build_exe.py` no longer overwrites the live `main_config.json` next to the deployed EXE — it only seeds it on first deploy

### v3.5.1
- Cancel now actually stops the job on the ComfyUI server: removes the pending prompt from the queue and POSTs `/interrupt` — previously the prompt kept running (and kept billing on RunPod) after the UI said cancelled
- Fix: cancelling mid-poll no longer tries to download outputs of the half-finished prompt (confusing error instead of "Cancelled")
- Fix: a missing output video no longer silently truncates the batch — every image after the gap would have been stitched to the wrong chain of videos; the run now fails loudly naming the segment
- Fix: Auto Run next-batch handoff moved from `all_done` to the worker's `finished` signal — previously the new worker replaced the still-running old QThread (timing-dependent crash risk)
- Removed dead code: single-mode `worker.py` (unused since batch-only v2.7.0), `CompletionDialog`, `_on_stitch_done`, `_find_local_batch_outputs`
- Daily log no longer recreates the output folder on every log line
- Changelog moved out of PROJECT_SUMMARY.md into this file


### v3.5.0
- **Per-template output subfolders**: the "Final Video Folder" in Settings is now a root folder; the app automatically creates a subfolder named after the active chain template (e.g. `Videos/WAN_Chain_1/`) and writes all stitched videos there
- Switching templates instantly refreshes the starting image grid — images already processed for the current template are hidden; switching to a template with no videos shows all images
- Library tab auto-updates its folder display when you switch templates
- Daily run log is written into the template's subfolder instead of the root
- Zero config changes required — root folder is still set once in Settings

### v3.4.0
- **Video Converter**: select one or more videos in the Library tab and click **🔄 Convert** to re-encode them to a photo-frame-compatible format
  - **AVI — Xvid**: widest digital photo frame support
  - **MP4 — H.264 Baseline**: universal device compatibility (re-encodes at Baseline/Level 3.1 + yuv420p)
  - **MOV — H.264**: QuickTime / Apple device compatibility
- Output folder defaults to the same folder as the source; can be changed per conversion
- Conversion runs in a background thread so the UI stays responsive; Cancel button stops mid-batch

### v3.3.0
- Poll log interval changed from 15 seconds to 1 minute — log now shows elapsed time in minutes (`2m`) instead of seconds to reduce log noise during long RunPod generations

### v3.2.0
- RunPod file-exists recovery: detects output files already present on RunPod before re-downloading
- Library tab shows selection count when multiple videos are selected

### v3.1.0
- **Auto Run mode**: processes all images in the folder automatically N at a time — no confirmation dialogs between batches
  - Configurable batch size spinner (1–50, default 4)
  - **▶▶ Auto Run** button starts the loop; processed images are removed from the grid automatically
  - **⏹ Stop After Batch** button finishes the current batch then stops cleanly
  - Auto mode is disabled when "Show all" is checked (prevents re-processing already-done images)
  - Auto mode stops automatically on error or cancellation
- **Library: Play Selected**: select multiple videos with Ctrl+click or Shift+click, then click **▶ Play Selected** to play them back-to-back in the built-in player (⏮/⏭ navigation, auto-advance on end)

### v3.0.1
- Fix: `_on_stitch_done` signal wiring carried over from single-mode; removed dead handler
- Minor log cleanup

### v3.0.0
- Starting Images sort combo: Name A→Z, Name Z→A, Newest First, Oldest First
- Daily log file: `ComfyUI_Chain_Log_mm_dd_yyyy.txt` written to final video folder each run
  - 80-char separator header between runs with date/time and image count
  - Each starting image listed on its own line
  - Logs segment times, zip archive names, total time; filters out poll-noise lines
- Unified all naming to "ComfyUI Workflow Chain Automator" / `ComfyUI_Chain_Automator`
- Source folder renamed from `CumfyUI_API` to `ComfyUI_Chain_Automator`

### v2.9.0
- Completion sound: optional audio cue on batch finish (configurable in Settings)
- Fix: total batch elapsed time now reflects full run including stitching

### v2.7.4
- Smart same-stem image filtering: images sharing a stem with an existing video are excluded from the Starting Images grid

### v2.7.3
- Auto-number output filename on collision (e.g. `photo_1.mp4`) to prevent overwriting

### v2.7.2
- Fix output filename collision when multiple images share the same stem

### v2.7.1
- Fix playlist not advancing correctly in batch playback
- Batch-only cleanup: removed unused single-mode code paths

### v2.7.0
- Batch-only mode: removed single/batch toggle — all runs are batch mode
- Chain folder dropdown: auto-detects segment count from `*_batch.json` files in selected folder

### v2.6.1
- Log: total batch elapsed time printed as final log line after stitching completes
- Log: append mode with rolling 50-batch history — older runs automatically trimmed on each new run

### v2.6.0
- Batch mode: Single/Batch toggle in UI; batch runs N images through all 7 segments in one pass using `LoadImageListFromDir //Inspire`
- Dual workflow sets: `workflow_segment_XX_batch.json` files in `{Chain}_Batch/` subfolder keep single and batch workflows separate
- RunPod batch upload: images uploaded directly into ComfyUI's input directory per segment via upload API
- FFmpeg local frame extraction with `-sseof -0.1` for smooth segment transitions (no full video upload between segments)
- Playlist video player: after batch completes, prompts to play all results back-to-back with ⏮⏭ navigation and auto-advance
- Settings: Batch Processing section with local dir, RunPod dir, and RunPod input dir fields
- Poll loop error detection: surfaces ComfyUI execution errors immediately instead of looping silently

### v2.5.1
- Fix: chain folder not persisted on startup when `active_chain_folder` was absent from config, causing worker to load workflows from root instead of selected subfolder
- Fix: segment dot double-click editor built wrong path when a chain folder was active

### v2.5.0
- Generate tab: IMG_* workflow picker, positive/negative prompts, seed control, two drag-and-drop reference image slots, gallery with Send to Chain / Delete / Clear buttons, Generate and Generate+Run Chain one-shot modes
- Chain tab: filtered image grid hides images that already have a video (Show all toggle), Chain folder dropdown lists Video_* subfolders, segment count auto-detected from folder contents
- Library tab: Delete button with confirmation to remove bad videos without leaving the app
- Worker: loads workflow JSON from the selected chain folder; node ID template falls back for extra segments

### v2.4.0
- Chain folder dropdown: select Video_* workflow folders; segment count auto-detected from workflow_segment_*.json files inside the folder
- Filtered image grid: hides images whose stem matches an existing library video

### v2.1.0
- Background image loading — window appears instantly, grid fills progressively
- Progress bar shows image loading status with count

### v2.0.0
- Split-pane layout: image grid left, controls right (1600×760 default)
- Thumbnails enlarged to 200px with black letterbox padding
- Segment count is dynamic — reads from workflow config, no hardcoded value
- Worker log messages use actual segment count
- Selection shown as accent border (no background fill)
- Scrollbar padding fix

### v1.1.0
- RunPod support
- EXE build via PyInstaller

### v1.0.0
- Initial release: 7-segment local chain automator
