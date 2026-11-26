"""NVML access: live sampling (no admin needed) and the privileged setters.

Reading is free for any user. Setting the power limit or locking clocks needs
an elevated process, so the setters live in apply_changes() and are only ever
called from the elevated `--apply` run (see apply_cli.py).
"""

import time

import pynvml as nv

# nvmlClocksEventReasons bit -> (label, severity). Severity: 0 info, 1 throttling, 2 hardware problem.
REASON_BITS = [
    (0x8, "HW slowdown", 2),
    (0x40, "HW thermal", 2),
    (0x80, "HW power brake", 2),
    (0x20, "Thermal", 1),
    (0x4, "Power cap", 1),
    (0x10, "Sync boost", 0),
    (0x2, "App clocks", 0),
    (0x100, "Display clock", 0),
]
REASON_IDLE = 0x1


def _try(fn, *args):
    try:
        return fn(*args)
    except nv.NVMLError:
        return None


def describe_reasons(mask):
    """Return (text, severity) for a clocks-event-reason bitmask."""
    if not mask:
        return "None", 0
    names, worst = [], 0
    for bit, label, sev in REASON_BITS:
        if mask & bit:
            names.append(label)
            worst = max(worst, sev)
    if not names:
        return ("Idle" if mask & REASON_IDLE else "None"), 0
    return ", ".join(names), worst


class GpuReader:
    def __init__(self, index=0):
        nv.nvmlInit()
        self.h = nv.nvmlDeviceGetHandleByIndex(index)
        name = nv.nvmlDeviceGetName(self.h)
        self.name = name.decode() if isinstance(name, bytes) else name
        drv = nv.nvmlSystemGetDriverVersion()
        self.driver = drv.decode() if isinstance(drv, bytes) else drv
        lo, hi = nv.nvmlDeviceGetPowerManagementLimitConstraints(self.h)
        self.limit_min_w, self.limit_max_w = lo / 1000.0, hi / 1000.0
        self.limit_default_w = nv.nvmlDeviceGetPowerManagementDefaultLimit(self.h) / 1000.0
        self.vram_total_mb = nv.nvmlDeviceGetMemoryInfo(self.h).total / 1048576.0
        self.sm_max_mhz = _try(nv.nvmlDeviceGetMaxClockInfo, self.h, nv.NVML_CLOCK_SM) or 2100
        self.supported_clocks = supported_graphics_clocks(self.h)

    def sample(self):
        h = self.h
        mem = _try(nv.nvmlDeviceGetMemoryInfo, h)
        util = _try(nv.nvmlDeviceGetUtilizationRates, h)
        power = _try(nv.nvmlDeviceGetPowerUsage, h)
        limit = _try(nv.nvmlDeviceGetPowerManagementLimit, h)
        return {
            "t": time.time(),
            "power_w": None if power is None else power / 1000.0,
            "limit_w": None if limit is None else limit / 1000.0,
            "temp_c": _try(nv.nvmlDeviceGetTemperature, h, nv.NVML_TEMPERATURE_GPU),
            "fan_pct": _try(nv.nvmlDeviceGetFanSpeed, h),
            "util_gpu": None if util is None else util.gpu,
            "util_mem": None if util is None else util.memory,
            "vram_used_mb": None if mem is None else mem.used / 1048576.0,
            "sm_mhz": _try(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_SM),
            "mem_mhz": _try(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_MEM),
            "reasons": _try(nv.nvmlDeviceGetCurrentClocksEventReasons, h) or 0,
        }

    def close(self):
        _try(nv.nvmlShutdown)


def supported_graphics_clocks(h):
    """Ascending list of core clocks the card can be locked to."""
    mem_clocks = []
    cur = _try(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_MEM)
    if cur:
        mem_clocks.append(cur)
    mem_clocks += _try(nv.nvmlDeviceGetSupportedMemoryClocks, h) or []
    for mc in mem_clocks:
        clocks = _try(nv.nvmlDeviceGetSupportedGraphicsClocks, h, mc)
        if clocks:
            return sorted(set(clocks))
    return []


def apply_changes(power_w=None, clock_max=None, reset_clocks=False):
    """Privileged: set the power limit and/or lock/unlock core clocks.

    Returns {"ok": bool, "messages": [str]}. Every step is attempted and reported
    separately so a failure in one does not hide the other.
    """
    messages, ok = [], True
    nv.nvmlInit()
    try:
        h = nv.nvmlDeviceGetHandleByIndex(0)
        if power_w is not None:
            lo, hi = nv.nvmlDeviceGetPowerManagementLimitConstraints(h)
            mw = int(max(lo, min(hi, round(power_w * 1000))))
            try:
                nv.nvmlDeviceSetPowerManagementLimit(h, mw)
                messages.append(f"Power limit set to {mw / 1000:.0f} W")
            except nv.NVMLError as e:
                ok = False
                messages.append(f"Power limit failed: {e}")
        if clock_max is not None:
            floor = min(supported_graphics_clocks(h) or [210])
            try:
                nv.nvmlDeviceSetGpuLockedClocks(h, floor, int(clock_max))
                messages.append(f"Core clock capped at {int(clock_max)} MHz")
            except nv.NVMLError as e:
                ok = False
                messages.append(f"Clock cap failed: {e}")
        elif reset_clocks:
            try:
                nv.nvmlDeviceResetGpuLockedClocks(h)
                messages.append("Core clock cap removed")
            except nv.NVMLError as e:
                ok = False
                messages.append(f"Clock reset failed: {e}")
    finally:
        _try(nv.nvmlShutdown)
    return {"ok": ok, "messages": messages}
