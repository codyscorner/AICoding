# GPU Monitor

Live monitoring and tuning for an NVIDIA RTX 3090 (any single NVIDIA GPU) while doing AI work.
PyQt6 + pyqtgraph + NVML (`nvidia-ml-py`), navy theme, portable single-file EXE.

## What it shows
- **Power** draw against the current limit (graph has a dashed limit line)
- **Temperature**, **fan %**, **GPU load** and memory-bus load
- **VRAM** used / total (watch the peak — ComfyUI spikes during VAE decode)
- **Core clock** and MHz-per-watt
- **Throttle reason** (power cap, thermal, HW slowdown…) — the fastest answer to "why did it slow down"

## What it controls
- **Power limit** — slider over the range the card reports (3090: 100–450 W), plus Stock / Efficient / Quiet presets.
- **Flat voltage ceiling** — caps the max core clock. The GPU never boosts past it, so voltage never climbs above
  that point on the V/F curve. This is the same effect as a flat curve in MSI Afterburner.
- **Restore stock** — stock power limit, clocks unlocked.

Changes need administrator rights, so **Apply** shows the Windows permission prompt. The app itself never runs elevated.
Settings are not persistent: a reboot or driver reset returns the card to stock.

## Limits worth knowing
- NVML (NVIDIA's documented API) reports clock offsets as *Not Supported* on this card and cannot read or set
  **voltage**. Editing the actual V/F curve (as Afterburner does through NVAPI) is not done by this app.
- **MSI Afterburner can overwrite these settings** when it applies a profile (e.g. at startup).
- Per-process VRAM, PCIe link, memory clock and CSV logging are not in v1.0.0.

## Run
`run.bat` (dev) or build with `build.bat` → `P:\Apps\AICoded\GPU Monitor\GPU_Monitor.exe`.
Build with the repo `.venv` (it has PyQt6, pyqtgraph, nvidia-ml-py, PyInstaller).

## Recent Changes
See [CHANGELOG.md](CHANGELOG.md).
