"""Settings live next to the EXE (portable app) — never in %APPDATA%."""

import json
import sys
from pathlib import Path

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH = BASE_DIR / "gpu_monitor_config.json"

DEFAULTS = {
    "geometry": None,       # [x, y, w, h]
    "history_s": 300,       # graph window in seconds
    "clock_cap_on": False,
    "clock_cap_mhz": None,  # None = top of the supported list
}


def load():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass
