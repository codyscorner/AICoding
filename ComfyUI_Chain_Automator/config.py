import json
import sys
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    """Folder next to the EXE (or main.py from source) — every portable file
    this app owns (config, api_keys.json, runpod_session.json, pod log) lives here."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


class ConfigManager:
    DEFAULT = {
        "comfyui_url": "http://127.0.0.1:8188",
        "input_dir": "P:/AI/ComfyLocal/ComfyUI_windows_portable/ComfyUI/input",
        "output_base_dir": "P:/AI/ComfyLocal/ComfyUI_windows_portable/ComfyUI/output/video/Merge",
        "workflow_dir": "P:/AI/ComfyLocal/ComfyUI_windows_portable/Workflow_API",
        "workflows": [],
        "anthropic_api_key": "",
        "lora_check_enabled": True,
        "s3_profile_name": "runpod-s3",
        "s3_region": "",
        "s3_endpoint_url": "",
        "s3_bucket_name": "",
        "s3_loras_prefix": "runpod-slim/ComfyUI/models/loras/",
        # remote_cleanup.py: after a RunPod segment video is downloaded and its
        # size verified, delete it from the pod volume through S3. Off by default.
        "s3_delete_outputs_after_download": False,
        "s3_output_prefix": "runpod-slim/ComfyUI/output/",
        # RunPod pod control (copied from ComfyUI Video Creator). The API key is
        # NOT here — it lives in api_keys.json next to the EXE (see runpod_api.py).
        "runpod_gpu_order": [],                # GPU models, best first; outranks runpod_pod_order
        "runpod_pod_order": [],                # pod IDs, best first within a GPU model
        "runpod_auto_prompt": True,            # offer to start a pod on launch
        "runpod_auto_stop_on_exit": True,      # ask to stop the connected pod when quitting
        "runpod_spend_limit": 0.0,             # USD per pod run; 0 = no limit
        "runpod_idle_stop_min": 0,             # stop the pod this long after the last batch; 0 = off
        "runpod_spend_warn_fraction": 0.8,
        # "Keep trying" when every pod is busy
        "runpod_retry_interval_min": 10,       # minutes between sweeps of the pod list
        "runpod_retry_window_min": 120,        # give up after this long
        # One sound for everything worth walking back for: pod found, gave up,
        # batch finished (the old completion_sound_* keys are migrated into these)
        "alert_sound_path": "",
        "alert_sound_enabled": True,
    }

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._data = self._load()

    def _load(self) -> dict:
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return self._migrate({**self.DEFAULT, **json.load(f)})
            except (json.JSONDecodeError, OSError):
                pass
        return self.DEFAULT.copy()

    @staticmethod
    def _migrate(data: dict) -> dict:
        """v3.11.0: the batch completion sound and the pod alerts share one
        sound. Carry an existing completion_sound_* setting over once, then
        drop the old keys so they can't drift apart again."""
        if "completion_sound_path" in data or "completion_sound_enabled" in data:
            old_path = (data.pop("completion_sound_path", "") or "").strip()
            old_on = bool(data.pop("completion_sound_enabled", False))
            if old_path and not (data.get("alert_sound_path") or "").strip():
                data["alert_sound_path"] = old_path
                data["alert_sound_enabled"] = old_on
        return data

    def save(self) -> bool:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=4)
            return True
        except OSError:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_all(self) -> dict:
        return self._data.copy()

    # Convenience (PodControl asks these) ------------------------------
    def server_url(self) -> str:
        if self.is_runpod():
            return (self.get("runpod_url", "") or "").strip().rstrip("/")
        return (self.get("comfyui_url", "") or "").strip().rstrip("/")

    def is_runpod(self) -> bool:
        return self.get("mode", "local") == "runpod"
