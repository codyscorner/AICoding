"""Headless entry point for the elevated `--apply` run (no Qt is imported)."""

import argparse
import json


def main(argv):
    p = argparse.ArgumentParser(prog="GPU Monitor --apply")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--out", required=True)
    p.add_argument("--power-w", type=float)
    p.add_argument("--clock-max", type=int)
    p.add_argument("--clock-reset", action="store_true")
    a = p.parse_args(argv)

    try:
        from nvml_backend import apply_changes
        result = apply_changes(a.power_w, a.clock_max, a.clock_reset)
    except Exception as e:  # report anything, the parent only sees the JSON file
        result = {"ok": False, "messages": [f"Helper error: {e}"]}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0 if result["ok"] else 1
