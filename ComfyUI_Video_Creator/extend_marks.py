"""Keeping track of one set of extensions at a time (Video → Extend tab).

Two things clutter the Extend picker once a few extensions have run:

* the **sources you already extended** — remembered here by file name in
  ``extend_hidden.json`` next to the config, added automatically when an
  extension finishes and by the Hide button, removed by Unhide;
* the **short clips** — an extension with *Append* ticked saves both the new
  clip (``…_EXT_<stamp>``) and the complete video (``…_extended_<stamp>``). The
  clip is only a building block, so once its complete video exists beside it,
  it can be hidden. With *Append* off the clip is the only result and is
  never hidden.

Nothing here touches Qt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MARKS_NAME = "extend_hidden.json"

# run_worker.EXT_MARK, then the run stamp (and _N when a run saved several clips)
_CLIP_RE = re.compile(r"^(?P<stem>.*)_EXT_(?P<stamp>\d{8}_\d{6})(?:_\d+)?$", re.IGNORECASE)
_COMPLETE_RE = re.compile(r"^(?P<stem>.*)_extended_(?P<stamp>\d{8}_\d{6})$", re.IGNORECASE)


class ExtendMarks:
    """The set of source files hidden from the Extend picker, kept on disk."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._names: set[str] = set()
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._names = {str(n).lower() for n in data}
        except (OSError, ValueError):
            pass

    def hidden_names(self) -> set[str]:
        return set(self._names)

    def add(self, paths) -> int:
        """Hide these files; returns how many were new."""
        new = {Path(p).name.lower() for p in paths} - self._names
        if new:
            self._names |= new
            self._save()
        return len(new)

    def remove(self, paths) -> int:
        """Bring these files back; returns how many had been hidden."""
        gone = {Path(p).name.lower() for p in paths} & self._names
        if gone:
            self._names -= gone
            self._save()
        return len(gone)

    def clear(self) -> int:
        n = len(self._names)
        if n:
            self._names.clear()
            self._save()
        return n

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._names), f, indent=2)
        except OSError:
            pass            # the list is a convenience; never fail a run over it


def superseded_clips(paths) -> set[str]:
    """Paths (as strings) of short extension clips whose complete video from the
    same run is in the same folder."""
    complete: set[tuple[str, str]] = set()
    for p in paths:
        p = Path(p)
        m = _COMPLETE_RE.match(p.stem)
        if m:
            complete.add((str(p.parent).lower(), m.group("stamp")))
    out: set[str] = set()
    for p in paths:
        p = Path(p)
        m = _CLIP_RE.match(p.stem)
        if m and (str(p.parent).lower(), m.group("stamp")) in complete:
            out.add(str(p))
    return out
