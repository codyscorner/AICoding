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
        "mode": "local",
        "comfyui_url": "http://127.0.0.1:8000",
        "runpod_url": "",
        "input_dir": "",
        "output_dir": "",
        "workflow_path": "",
        "prompts_file": "",
        "skip_existing": True,
        # Main character: one fixed photo sent as the workflow's second image on
        # every run, while the folder images rotate through the first.
        "main_character_enabled": False,
        "main_character_path": "",
        # "reference" = 2nd Load Image; "stitch_left"/"stitch_right" = joined to the
        # folder image as ONE image (for one-image workflows such as Flux2 Dev)
        "main_character_mode": "stitch_left",
        # Aspect ratio of the generated image: "auto" (follow the input image) or a
        # key of worker.OUTPUT_SHAPES such as "portrait_2_3" / "landscape_3_2"
        "output_shape": "auto",
        # Remembered between sessions (the AI scene generator and the main window)
        "scene_gen_scenario": "",
        "scene_gen_idea": "",
        "scene_gen_count": 6,
        "prompt_editor_size": None,
        "prompt_order": "evens_odds",
        "auto_batch_size": 4,
        "window_geometry": "",
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
        # batch finished
        "alert_sound_path": "",
        "alert_sound_enabled": True,
        # Model check & sync with the pod volume (copied from Video Creator,
        # see model_sync.py). Blank S3 fields = the check stays off.
        "model_check_enabled": True,
        "model_sync_download": False,          # also pull pod-only files down to this PC (off: a pod run only needs them on the pod)
        "models_dir": "",                      # local ComfyUI/models root
        "s3_profile_name": "runpod-s3",
        "s3_region": "",
        "s3_endpoint_url": "",
        "s3_bucket_name": "",
        "s3_models_prefix": "runpod-slim/ComfyUI/models/",
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
        return self.DEFAULT.copy()

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
        return self._data.copy()

    # Convenience (PodControl asks these) ------------------------------
    def server_url(self) -> str:
        if self.is_runpod():
            return (self.get("runpod_url", "") or "").strip().rstrip("/")
        return (self.get("comfyui_url", "") or "").strip().rstrip("/")

    def is_runpod(self) -> bool:
        return self.get("mode", "local") == "runpod"
