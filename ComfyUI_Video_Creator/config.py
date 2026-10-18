"""Portable config for ComfyUI Video Creator.

The settings file lives next to the EXE (or next to main.py when run from
source) — never in %APPDATA% — because every VibeCoded app is a portable
single-file EXE that must work from a thumb drive.
"""

import json
import sys
from pathlib import Path
from typing import Any

CONFIG_NAME = "video_creator_config.json"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


class ConfigManager:
    DEFAULT: dict[str, Any] = {
        # ComfyUI server
        "mode": "local",                       # local | runpod
        "comfyui_url": "http://127.0.0.1:8000",
        "runpod_url": "",
        # RunPod pod control (see RUNPOD_POD_CONTROL_PLAN.md). The API key is
        # NOT here — it lives in api_keys.json so this file stays safe to copy.
        "runpod_gpu_order": [],                # GPU models, best first; outranks runpod_pod_order
        "runpod_pod_order": [],                # pod IDs, best first within a GPU model
        "runpod_auto_prompt": True,            # offer to start a pod on launch
        "runpod_auto_stop_on_exit": True,      # ask to stop the connected pod when quitting
        "runpod_spend_limit": 0.0,             # USD per pod run; 0 = no limit
        "runpod_idle_stop_min": 0,             # stop the pod this long after the queue finishes; 0 = off
        "runpod_spend_warn_fraction": 0.8,
        # "Keep trying" when every pod is busy
        "runpod_retry_interval_min": 10,       # minutes between sweeps of the pod list
        "runpod_retry_window_min": 120,        # give up after this long
        "alert_sound_path": "",                # played when a pod is found, and when giving up
        "alert_sound_enabled": True,
        # Folders
        "image_dir": "",
        "video_dir": "",
        "workflow_dir": "P:/AI/ComfyLocal/ComfyUI_windows_portable/Workflow_API",
        "output_dir": "",
        "library_dir": "",                     # blank = output_dir
        "output_per_workflow": True,           # save each workflow's videos in <output>/<workflow path>/
        "library_follow": True,                # Library tab shows the workflow selected on the active tab
        "archive_dir": "",                     # where the Library's Archive button moves videos to
        "library_sort": "Newest First",
        "loras_dir": "P:/AI/ComfyLocal/ComfyUI_windows_portable/ComfyUI/models/loras",
        # Model check & sync against the RunPod volume (model_sync.py). Before a
        # RunPod run every model file the workflow names is looked for locally and
        # on the volume; whatever is missing on one side is copied from the other.
        "model_check_enabled": True,
        "model_sync_download": False,          # also pull pod-only files down to this PC (off: a pod run only needs them on the pod)
        "model_sync_download": False,          # also pull pod-only files down to this PC (off: a pod run only needs them on the pod)
        "models_dir": "",                      # ComfyUI/models root; blank = parent of loras_dir
        "s3_profile_name": "runpod-s3",        # profile in %USERPROFILE%\.aws\credentials
        "s3_region": "",
        "s3_endpoint_url": "",
        "s3_bucket_name": "",
        "s3_models_prefix": "runpod-slim/ComfyUI/models/",
        # remote_cleanup.py: after a RunPod result is downloaded and its size
        # verified, delete it from the pod volume through S3. Off by default.
        "s3_delete_outputs_after_download": False,
        "s3_output_prefix": "runpod-slim/ComfyUI/output/",
        # Staging for workflows that read a whole folder (LoadImageListFromDir)
        "staging_dir_local": "",
        "runpod_input_dir": "/workspace/runpod-slim/ComfyUI/input",
        # Tools
        "ffmpeg_path": "",
        # Remembered UI state
        "image_workflow": "",
        "video_workflow": "",
        "text_workflow": "",
        # "✚ New" copies these (relative to workflow_dir) with prompts + LoRAs cleared
        "image_blank_template": "",
        "text_blank_template": "",
        "text_output_name": "",                # Text → Video: base name for the saved clip (blank = T2V)
        "image_sort": "Name A→Z",
        "video_sort": "Newest First",
        "video_input_mode": "auto",            # auto | last_frame | upload_video
        "extend_stitch": True,
        "extend_hide_clips": True,             # Extend list hides a short clip once its complete video exists
        "seed_mode": "random",                 # random | fixed
        "seed_value": 0,
        "prompt_font_size": 10,
        "panel_split_image": [],
        "panel_split_video": [],
        "panel_split_text": [],
        # AI prompt rewriter (local LLM via LM Studio's OpenAI-compatible API)
        "rewriter_base_url": "http://127.0.0.1:1970/v1",
        "rewriter_model": "openai/gpt-oss-20b",
    }

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._data = self._load()

    def _load(self) -> dict:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return {**self.DEFAULT, **json.load(f)}
            except (json.JSONDecodeError, OSError):
                pass
        return dict(self.DEFAULT)

    def save(self) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4)
            return True
        except OSError:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_all(self) -> dict:
        return dict(self._data)

    # Convenience -------------------------------------------------------
    def server_url(self) -> str:
        if self.get("mode", "local") == "runpod":
            return (self.get("runpod_url", "") or "").strip().rstrip("/")
        return (self.get("comfyui_url", "") or "").strip().rstrip("/")

    def is_runpod(self) -> bool:
        return self.get("mode", "local") == "runpod"
