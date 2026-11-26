# Changelog

## v1.0.2 — 2026-10-16
- App icon (emerald graphics card with a live pulse line + gauge on a dark tile, made with OpenArt Nano Banana 2;
  source render in `IconMaker/output/GPUMonitor*.png`). Embedded in the EXE for Explorer/shortcuts, bundled for
  the window title bar, and a dedicated AppUserModelID so the taskbar shows it.
- Build icon wiring lives in `build_exe.py` (`--icon`, `--add-data`) — no `.spec` file is needed.

## v1.0.1 — 2026-10-16
- Fix: the "Cap max core clock" checkbox had no visible box on the navy theme, so the clock slider looked locked.
  The checkbox now has a visible box, the slider is always usable, and moving it turns the cap on.
- Readout shows "(cap off)" while the cap is not enabled.

## v1.0.0 — 2026-10-16
- First release: live GPU monitor for an NVIDIA RTX 3090 (works with any single NVIDIA GPU).
- Tiles: power draw vs limit, temperature, fan, GPU load (+ memory-bus load), VRAM, core clock (+ MHz per watt).
- Four linked live graphs (power with limit line, temperature, load/VRAM %, core clock); 1 / 5 / 15 min window.
- Throttle indicator from the NVML clocks-event-reason flags (power cap, thermal, HW slowdown…).
- Power-limit slider (range read from the card, 5 W steps) with Stock / Efficient / Quiet presets.
- Core clock cap (`nvmlDeviceSetGpuLockedClocks`) as a flat-voltage-ceiling control.
- Restore stock button (stock power limit + clocks unlocked).
- Windows UAC prompt only when Apply is pressed; the monitor itself runs as a normal user.
- Config saved next to the EXE (`gpu_monitor_config.json`).
