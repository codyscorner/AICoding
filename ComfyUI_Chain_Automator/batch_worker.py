import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from metadata_parser import extract_segment_prompt, ffmetadata_escape, build_prompts_text
from remote_cleanup import OutputCleaner, enabled as cleanup_enabled

logger = logging.getLogger("batch_chain")
logger.setLevel(logging.DEBUG)


LIST_LOADER_TYPE = "LoadImageListFromDir //Inspire"
LIST_LOADER_TITLE = "Load Image List From Dir (Inspire)"
BATCH_FILE_GLOB = "workflow_segment_*_batch.json"
LIST_LOADER_SORT = "Alphabetical (ASC)"   # Inspire sort_method; names are zero-padded

# Stitch audio: one common format so segments with different sample rates /
# channel layouts can still be concatenated (same values as Video Creator).
AUDIO_RATE = 48000
AUDIO_NORM = (
    "aresample=async=1:first_pts=0,"
    f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=stereo"
)


def check_batch_workflow_wiring(workflow: dict, json_file: str) -> list[str]:
    """Verify that one batch workflow (API-format JSON) will actually fan out.

    ComfyUI only renders one video per image when the list loader's output
    feeds the rest of the graph. If the loader is missing, or present but
    orphaned (the graph still takes its first frame from a plain LoadImage
    node), the server runs the workflow exactly once regardless of batch
    size and the run dies late with a misleading "expected N output videos,
    ComfyUI returned 1" error.

    Raises RuntimeError with a specific, actionable message on a blocking
    problem. Returns a list of non-blocking warning strings."""
    if not isinstance(workflow, dict) or not workflow:
        raise RuntimeError(
            f"{json_file}: the file is empty or is not a ComfyUI API-format "
            f"workflow (expected a JSON object of node-id -> node). In ComfyUI "
            f"use Workflow > Export (API) and save it over this file."
        )

    def _title(nid: str) -> str:
        node = workflow.get(nid, {})
        return node.get("_meta", {}).get("title") or node.get("class_type", "?")

    loader_ids = [
        nid for nid, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == LIST_LOADER_TYPE
    ]
    plain_loaders = [
        nid for nid, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == "LoadImage"
    ]

    if not loader_ids:
        hint = ""
        if plain_loaders:
            fixed = ", ".join(
                f"'{workflow[nid].get('inputs', {}).get('image', '?')}' (node {nid})"
                for nid in plain_loaders
            )
            hint = (
                f" The image source is currently a plain 'Load Image' node "
                f"fixed to {fixed}, which would feed the same picture to "
                f"every item in the batch."
            )
        raise RuntimeError(
            f"{json_file}: no '{LIST_LOADER_TITLE}' node in the workflow.{hint}\n"
            f"Fix: in ComfyUI add a '{LIST_LOADER_TITLE}' node, connect its "
            f"IMAGE output to the image-scale / first-frame input that the "
            f"Load Image node currently feeds, delete the Load Image node, "
            f"then Workflow > Export (API) and save it over this file."
        )

    # Node inputs that are links look like [source_node_id, slot]
    def _consumers(src_id: str) -> list[str]:
        out = []
        for nid, node in workflow.items():
            if nid == src_id or not isinstance(node, dict):
                continue
            for value in node.get("inputs", {}).values():
                if (isinstance(value, list) and len(value) == 2
                        and str(value[0]) == src_id):
                    out.append(nid)
                    break
        return out

    for loader_id in loader_ids:
        if _consumers(loader_id):
            continue
        # Name the node that currently feeds the graph instead, if we can.
        feeding = ""
        if plain_loaders:
            parts = []
            for pid in plain_loaders:
                targets = _consumers(pid)
                img = workflow[pid].get("inputs", {}).get("image", "?")
                if targets:
                    tnames = ", ".join(f"'{_title(t)}' (node {t})" for t in targets)
                    parts.append(
                        f"'Load Image' node {pid} (fixed to '{img}') feeds {tnames}"
                    )
                else:
                    parts.append(f"'Load Image' node {pid} (fixed to '{img}')")
            feeding = " Instead, " + "; ".join(parts) + "."
        raise RuntimeError(
            f"{json_file}: the '{LIST_LOADER_TITLE}' node (node {loader_id}) "
            f"is not connected to anything, so ComfyUI would render only one "
            f"image no matter how many are in the batch.{feeding}\n"
            f"Fix: in ComfyUI connect the IMAGE output of node {loader_id} to "
            f"the image-scale / first-frame input, remove the plain Load Image "
            f"node, then Workflow > Export (API) and save it over this file."
        )

    warnings = []
    if plain_loaders:
        warnings.append(
            f"{json_file} still contains a plain 'Load Image' node "
            f"(node {', '.join(plain_loaders)}). The batch never patches it, so "
            f"anything it feeds will use the same fixed image for every item."
        )
    return warnings


def validate_batch_chain_dir(chain_dir: Path) -> tuple[list[str], list[str]]:
    """Validate every batch workflow the chain would run, in segment order.

    Returns (errors, warnings). Any error means the batch must not start.
    Each message names the file, the node, and what to change."""
    errors: list[str] = []
    warnings: list[str] = []
    chain_dir = Path(chain_dir)
    if not chain_dir.is_dir():
        return [f"Chain folder not found: {chain_dir}"], warnings
    files = sorted(chain_dir.glob(BATCH_FILE_GLOB))
    if not files:
        return [
            f"No {BATCH_FILE_GLOB} files in {chain_dir}. Batch mode needs at "
            f"least workflow_segment_01_batch.json exported from ComfyUI "
            f"(Workflow > Export (API))."
        ], warnings
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                workflow = json.load(fh)
        except Exception as e:  # any read/parse failure blocks the batch
            errors.append(f"{f.name}: cannot read the workflow JSON ({e}).")
            continue
        try:
            warnings.extend(check_batch_workflow_wiring(workflow, f.name))
        except RuntimeError as e:
            errors.append(str(e))
    return errors, warnings


class BatchChainWorker(QThread):
    log = pyqtSignal(str)
    segment_done = pyqtSignal(int)
    segment_time = pyqtSignal(int, str)
    segment_secs = pyqtSignal(int, float)     # segment, elapsed seconds (for ETA)
    step_progress = pyqtSignal(int, int, int)  # segment, step value, step max
    segment_plan = pyqtSignal(int, int, int, int)   # segment, expected sampler passes, expected total steps, post-sampler phase count
    phase_progress = pyqtSignal(int)  # segment — a post-sampler phase (VAE decode, encode, save) started
    all_done = pyqtSignal(list)   # list[str] of final video paths
    error = pyqtSignal(str)

    def __init__(self, config: dict, images: list[str]):
        super().__init__()
        self._config = config
        self._images = images
        self._cancelled = False
        self._active_prompt_id = ""
        self._total_segs = len(config.get("workflows", []))
        self._client_id = str(uuid.uuid4())
        self._run_id = str(int(time.time() * 1000))
        # Suffix for stitched filenames so re-running the same source image
        # (e.g. after cleaning out a folder) never collides with or gets
        # skipped by an earlier batch's video of the same name.
        self._run_stamp = time.strftime("%Y%m%d_%H%M%S")
        self._runpod = config.get("mode", "local") == "runpod"
        self._url = (
            config.get("runpod_url", "").rstrip("/")
            if self._runpod
            else config.get("comfyui_url", "http://127.0.0.1:8000").rstrip("/")
        )
        self._batch_dir_local = Path(config.get("batch_dir_local", ""))
        self._batch_dir_runpod = config.get("batch_dir_runpod", "/workspace/runpod-slim/Batch_Processing")
        self._runpod_input_dir = config.get("runpod_input_dir", "/workspace/runpod-slim/ComfyUI/input")
        base_dir = Path(config.get("_base_dir", str(Path(__file__).parent)))
        self._temp_dir = base_dir / "temp"

        log_path = base_dir / "batch_run_log.txt"
        self._trim_log(log_path, keep=50)
        fh = logging.FileHandler(str(log_path), mode='a', encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S'))
        logger.handlers.clear()
        logger.addHandler(fh)

    def cancel(self):
        self._cancelled = True
        # Stop the job on the ComfyUI server too — otherwise the prompt keeps
        # running (and on RunPod keeps billing) after the UI says cancelled.
        threading.Thread(target=self._interrupt_server, daemon=True).start()

    def _interrupt_server(self):
        try:
            requests.post(f"{self._url}/queue", json={"delete": [self._active_prompt_id]}, timeout=10)
        except Exception:
            pass
        try:
            requests.post(f"{self._url}/interrupt", timeout=10)
        except Exception:
            pass

    def _log(self, msg: str):
        self.log.emit(msg)
        logger.info(msg)

    # ------------------------------------------------------------------ #
    # Main thread entry
    # ------------------------------------------------------------------ #

    def run(self):
        try:
            logger.info("=== New batch run started ===")
            batch_start = time.time()

            # The thumbnails cache folder holds small downscaled previews —
            # if the image folder is misconfigured to point at it directly,
            # those tiny files would get sent to ComfyUI and come back
            # blurry/warped once upscaled. Refuse to run rather than send
            # the wrong file.
            input_dir = Path(self._config["input_dir"])
            if input_dir.name.lower() == "thumbnails":
                self.error.emit(
                    f"Image folder is set to a 'thumbnails' cache folder ({input_dir}), "
                    "which only holds small downscaled previews. Point Image folder at "
                    "the parent folder that contains the full-size originals."
                )
                return

            workflows = self._build_effective_workflows()
            self._total_segs = len(workflows)

            # Pre-flight every segment before touching temp files or
            # uploading anything: a batch workflow with no list loader, or
            # one whose loader is orphaned, would only ever render one
            # image, so refuse to start rather than fail after minutes of
            # server time.
            for wf in workflows:
                self._check_batch_wiring(self._load_workflow(wf), wf["json_file"])

            self._temp_dir.mkdir(exist_ok=True)
            self._clean_temp_dir()
            self._batch_dir_local.mkdir(parents=True, exist_ok=True)
            n = len(self._images)
            self._log(f"Batch: {n} image{'s' if n != 1 else ''}")

            # Local mode: prepare fixed per-segment subdirs
            seg_subdirs = {}
            if not self._runpod:
                for wf in workflows:
                    s = wf["segment"]
                    d = self._batch_dir_local / f"seg_{s}"
                    d.mkdir(parents=True, exist_ok=True)
                    seg_subdirs[s] = d

            # segment_outputs[seg_idx] = list of N video Paths (one per image)
            segment_outputs: list[list[Path]] = []
            # transition_frames[i] = frames extracted between segments for image i
            transition_frames: list[list[Path]] = [[] for _ in range(n)]

            for wf in workflows:
                if self._cancelled:
                    self._log("Cancelled.")
                    return

                seg = wf["segment"]
                seg_start = time.time()
                self._log(f"[Segment {seg}/{self._total_segs}] Starting — {n} images in batch...")

                workflow_json = self._load_workflow(wf)
                self._bust_cache(workflow_json)

                # Use run-ID subfolder so each run gets an isolated, clean directory
                upload_subfolder = f"Batch_Processing/{self._run_id}/seg_{seg}"

                if seg == 1:
                    input_dir = Path(self._config["input_dir"])
                    if self._runpod:
                        for i, img_name in enumerate(self._images):
                            src = input_dir / img_name
                            fname = f"{i+1:03d}_{src.name}"
                            self._upload_batch_image(src, upload_subfolder, fname)
                        self._log(f"[Segment {seg}/{self._total_segs}] Uploaded {n} starting images")
                    else:
                        local_subdir = seg_subdirs[seg]
                        for f in local_subdir.iterdir():
                            if f.is_file(): f.unlink()
                        for i, img_name in enumerate(self._images):
                            src = input_dir / img_name
                            shutil.copy2(src, local_subdir / f"{i+1:03d}_{src.name}")
                        self._log(f"[Segment {seg}/{self._total_segs}] Staged {n} starting images")
                else:
                    prev_videos = segment_outputs[-1]
                    if self._runpod:
                        for i, prev_video in enumerate(prev_videos):
                            frame = self._temp_dir / f"{i+1:03d}_frame_seg{seg}.png"
                            self._extract_last_frame_to(prev_video, frame)
                            self._upload_batch_image(frame, upload_subfolder, frame.name)
                            transition_frames[i].append(frame)
                        self._log(f"[Segment {seg}/{self._total_segs}] Uploaded {n} frames")
                    else:
                        local_subdir = seg_subdirs[seg]
                        for f in local_subdir.iterdir():
                            if f.is_file(): f.unlink()
                        for i, prev_video in enumerate(prev_videos):
                            dst = local_subdir / f"{i+1:03d}_frame_seg{seg}.png"
                            self._extract_last_frame_to(prev_video, dst)
                            transition_frames[i].append(dst)
                        self._log(f"[Segment {seg}/{self._total_segs}] Extracted {n} last frames")

                # Set directory for LoadImageListFromDir
                if self._runpod:
                    dir_path = f"{self._runpod_input_dir}/Batch_Processing/{self._run_id}/seg_{seg}"
                else:
                    dir_path = str(seg_subdirs[seg])
                self._patch_batch_input(workflow_json, dir_path)
                self._patch_batch_output_prefix(workflow_json, seg)

                # Tell the UI how much sampler work this segment holds:
                # every sampler runs once per image in the batch
                steps_per_image = self._sampler_steps(workflow_json)
                post_phases = self._count_post_phases(workflow_json)
                self.segment_plan.emit(seg, len(steps_per_image) * n, sum(steps_per_image) * n, post_phases)

                prompt_id = self._queue_prompt(workflow_json)
                self._active_prompt_id = prompt_id
                self._log(f"[Segment {seg}/{self._total_segs}] Queued ({prompt_id[:8]}...), polling...")

                self._wait_until_done(prompt_id, seg, workflow_json)
                if self._cancelled:
                    self._log("Cancelled.")
                    return

                if self._runpod:
                    time.sleep(5)
                videos = self._download_batch_outputs(seg, prompt_id, n, workflow_json)
                elapsed_secs = time.time() - seg_start
                elapsed = self._fmt(elapsed_secs)
                self._log(f"[Segment {seg}/{self._total_segs}] Done in {elapsed} — {n} videos")
                segment_outputs.append(videos)
                self.segment_done.emit(seg)
                self.segment_time.emit(seg, elapsed)
                self.segment_secs.emit(seg, elapsed_secs)

            if self._cancelled:
                return

            self._log("All segments complete. Stitching final videos...")
            final_paths = []
            for i, img_name in enumerate(self._images):
                chain_videos = [segment_outputs[s][i] for s in range(len(workflows))]
                final, seg_meta = self._stitch(chain_videos, img_name)
                final_paths.append(str(final))
                size_kb = final.stat().st_size // 1024
                self._log(f"  [{i+1}/{n}] {final.name}  ({size_kb} KB)")
                src_image = Path(self._config["input_dir"]) / img_name
                zip_path = self._zip_segments(chain_videos, final, src_image, transition_frames[i], seg_meta)
                self._log(f"  [{i+1}/{n}] Archive: {zip_path.name}")

            self._log(f"Total time: {self._fmt(time.time() - batch_start)}")
            self.all_done.emit(final_paths)

        except Exception as e:
            logger.exception("Batch chain error")
            self.error.emit(str(e))

    # ------------------------------------------------------------------ #
    # Workflow patching
    # ------------------------------------------------------------------ #

    def _upload_batch_image(self, image_path: Path, subfolder: str, filename: str):
        with open(image_path, 'rb') as f:
            resp = requests.post(
                f"{self._url}/upload/image",
                files={"image": (filename, f, "image/png")},
                data={"type": "input", "subfolder": subfolder, "overwrite": "true"},
                timeout=120,
            )
        resp.raise_for_status()

    _LIST_LOADER_TYPE = LIST_LOADER_TYPE

    def _patch_batch_input(self, workflow: dict, directory: str):
        for node in workflow.values():
            if node.get("class_type") == self._LIST_LOADER_TYPE:
                node["inputs"]["directory"] = directory
                # Outputs are paired back to images by position, so the loader
                # must return 001_, 002_, ... in name order. With the node's
                # default sort_method "None" it returns raw os.listdir order,
                # which on the pod's Linux filesystem is arbitrary and swapped
                # the segments between videos.
                node["inputs"]["sort_method"] = LIST_LOADER_SORT
                return

    def _check_batch_wiring(self, workflow: dict, json_file: str):
        """Pre-flight (run for every segment before the batch starts).

        The UI already validates the whole chain folder when it is selected
        and refuses to start on problems (see validate_batch_chain_dir);
        this is the last line of defence in case a file was edited between
        selection and Start. Raises RuntimeError on a blocking problem and
        logs any non-blocking warnings."""
        for warning in check_batch_workflow_wiring(workflow, json_file):
            self._log(f"  Warning: {warning}")

    _VIDEO_OUTPUT_TYPES = {"VHS_VideoCombine", "SaveVideo"}

    # Post-sampling nodes worth a log line — the websocket goes quiet for
    # these (no "progress" events), which otherwise reads as a hang during
    # MiniMax H3's VAE decode / video encode stretch between the last
    # sampler step and the finished file.
    _STATUS_NODE_LABELS = {
        "VAEDecode": "Decoding video (VAE)...",
        "VAEDecodeAudio": "Decoding audio (VAE)...",
        "CreateVideo": "Encoding video...",
        "SaveVideo": "Saving video...",
        "VHS_VideoCombine": "Saving video...",
    }

    def _patch_batch_output_prefix(self, workflow: dict, seg: int):
        for node in workflow.values():
            if node.get("class_type") in self._VIDEO_OUTPUT_TYPES:
                node["inputs"]["filename_prefix"] = f"Merge/{self._run_id}/Batch_{seg}"
                break

    @staticmethod
    def _sampler_steps(workflow: dict) -> list[int]:
        """Executed steps of every sampler node in the workflow. Each sampler
        runs once per image (list processing), emitting one progress cycle of
        this many steps. WAN 2.2's hi/lo KSamplerAdvanced pair with steps=4
        split at 0-2 / 2-4 yields [2, 2].

        MiniMax H3's SamplerCustomAdvanced/KSamplerSelect nodes don't carry
        a `steps` input themselves — the step count instead lives on the
        upstream BasicScheduler node that builds their sigma schedule — so
        that node type is treated as a step source too."""
        out = []
        for node in workflow.values():
            class_type = node.get("class_type", "")
            if "sampler" not in class_type.lower() and class_type != "BasicScheduler":
                continue
            inp = node.get("inputs", {})
            steps = inp.get("steps")
            if not isinstance(steps, int) or steps <= 0:
                continue
            start, end = inp.get("start_at_step"), inp.get("end_at_step")
            if isinstance(start, int) and isinstance(end, int):
                steps = max(0, min(end, steps) - max(start, 0))
            if steps:
                out.append(steps)
        return out

    def _count_post_phases(self, workflow: dict) -> int:
        """Number of distinct post-sampler nodes (VAE decode, encode, save)
        this workflow will run through. The sampler's progress events end at
        100% well before the file is actually written — these phases have no
        step-level progress of their own, so each counts as one unit tacked
        onto the segment's step total, keeping the bar honest until the last
        one finishes."""
        return sum(
            1 for node in workflow.values()
            if node.get("class_type", "") in self._STATUS_NODE_LABELS
        )

    def _bust_cache(self, workflow: dict):
        new_seed = int(uuid.uuid4().int % (2**32))
        for node in workflow.values():
            inp = node.get("inputs", {})
            if "noise_seed" in inp:
                inp["noise_seed"] = new_seed
            if "seed" in inp and isinstance(inp["seed"], int):
                inp["seed"] = new_seed

    # ------------------------------------------------------------------ #
    # Output collection
    # ------------------------------------------------------------------ #

    def _download_batch_outputs(self, seg: int, prompt_id: str, n: int, workflow: dict | None = None) -> list[Path]:
        history_url = f"{self._url}/history/{prompt_id}"
        resp = requests.get(history_url, timeout=15)
        resp.raise_for_status()
        history = resp.json().get(prompt_id, {})
        outputs = history.get("outputs", {})
        cleaner = OutputCleaner(self._config, self._log) if self._runpod and cleanup_enabled(self._config) else None

        all_files = []
        # ComfyUI's native SaveVideo node (MiniMax H3 workflows) reports its
        # result under the "images" key, same as any image-preview node —
        # so scan the known video-output node ids first to avoid grabbing
        # an unrelated node's "images" list.
        video_node_ids = {
            nid for nid, node in (workflow or {}).items()
            if node.get("class_type") in self._VIDEO_OUTPUT_TYPES
        }
        for nid in video_node_ids:
            files = outputs.get(nid, {})
            files = files.get("videos") or files.get("gifs") or files.get("images") or []
            if files:
                all_files = sorted(files, key=lambda f: f["filename"])
                break

        if not all_files:
            for node_output in outputs.values():
                files = node_output.get("videos") or node_output.get("gifs") or []
                if files:
                    all_files = sorted(files, key=lambda f: f["filename"])
                    break

        if not all_files:
            if getattr(self, '_already_exists_seg', None) == seg:
                self._already_exists_seg = None
                self._log(f"  No history outputs — waiting 2s for writes to finish...")
                time.sleep(2)
                subfolder = f"Merge/{self._run_id}"
                downloaded = []
                for i in range(1, n + 1):
                    filename = f"Batch_{seg}_{i:05d}.mp4"
                    self._log(f"  Downloading {i}/{n}: {filename}")
                    params = {"filename": filename, "subfolder": subfolder, "type": "output"}
                    for attempt in range(6):
                        dl = requests.get(f"{self._url}/view", params=params, timeout=300, stream=True)
                        if dl.status_code == 200:
                            break
                        self._log(f"  Not ready, retrying ({attempt+1}/6)...")
                        time.sleep(5)
                    dl.raise_for_status()
                    local = self._temp_dir / f"batch_seg{seg}_{i:03d}.mp4"
                    with open(local, 'wb') as f:
                        for chunk in dl.iter_content(1024 * 1024):
                            f.write(chunk)
                    downloaded.append(local)
                    if cleaner:
                        cleaner.delete_if_downloaded(
                            {"filename": filename, "subfolder": subfolder, "type": "output"}, local)
                return downloaded
            raise RuntimeError(f"No output videos in history for batch segment {seg}")

        if len(all_files) != n:
            # A silent truncation here would stitch every image after the gap
            # to the wrong chain of videos — fail loudly instead.
            names = ", ".join(f["filename"] for f in all_files)
            raise RuntimeError(
                f"Segment {seg}: expected {n} output videos, ComfyUI returned "
                f"{len(all_files)} ({names or 'none'}). One or more images "
                f"failed on the server — check the ComfyUI console."
            )

        downloaded = []
        for idx, file_info in enumerate(all_files):
            filename = file_info["filename"]
            subfolder = file_info.get("subfolder", "")
            self._log(f"  Downloading {idx+1}/{len(all_files)}: {filename}")
            params = {"filename": filename, "subfolder": subfolder, "type": "output"}
            for attempt in range(6):
                dl = requests.get(f"{self._url}/view", params=params, timeout=300, stream=True)
                if dl.status_code == 200:
                    break
                self._log(f"  Not ready, retrying ({attempt+1}/6)...")
                time.sleep(5)
            dl.raise_for_status()
            local = self._temp_dir / f"batch_seg{seg}_{idx+1:03d}.mp4"
            with open(local, 'wb') as f:
                for chunk in dl.iter_content(1024 * 1024):
                    f.write(chunk)
            downloaded.append(local)
            if cleaner:
                cleaner.delete_if_downloaded(file_info, local)

        return downloaded

    # ------------------------------------------------------------------ #
    # Frame extraction
    # ------------------------------------------------------------------ #

    def _extract_last_frame_to(self, video_path: Path, dst: Path) -> Path:
        ffmpeg = self._config.get("ffmpeg_path", "ffmpeg")
        result = subprocess.run(
            [ffmpeg, "-y", "-sseof", "-0.1", "-i", str(video_path),
             "-vframes", "1", "-q:v", "2", str(dst)],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg frame extraction failed:\n{result.stderr}")
        return dst

    # ------------------------------------------------------------------ #
    # Stitch
    # ------------------------------------------------------------------ #

    def _zip_segments(self, videos: list[Path], final_path: Path, src_image: Path,
                       frames: list[Path] | None = None, seg_meta: dict | None = None) -> Path:
        zip_dir = Path(self._config.get("zip_output_dir", self._config.get("final_video_dir", str(final_path.parent))))
        zip_dir.mkdir(parents=True, exist_ok=True)
        zip_path = zip_dir / f"{final_path.stem}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            if src_image.exists():
                self._zip_write_safe(zf, src_image, src_image.name)
            for seg_idx, frame in enumerate(frames or [], start=2):
                if frame.exists():
                    self._zip_write_safe(zf, frame, f"frame_start_seg{seg_idx}.png")
            for v in videos:
                self._zip_write_safe(zf, v, v.name)
            self._zip_write_safe(zf, final_path, final_path.name)
            if seg_meta:
                zf.writestr("prompts.txt", build_prompts_text(seg_meta))
        return zip_path

    @staticmethod
    def _zip_write_safe(zf: zipfile.ZipFile, path: Path, arcname: str):
        try:
            zf.write(path, arcname)
        except (OSError, ValueError):
            # A corrupted/out-of-range file mtime (seen on some exported
            # source images) makes ZipInfo.from_file crash in time.localtime
            # with [Errno 22] on Windows — fall back to a manual ZipInfo
            # stamped with the current time instead of failing the batch.
            info = zipfile.ZipInfo(arcname, date_time=time.localtime()[:6])
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())

    def _extract_all_segment_prompts(self, videos: list[Path]) -> dict:
        """Pull each segment's embedded ComfyUI prompt graph before the
        source clips are discarded (ffmpeg concat below re-encodes and
        drops it)."""
        segments = {}
        for idx, v in enumerate(videos, start=1):
            prompt = extract_segment_prompt(v)
            if prompt:
                segments[str(idx)] = prompt
        return segments

    def _write_ffmetadata_file(self, segments: dict, stem: str) -> Optional[Path]:
        """Write the per-segment prompt graphs to an ffmpeg ffmetadata file
        so the stitch below can re-embed them into the final video via
        -map_metadata (a file avoids the Windows command-line length limit
        a multi-segment JSON blob could hit as a raw -metadata argument)."""
        if not segments:
            return None
        payload = json.dumps({"chain_automator_segments": segments}, ensure_ascii=False, separators=(',', ':'))
        meta_path = self._temp_dir / f"meta_{stem}.txt"
        content = ";FFMETADATA1\ncomment=" + ffmetadata_escape(payload) + "\n"
        meta_path.write_text(content, encoding='utf-8')
        return meta_path

    def _video_has_audio(self, path: Path, ffmpeg: str) -> bool:
        result = subprocess.run(
            [ffmpeg, "-i", str(path)],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Audio:" in result.stderr

    def _ffprobe_path(self, ffmpeg: str) -> str:
        p = Path(ffmpeg)
        for cand in (p.parent / "ffprobe.exe", p.parent / "ffprobe"):
            if cand.exists():
                return str(cand)
        return "ffprobe"

    def _probe_video_props(self, path: Path, ffmpeg: str) -> tuple[int, int, str]:
        """Return (width, height, r_frame_rate) of a video's first stream,
        or (0, 0, "") if ffprobe fails or the values look unusable."""
        result = subprocess.run(
            [self._ffprobe_path(ffmpeg), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            info = json.loads(result.stdout)["streams"][0]
            width, height, fps = int(info["width"]), int(info["height"]), info["r_frame_rate"]
            if width and height and fps and fps != "0/0":
                return width, height, fps
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        return 0, 0, ""

    def _probe_video_props_safe(self, path: Path, ffmpeg: str) -> tuple[int, int, str]:
        """_probe_video_props, but tolerant of a missing/unresolvable ffprobe
        binary (e.g. only ffmpeg.exe is configured, no ffprobe alongside it)
        — falls back to no normalization instead of crashing the stitch."""
        try:
            return self._probe_video_props(path, ffmpeg)
        except OSError:
            # No ffprobe next to ffmpeg (the deployed app only ships ffmpeg.exe)
            # — read the same numbers from ffmpeg's own stream dump instead.
            return self._probe_video_props_ffmpeg(path, ffmpeg)

    def _probe_video_props_ffmpeg(self, path: Path, ffmpeg: str) -> tuple[int, int, str]:
        """(width, height, fps) parsed from `ffmpeg -i` output, or (0, 0, "")."""
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                capture_output=True, text=True, errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            return 0, 0, ""
        # Anchor on the "Stream #n:n...: Video:" line — embedded metadata
        # (the ComfyUI prompt JSON) is dumped into the same output.
        m = re.search(r"^\s*Stream #\d+:\d+.*?: Video:.*?,\s*(\d{2,5})x(\d{2,5})\b.*?(\d+(?:\.\d+)?) fps",
                      result.stderr, re.MULTILINE)
        if not m:
            return 0, 0, ""
        return int(m.group(1)), int(m.group(2)), m.group(3)

    def _stitch(self, videos: list[Path], img_name: str) -> tuple[Path, dict]:
        final_dir = Path(self._config.get("final_video_dir", self._config["output_base_dir"]))
        final_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(img_name).stem
        final_path = final_dir / f"{stem}_{self._run_stamp}.mp4"
        n = len(videos)

        seg_meta = self._extract_all_segment_prompts(videos)

        # A single-segment chain has nothing to concatenate — copy the raw
        # download straight to the final name instead of round-tripping it
        # through ffmpeg, which only re-encodes it and risks introducing
        # its own artifacts for zero benefit.
        if n == 1:
            shutil.copy2(videos[0], final_path)
            return final_path, seg_meta

        ffmpeg = self._config.get("ffmpeg_path", "ffmpeg")
        inputs = []
        for v in videos:
            inputs += ["-i", str(v)]

        # Segments can differ in resolution/fps/SAR when a chain mixes
        # workflow templates with different output settings (e.g. one
        # segment saved at 18fps while the rest are 16fps) — concatenating
        # those streams unnormalized produces a rippling "underwater" warp
        # in the stitched result even though each segment plays back fine
        # on its own. Normalize every input to the first segment's
        # width/height/fps before concat.
        width, height, fps = self._probe_video_props_safe(videos[0], ffmpeg)
        if width and height and fps:
            # Fit inside the first segment's frame and pad with black rather than
            # stretching, so a segment saved at a slightly different aspect
            # (e.g. 896x704 after 832x640) isn't distorted. libx264 + yuv420p
            # need even dimensions.
            width, height = width - width % 2, height - height % 2
            norm = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"setsar=1,fps={fps},format=yuv420p"
            )
            filter_v = "".join(f"[{i}:v]{norm}[v{i}];" for i in range(n))
            v_pads = [f"[v{i}]" for i in range(n)]
        else:
            filter_v = ""
            v_pads = [f"[{i}:v]" for i in range(n)]

        # MiniMax H3 segments generate their own synced audio track (unlike
        # WAN's video-only output) — concat it alongside video when every
        # segment has one, otherwise fall back to the video-only path so
        # silent WAN chains keep working unchanged.
        has_audio = n > 0 and all(self._video_has_audio(v, ffmpeg) for v in videos)
        if has_audio:
            # concat wants its inputs interleaved per segment (v0 a0 v1 a1 ...),
            # not all video pads followed by all audio pads.
            # Every segment's audio is resampled to one common format first —
            # concat refuses inputs whose sample rate / channel layout differ.
            filter_a = "".join(f"[{i}:a]{AUDIO_NORM}[a{i}];" for i in range(n))
            concat_inputs = "".join(f"{v_pads[i]}[a{i}]" for i in range(n))
            filter_complex = f"{filter_v}{filter_a}{concat_inputs}concat=n={n}:v=1:a=1[out][outa]"
            map_args = ["-map", "[out]", "-map", "[outa]"]
            audio_args = ["-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE)]
        else:
            filter_complex = f"{filter_v}{''.join(v_pads)}concat=n={n}:v=1[out]"
            map_args = ["-map", "[out]"]
            audio_args = ["-an"]

        meta_path = self._write_ffmetadata_file(seg_meta, stem)
        extra_args = []
        if meta_path is not None:
            inputs += ["-i", str(meta_path)]
            extra_args = ["-map_metadata", str(n)]

        result = subprocess.run(
            [ffmpeg, "-y"] + inputs + [
                "-filter_complex", filter_complex,
            ] + map_args + extra_args + [
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            ] + audio_args + [
                str(final_path),
            ],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg stitch failed:\n{result.stderr[-3000:]}")
        return final_path, seg_meta

    # ------------------------------------------------------------------ #
    # API helpers
    # ------------------------------------------------------------------ #

    def _clean_temp_dir(self):
        removed = 0
        for f in self._temp_dir.iterdir():
            if f.is_file():
                f.unlink()
                removed += 1
        if removed:
            self._log(f"Cleared {removed} file(s) from temp folder.")

    def _queue_prompt(self, workflow: dict) -> str:
        resp = requests.post(
            f"{self._url}/prompt",
            json={"prompt": workflow, "client_id": self._client_id, "extra_data": {"extra_pnginfo": {}}},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["prompt_id"]

    def _handle_execution_error(self, ex_msg: str, seg: int):
        """Shared error handling: 'already exists' means the outputs are on the
        server from a prior run — recover by downloading instead of failing."""
        if "already exists" in ex_msg or "Error opening output file" in ex_msg:
            self._log(f"[Segment {seg}/{self._total_segs}] Output exists on server, downloading...")
            self._already_exists_seg = seg
            return
        raise RuntimeError(f"ComfyUI execution error: {ex_msg}")

    def _history_done(self, prompt_id: str, seg: int) -> bool:
        """Check /history once. True if the prompt finished (or recovered via
        the already-exists path); raises on a real execution error."""
        h = requests.get(f"{self._url}/history/{prompt_id}", timeout=10).json()
        if prompt_id not in h:
            return False
        status = h[prompt_id].get("status", {})
        if status.get("completed", False):
            return True
        msgs = status.get("messages", [])
        if msgs and msgs[-1][0] == "execution_error":
            self._handle_execution_error(msgs[-1][1].get("exception_message", ""), seg)
            return True  # already-exists recovery
        return False

    def _wait_until_done(self, prompt_id: str, seg: int, workflow: dict | None = None):
        """Wait for the prompt via websocket for live step progress; fall back
        to HTTP polling if the websocket can't connect or drops."""
        try:
            import websocket
        except ImportError:
            self._poll_until_done(prompt_id, seg)
            return

        ws_url = self._url.replace("https://", "wss://").replace("http://", "ws://")
        try:
            ws = websocket.create_connection(f"{ws_url}/ws?clientId={self._client_id}", timeout=20)
        except Exception as e:
            self._log(f"[Segment {seg}/{self._total_segs}] Websocket unavailable ({type(e).__name__}) — using polling")
            self._poll_until_done(prompt_id, seg)
            return

        start = time.time()
        last_minute_logged = 0
        logged_node = None
        pending_phase = None  # label of the post-sampler phase currently running, if any
        try:
            while not self._cancelled:
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    # Quiet stretch (model load, VAE decode) — confirm liveness
                    # via history so a missed finish can't hang us forever.
                    try:
                        if self._history_done(prompt_id, seg):
                            return
                    except requests.RequestException:
                        pass
                    minute = int(time.time() - start) // 60
                    if minute > last_minute_logged:
                        last_minute_logged = minute
                        self._log(f"[Segment {seg}/{self._total_segs}] Running... ({minute}m)")
                    continue
                except Exception:
                    self._log(f"[Segment {seg}/{self._total_segs}] Websocket dropped — using polling")
                    self._poll_until_done(prompt_id, seg)
                    return

                if isinstance(msg, bytes):
                    continue  # binary preview frames
                try:
                    payload = json.loads(msg)
                except ValueError:
                    continue
                mtype = payload.get("type")
                data = payload.get("data", {})
                if mtype == "progress":
                    self.step_progress.emit(seg, int(data.get("value", 0)), int(data.get("max", 1)))
                    minute = int(time.time() - start) // 60
                    if minute > last_minute_logged:
                        last_minute_logged = minute
                        self._log(f"[Segment {seg}/{self._total_segs}] Running... ({minute}m)")
                elif mtype == "executing" and data.get("prompt_id") == prompt_id:
                    node_id = data.get("node")
                    if node_id is None:
                        if pending_phase:
                            self.phase_progress.emit(seg)  # last phase (e.g. save) just finished
                        return  # prompt finished
                    if workflow and node_id != logged_node:
                        logged_node = node_id
                        class_type = workflow.get(node_id, {}).get("class_type", "")
                        label = self._STATUS_NODE_LABELS.get(class_type)
                        if label:
                            self._log(f"[Segment {seg}/{self._total_segs}] {label}")
                            if pending_phase:
                                # entering a new phase means the previous one
                                # (e.g. decode) actually finished, not just started
                                self.phase_progress.emit(seg)
                            pending_phase = label
                elif mtype == "execution_error" and data.get("prompt_id") == prompt_id:
                    self._handle_execution_error(data.get("exception_message", ""), seg)
                    return  # already-exists recovery
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _poll_until_done(self, prompt_id: str, seg: int):
        queue_url = f"{self._url}/queue"
        elapsed = 0
        while not self._cancelled:
            time.sleep(3)
            elapsed += 3
            try:
                q = requests.get(queue_url, timeout=10).json()
                running = [item[1] for item in q.get("queue_running", [])]
                pending = [item[1] for item in q.get("queue_pending", [])]
                if prompt_id in running:
                    if elapsed % 60 == 0:
                        self._log(f"[Segment {seg}/{self._total_segs}] Running... ({elapsed // 60}m)")
                    continue
                if prompt_id in pending:
                    if elapsed % 60 == 0:
                        self._log(f"[Segment {seg}/{self._total_segs}] Queued... ({elapsed // 60}m)")
                    continue
                if self._history_done(prompt_id, seg):
                    return
                if elapsed % 60 == 0:
                    self._log(f"[Segment {seg}/{self._total_segs}] Waiting for history... ({elapsed // 60}m)")
            except requests.RequestException as e:
                self._log(f"[Segment {seg}/{self._total_segs}] Poll error: {e}")

    # ------------------------------------------------------------------ #
    # Workflow loading (mirrors ChainWorker)
    # ------------------------------------------------------------------ #

    def _batch_chain_dir(self) -> Path:
        workflow_dir = Path(self._config["workflow_dir"])
        folder = self._config.get("active_chain_folder", "")
        return workflow_dir / folder if folder else workflow_dir

    def _load_workflow(self, wf: dict) -> dict:
        path = self._batch_chain_dir() / wf["json_file"]
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _build_effective_workflows(self) -> list[dict]:
        template = self._config.get("workflows", [])
        chain_dir = self._batch_chain_dir()
        files = sorted(chain_dir.glob("workflow_segment_*_batch.json"))
        if not files:
            return template
        video_entries = [t for t in template if t.get("input_type") in ("video", "frame")]
        fallback = video_entries[-1] if video_entries else (template[-1] if template else {})
        segs = []
        for i, f in enumerate(files, 1):
            tmpl = template[i - 1] if i - 1 < len(template) else fallback
            segs.append({
                "segment": i,
                "json_file": f.name,
                "input_node_id": tmpl.get("input_node_id", ""),
                "input_type": tmpl.get("input_type", "frame"),
            })
        return segs

    def _trim_log(self, log_path: Path, keep: int):
        delimiter = "=== New batch run started ==="
        if not log_path.exists():
            return
        text = log_path.read_text(encoding='utf-8')
        parts = text.split(delimiter)
        # parts[0] is anything before the first delimiter (empty or header noise)
        batches = [p for p in parts[1:] if p.strip()]
        if len(batches) >= keep:
            trimmed = delimiter.join([""] + batches[-(keep - 1):])
            log_path.write_text(trimmed.lstrip('\n'), encoding='utf-8')

    def _fmt(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}m {s:02d}s"
