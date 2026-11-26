"""Run the privileged NVML setters in a short-lived elevated copy of this app.

The monitor itself stays a normal-user process. Pressing Apply re-launches the
same EXE (or script) with `--apply ...` through the "runas" verb, which shows
the UAC prompt, waits for it to finish, then reads its JSON result file.
"""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0
ERROR_CANCELLED = 1223
WAIT_TIMEOUT_MS = 60000


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _launch_args(extra):
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(extra)
    script = str(Path(__file__).with_name("main.py"))
    return sys.executable, subprocess.list2cmdline([script, *extra])


def run_apply(power_w=None, clock_max=None, reset_clocks=False):
    """Show UAC, apply the changes, return {"ok", "messages", "cancelled"}."""
    fd, out_path = tempfile.mkstemp(prefix="gpumon_", suffix=".json")
    os.close(fd)
    args = ["--apply", "--out", out_path]
    if power_w is not None:
        args += ["--power-w", str(power_w)]
    if clock_max is not None:
        args += ["--clock-max", str(int(clock_max))]
    elif reset_clocks:
        args += ["--clock-reset"]

    exe, params = _launch_args(args)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = params
    info.nShow = SW_HIDE
    try:
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            cancelled = ctypes.GetLastError() == ERROR_CANCELLED
            msg = "Cancelled at the Windows permission prompt" if cancelled else "Could not start the elevated helper"
            return {"ok": False, "cancelled": cancelled, "messages": [msg]}
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, WAIT_TIMEOUT_MS)
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
        try:
            result = json.loads(Path(out_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ok": False, "cancelled": False, "messages": ["Elevated helper returned no result"]}
        result["cancelled"] = False
        return result
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass
