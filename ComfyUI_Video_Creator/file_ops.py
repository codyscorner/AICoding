"""Deleting media from inside the app.

Files go to the Recycle Bin, not into thin air — a bad generation is deleted
in a hurry and the Bin is the only way back. A permanent delete is the
fallback for when the shell call can't do it (a network share, a full Bin).
"""

from __future__ import annotations

import ctypes
import shutil
import time
import zlib
from ctypes import wintypes
from pathlib import Path

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def recycle(paths: list[Path]) -> bool:
    """Send files to the Recycle Bin in one shell operation."""
    files = [p for p in paths if p.exists()]
    if not files:
        return True
    try:
        buf = "\0".join(str(p.resolve()) for p in files) + "\0\0"
        op = _SHFILEOPSTRUCTW(
            None, FO_DELETE, buf, None,
            FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
            False, None, None,
        )
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return rc == 0 and not op.fAnyOperationsAborted
    except Exception:  # noqa: BLE001
        return False


# A player that just released its file may hold the handle a beat longer
# while the media backend winds down: retry briefly before giving up.
LOCK_RETRIES = 8
LOCK_WAIT = 0.15


def delete_paths(paths: list[Path]) -> tuple[int, list[str], bool]:
    """Delete `paths`, Recycle Bin first. Returns (deleted, errors, recycled)."""
    paths = [Path(p) for p in paths]
    recycled = True
    errors: list[str] = []
    for attempt in range(LOCK_RETRIES):
        remaining = [p for p in paths if p.exists()]
        if not remaining:
            break
        recycled = recycle(remaining) and recycled
        errors = []
        locked = False
        for p in remaining:
            if not p.exists():
                continue
            try:
                p.unlink()
            except PermissionError as e:
                locked = True
                errors.append(f"{p.name}: {e}")
            except OSError as e:
                errors.append(f"{p.name}: {e}")
        if not locked or attempt == LOCK_RETRIES - 1:
            break
        time.sleep(LOCK_WAIT)
    deleted = sum(1 for p in paths if not p.exists())
    return deleted, errors, recycled and not errors


def archive_paths(paths: list[Path], archive_dir: Path) -> tuple[list[Path], list[str]]:
    """Move files into archive_dir, keeping names unique on a clash.

    Returns (moved dest paths, errors)."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    errors: list[str] = []
    for p in paths:
        dest = archive_dir / p.name
        if dest.exists() and dest != p:
            n = 2
            while (archive_dir / f"{p.stem}_{n}{p.suffix}").exists():
                n += 1
            dest = archive_dir / f"{p.stem}_{n}{p.suffix}"
        try:
            shutil.move(str(p), str(dest))
            moved.append(dest)
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    return moved, errors


def browse_start(folder: str) -> str:
    """Folder a Browse dialog should open in for `folder`.

    A path that does not exist yet (a workflow with no runs) is created first;
    if that fails (drive gone, no permission) walk up to the nearest folder
    that does exist. Home only when nothing on the path is reachable."""
    if folder:
        p = Path(folder)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        while not p.is_dir() and p.parent != p:
            p = p.parent
        if p.is_dir():
            return str(p)
    return str(Path.home())


def thumbnail_caches(path: Path, root: Path | None = None) -> list[Path]:
    """Cached thumbnails belonging to `path`: `<stem>.jpg` for videos (plus the
    `<stem>_last.jpg` that v2.x cached), `<stem>_<crc of the path relative to
    root>.jpg` for images."""
    out: list[Path] = []
    folders = {path.parent / "thumbnails"}
    if root:
        folders.add(Path(root) / "thumbnails")
    for folder in folders:
        out += [folder / f"{path.stem}.jpg", folder / f"{path.stem}_last.jpg"]
        if root:
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                continue
            out.append(folder / f"{path.stem}_{zlib.crc32(rel.lower().encode()):08x}.jpg")
    return [p for p in out if p.exists()]
