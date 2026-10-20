# Changelog

## v1.4.0 — 2026-09-19
- **Renamed to ComfyUI Metadata Viewer** (was VHS Metadata Parser). The folder is now `ComfyUI_Metadata_Viewer/`, the script `comfyui_metadata_viewer.py`, the spec and EXE `ComfyUI_Metadata_Viewer`, and the deploy folder `P:\Apps\AICoded\ComfyUI Metadata Viewer\`. The old deploy folder is left in place for the user to delete. The IconMaker entry now points at the new folder.
- **Reads metadata from any ComfyUI output, not just MP4.** The user wanted to check a Flux.2 PNG's seed without dragging it into ComfyUI (Windows Properties doesn't show PNG text chunks).
  - **PNG:** `tEXt`, `iTXt` and compressed `zTXt` chunks are parsed properly.
  - **WebP / JPEG:** EXIF `prompt:{…}` / `workflow:{…}` tags, as written by `SaveAnimatedWEBP`.
  - **Audio:** FLAC Vorbis comments and MP3 ID3 frames (`prompt={…}`, `prompt\0{…}`).
  - **Other containers:** MKV, WebM, MOV and anything else, found with the same `{"prompt": …}` search MP4 already used.
  - **Any file:** a generic scan tries every `prompt` / `workflow` key it finds and keeps only JSON shaped like an API prompt (nodes with `class_type`) or a UI workflow (a `nodes` list), so false matches are ignored. Saved UI-workflow `.json` files now fill the Workflow tab.
  - Standard library only; no Pillow or mutagen, so the EXE stays small.
- **Fix: non-ASCII prompt text was dropped from MP4 metadata.** The old MP4 reader kept only ASCII bytes and counted braces even inside strings. JSON is now decoded properly (`raw_decode` over UTF-8), so accents, dashes and braces inside prompt text survive. Decoding starts with a 16 KB window and only widens when a real JSON block runs past it, so thousands of false `prompt` matches in a big file stay cheap.
- **File Header for every format** (was "MP4 Header"): PNG/WebP/JPEG/GIF sizes and MP4/MOV size + duration, e.g. `PNG, 1584×1312`. Width/height fall back to it whenever the workflow only has a link (Flux.2 edit's `GetImageSize`), shown as `1584 (from PNG header; workflow: → Get Image Size [68:72])`.
- Image workflows: `*LatentImage` nodes (EmptyLatentImage, EmptyFlux2LatentImage, …) supply width/height/batch; `SaveImage` / `SaveAnimatedWEBP` / `SaveAudio` supply the filename prefix. The first tab is now **Media Settings**.
- **Seed column in Batch / Search**, plus seed in the search filter, the Diff dialog and the summary CSV.
- **Explorer right-click entry:** Tools → Add "Open in ComfyUI Metadata Viewer" to Explorer right-click menu.
  - Writes a per-user verb under `HKCU\Software\Classes\*\shell\ComfyUIMetadataViewer` (no admin), set to single selection. Unticking removes it.
  - A frozen EXE that finds the entry pointing at a different path re-points it on launch (the EXE is portable).
  - From source, it registers `pythonw` + the script.
- A file with no ComfyUI metadata now says so, and why, in the drop zone instead of "Error loading file".
- File > Open lists images, videos, audio and exports, plus All Files. Batch scans all of those types.
- Verified headless: MP4 results identical to v1.3.1 on both test videos; three real Flux.2 PNGs (API-queued, prompt only) give seed/UNET/header; synthetic WebP (lossy + lossless), JPEG EXIF, FLAC-style, MP3-style and WebM-style files; saved workflow `.json`; bare prompt `.txt`; a 13 MB file with 3000 decoy matches (0.04 s); a 16 MB real video (0.15 s); a file with no metadata fails cleanly.

## v1.3.1 — 2026-09-04
- Version bump + EXE rebuild. The deployed v1.3.0 EXE predated the fixes listed under v1.3.0 below (MP4-header dimensions, layout un-clipping, resizable Negative pane, run.bat + CLI file argument); this build ships all of them. No functional changes beyond the version string.

## v1.3.0 — 2026-09-04
- **MiniMax H3 workflows now parse fully** (test file: `Test_files/MiniMax_H3_00008-audio.mp4`). Previously the Prompts tab was empty and Video/Sampler tabs showed `N/A` because the parser only knew `CLIPTextEncode`, `WanImageToVideo` and `KSamplerAdvanced`.
- `MetadataParser` rewritten around `_take()` / `_resolve()`: every input is read through a helper that follows `[node_id, slot]` links back to a literal (same-named input on the source node, a `value` primitive, a `ComfyMathExpression` evaluated with a whitelisted namespace, or a prompt-text input) and records the (node, input) pair as *consumed*.
- Prompt extraction is generic: any node input named `prompt`, `text`, `positive`, `negative`, `positive_prompt`, `negative_prompt`, `custom_prompts`, `string`, `text_positive`, `text_negative`. Literal strings first, then links, de-duplicated by text. Fixes `CLIPTextEncode.text` linked from `PromptCycler` showing as `['126', 0]`.
- New `parse_prompt_sections()` + **Prompt Sections** table (Source / Section / Content) on the Prompts tab: `[Shot N] At mm:ss.mmm` → `Shot N @ mm:ss.mmm`, `<d>…</d>` → `Shot N · Dialogue`, `Camera:` / `overall_soundscape:` / `non_diegetic_music:` / any `Label:` or `snake_case_key:` → own row, JSON prompts → one row per key. Negative prompts tinted red, dialogue rows tinted cyan. Raw positive/negative boxes kept below in a splitter.
- New **Other Settings** tab (after Sampler): `get_other_settings()` lists every literal node input that no extractor consumed — Node ID / Node Type / Title / Setting / Value — with a text filter and a "show nodes that have no literal settings" toggle. Also appended as a section to the Models/Sampler CSV export (menu + buttons renamed to "Export Models, Sampler & Other Settings").
- Video settings: any `*ToVideo` / `*LatentVideo` node supplies width/height/length/batch_size; `VHS_VideoCombine` supplies `has_audio` (names the audio source node); `duration_s = length / frame_rate`. `ImageResizeKJv2` / `ImageScale` / `ImageResize+` fill in width/height only when the primary value is unresolved. UI rows added: Duration (s), Audio.
- Sampler: handles `KSampler*` (seed or noise_seed, denoise) and `SamplerCustomAdvanced` / `SamplerCustom` (seed via `RandomNoise`, steps/scheduler/denoise via `BasicScheduler`, sampler via `KSamplerSelect` or the linked sampler node's title such as "MiniMax-H3 Turbo Sampler (4-step)", CFG via CFGGuider else "N/A (Basic Guider)"). Denoise column added.
- Models: detection by input name (`clip_name`, `clip_name1..3`, `vae_name`, `unet_name`, `ckpt_name`, `lora_name` with `strength_model` or `strength`), so `MiniMaxH3TurboLoRA` and checkpoint loaders appear. LoRA table gains a Loader column. Model Sampling covers all `ModelSampling*` nodes (non-`shift` literals are joined as `k=v`).
- `parse_file()` accepts bare API-format prompt JSON (dict of `{id: {class_type, inputs}}`) and resets state between loads.
- Batch: `summarize_file()` rows gain `duration_s` / `has_audio`; Diff dialog and batch CSV include Duration (s) and Audio.
- Fix: prompt-section rows are re-fitted when the tab is shown / columns resized (rows were sized before layout and came out huge); `&` in button/menu labels escaped so it is not eaten as a mnemonic.
- Version bumped to 1.3.0 (docstring, window title, docs).
- Added `run.bat` (runs from source via the shared `..\.venv`, falls back to `python` on PATH) and an optional command-line file argument: `run.bat path\to\file.mp4` opens it on launch.
- Width/height/duration are now read from the MP4 container header (`tkhd` / `mvhd`) and used whenever the workflow only has a link for them (MiniMax `GetImageSize` case). Video Settings shows e.g. `832 (from MP4 header; workflow: → Get Image Size [120])` plus a new **MP4 Header** row (`832×640, 15.08 s`) for cross-checking.
- Layout fixes from screenshots: drop-zone label no longer clips its three lines (min height from font metrics); Video Settings group boxes keep their natural height and the tab scrolls instead of squashing the line edits when the window is short.
- Prompts tab: Positive and Negative raw boxes are now separate splitter panes (drag either edge, or collapse a pane entirely). When a file has no negative prompt the Negative pane auto-shrinks to one line instead of wasting a third of the tab; it gets ~20% of the height when one exists.

## v1.2.0 — 2026-07-08
- New **Batch / Search** tab: scan a folder (optionally recursive) for `.mp4`/`.json`/`.txt` metadata files on a background `QThread`, with a live progress status label.
- Summary table per scanned file: filename, width, height, length, frame rate, format, sampler steps/CFG/name, LoRA names, UNET names.
- Live search box filters the batch table by filename, LoRA/model name, sampler, or prompt text — answers "which videos used LoRA X?".
- Diff view: select exactly two rows (Ctrl+Click) and click "Diff Selected" to open a dialog comparing key metadata fields side by side, with differing fields highlighted.
- "Export Summary CSV" writes the currently filtered batch table to a CSV file.
- Double-click a batch row to load that file into the main single-file viewer tabs.
- Added a `summarize_file()` helper and `row_matches_search()` used by both the batch table and search filter.
- `VHS_Metadata_Parser.spec` gained an `excludes` list for shared-venv ML packages (torch, cv2, numpy, etc.) to keep the EXE small.

## v1.1.1 (pre-existing, undocumented)
- Version bump only; no changelog entry existed prior to this file.

## v1.1.0
- Migrated from PyQt5 to PyQt6.
- Dark blue-green theme applied throughout.
- Updated all Qt6 enum flags (ResizeMode, EditTrigger, etc.).

## v1.0.0
- Initial release with PyQt5.
- Tabbed metadata viewer.
- Drag & drop and file browser support.
