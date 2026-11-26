"""Shared helpers for the planner / copier tests."""
import os
from datetime import datetime

from copy_plan import build_plan
from file_operations import FileCopier, FileScanner, FileValidator
from folder_organization import FolderStructure

# Local noon on 15 June 2025: the year/month folder is 2025\06 in any time zone,
# and +/- a few days stays inside June.
JUNE = datetime(2025, 6, 15, 12, 0, 0).timestamp()
DAY = 86400
HOUR = 3600
MASK = "*.png, *.jpg"


def write(path, content: bytes = b"x", mtime: float = JUNE) -> str:
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    os.utime(path, (mtime, mtime))
    return path


def scan(root, mask: str = MASK):
    patterns = FileValidator.validate_file_mask(mask)
    return FileScanner.get_files_with_patterns(
        os.fspath(root), patterns, recursive=True, sort_order="directory", include_mtime=True)


def make_plan(src: str, dest: str, **opts):
    opts.setdefault("folder_structure", FolderStructure.BY_YEAR_MONTH)
    return build_plan(scan(src), dest, **opts)


def by_rel(plan, src: str) -> dict:
    """{path relative to the source root: PlanItem}"""
    return {os.path.relpath(i.source_path, src): i for i in plan.items}


def run_copy(src: str, dest: str, plan=None, *, incremental=True, number_duplicates=True,
             preserve=False, structure=FolderStructure.BY_YEAR_MONTH, **copier_kw):
    copier = FileCopier(folder_structure=structure, number_duplicates=number_duplicates,
                        incremental=incremental, **copier_kw)
    results = copier.copy_files(src, dest, MASK, preserve_structure=preserve,
                                recursive=True, plan=plan)
    return copier, results


def tree(root: str) -> dict:
    """{relative path (lower-case): file bytes} for everything under root."""
    out = {}
    for r, _d, files in os.walk(root):
        for f in files:
            p = os.path.join(r, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).lower()] = fh.read()
    return out


def leftovers(root: str) -> list:
    """Temp files the copier should never leave behind."""
    return [os.path.join(r, f) for r, _d, files in os.walk(root) for f in files if f.endswith(".partial")]
