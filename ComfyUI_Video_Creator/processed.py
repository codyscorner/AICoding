"""Which source files already have a finished video in the Library — per workflow.

A source counts as processed for a workflow when that workflow's prompt-history
entry records a result made from it (``sources`` per result file, or the
entry-level ``source`` that pre-2.6.1 sidecars wrote) AND that result file is
still sitting in the workflow's Library folder — so deleting a bad generation
puts its source back in the picker. Names are compared case-insensitively, as
Windows does.
"""

import json
from pathlib import Path

from workflow_folders import history_file, library_dir_for, video_names

# history file -> (mtime, {result name -> source name})
_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def _result_sources(hist: Path) -> dict[str, str]:
    try:
        mtime = hist.stat().st_mtime
    except OSError:
        return {}
    cached = _CACHE.get(str(hist))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    pairs: dict[str, str] = {}
    try:
        with open(hist, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        per_file = entry.get("sources") or {}
        for result in entry.get("results") or []:
            source = per_file.get(result) or entry.get("source") or ""
            if source:
                pairs[str(result).lower()] = str(source).lower()
    _CACHE[str(hist)] = (mtime, pairs)
    return pairs


def processed_sources(workflow_dir: str, library_root: str, workflow_rel: str) -> set[str]:
    """Lower-cased file names of every source that ONE workflow has already
    turned into a video that is still in the Library.

    Only that workflow's own history file counts, so an image finished by
    workflow 1 stays visible while workflow 2 is selected, until workflow 2 has
    made its own video from it. The video must sit in the workflow's own Library
    folder, or loose in the Library root (how videos were saved before there
    were per-workflow folders)."""
    wf_dir = (workflow_dir or "").strip()
    root = (library_root or "").strip()
    if not (wf_dir and root and (workflow_rel or "").strip()):
        return set()
    hist = history_file(wf_dir, workflow_rel)
    if not hist.is_file():
        return set()
    present = video_names(library_dir_for(root, workflow_rel)) | video_names(root)
    if not present:
        return set()
    return {source for result, source in _result_sources(hist).items() if result in present}
