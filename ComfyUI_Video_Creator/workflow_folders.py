"""One Library folder per workflow.

A finished video is saved into ``<Output>/<workflow path without .json>/`` —
``Series 1/MiniMax_Makeout_On_Bed_Ext1.json`` becomes
``<Output>/Series 1/MiniMax_Makeout_On_Bed_Ext1/``. The workflow's whole
relative path is used (not just its file name) because the same file name
exists in more than one workflow subfolder.

This module also plans the one-time tidy-up of videos that were saved loose in
the Output folder before this existed: each workflow's prompt-history file
names the videos it made, so every loose video can be matched to its workflow.
Nothing here touches Qt.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from media_tools import VIDEO_EXTS
from workflow_tools import HISTORY_SUFFIX

THUMBS = "thumbnails"


def folder_rel(workflow_rel: str) -> str:
    """``Series 1/Foo.json`` -> ``Series 1/Foo`` (POSIX separators, no extension)."""
    rel = (workflow_rel or "").strip().replace("\\", "/").strip("/")
    if rel.lower().endswith(".json"):
        rel = rel[:-5]
    return rel


def workflow_rel_of(workflow_path: Path | None, workflow_dir: str) -> str:
    """The workflow's path relative to the Workflows folder, POSIX style.
    Falls back to the bare file name when it lives outside that folder."""
    if workflow_path is None:
        return ""
    try:
        return Path(workflow_path).relative_to(Path(workflow_dir)).as_posix()
    except (ValueError, TypeError):
        return Path(workflow_path).name


def library_dir_for(root: Path | str, workflow_rel: str) -> Path:
    """``root`` itself when there is no workflow, otherwise the workflow's own folder."""
    rel = folder_rel(workflow_rel)
    return Path(root) / rel if rel else Path(root)


def history_file(workflow_dir: Path | str, workflow_rel: str) -> Path:
    """The prompt-history sidecar of one workflow."""
    return Path(workflow_dir) / f"{folder_rel(workflow_rel)}{HISTORY_SUFFIX}"


def video_names(folder: Path | str) -> set[str]:
    """Lower-cased names of the videos directly inside ``folder``."""
    try:
        return {p.name.lower() for p in Path(folder).iterdir()
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS}
    except OSError:
        return set()


def library_workflow_folders(root: Path | str) -> list[str]:
    """Relative POSIX paths of every folder under ``root`` that holds videos
    directly, thumbnail caches excluded."""
    root = Path(root)
    out: list[str] = []
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() != THUMBS]       # a cache holds thousands of jpgs
        if Path(here) != root and any(Path(f).suffix.lower() in VIDEO_EXTS for f in files):
            out.append(Path(here).relative_to(root).as_posix())
    return sorted(out, key=str.lower)


# --------------------------------------------------------------------- #
# One-time tidy-up of loose videos
# --------------------------------------------------------------------- #

@dataclass
class SortPlan:
    root: Path
    moves: list[tuple[Path, Path]] = field(default_factory=list)   # (from, to)
    unmatched: list[Path] = field(default_factory=list)            # no history entry names it
    clashes: list[Path] = field(default_factory=list)              # the target name is already taken
    ambiguous: list[Path] = field(default_factory=list)            # two workflows both claim it

    def per_folder(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _src, dst in self.moves:
            key = dst.parent.relative_to(self.root).as_posix()
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[0].lower()))


def _results_in(hist: Path) -> set[str]:
    try:
        with open(hist, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    names: set[str] = set()
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict):
            names.update(str(r).lower() for r in entry.get("results") or [])
    return names


def plan_sort(workflow_dir: Path | str, root: Path | str) -> SortPlan:
    """Which of the videos lying directly in ``root`` belong to which workflow."""
    root = Path(root)
    plan = SortPlan(root)
    wf_root = Path(workflow_dir)
    owner: dict[str, str | None] = {}           # result name -> folder, None when two claim it
    if wf_root.is_dir():
        for hist in wf_root.rglob(f"*{HISTORY_SUFFIX}"):
            rel = hist.relative_to(wf_root).as_posix()
            folder = rel[: -len(HISTORY_SUFFIX)]
            for name in _results_in(hist):
                if name in owner and owner[name] != folder:
                    owner[name] = None
                else:
                    owner[name] = folder
    try:
        loose = sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS),
                       key=lambda p: p.name.lower())
    except OSError:
        loose = []
    for p in loose:
        key = p.name.lower()
        if key not in owner:
            plan.unmatched.append(p)
        elif owner[key] is None:
            plan.ambiguous.append(p)
        else:
            dst = root / owner[key] / p.name
            if dst.exists():
                plan.clashes.append(p)
            else:
                plan.moves.append((p, dst))
    return plan


def apply_sort(plan: SortPlan) -> tuple[int, list[str], Path | None]:
    """Do the moves, carrying each video's cached thumbnails along so nothing
    has to be re-extracted. Returns (moved, errors, manifest path)."""
    moved = 0
    errors: list[str] = []
    lines: list[str] = []
    for src, dst in plan.moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as e:
            errors.append(f"{src.name}: {e}")
            continue
        moved += 1
        lines.append(f"{src}  ->  {dst}")
        for suffix in (".jpg", "_last.jpg"):
            cache = src.parent / THUMBS / f"{src.stem}{suffix}"
            if not cache.exists():
                continue
            target = dst.parent / THUMBS / cache.name
            try:
                target.parent.mkdir(exist_ok=True)
                if not target.exists():
                    shutil.move(str(cache), str(target))
            except OSError:
                pass            # a thumbnail is re-made on demand; never fail the move for one
    manifest: Path | None = None
    if lines:
        manifest = plan.root / f"_sorted_into_workflow_folders_{datetime.now():%Y%m%d_%H%M%S}.txt"
        try:
            manifest.write_text(
                "Videos moved into per-workflow folders (one line per file: from -> to)\n\n"
                + "\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            manifest = None
    return moved, errors, manifest
