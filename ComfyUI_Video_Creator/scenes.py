"""Scene snippets — the swappable part of a prompt (Image / Video / Text tabs).

A prompt keeps ``{{tag}}`` markers (e.g. ``{{bedroom}}``). Each tag owns a list
of snippets (scene descriptions). Whichever snippet is *current* for a tag is
what the marker turns into when the prompt is sent, so only that one section of
the prompt changes between runs. After a run is queued the library can step to
the next snippet by itself, remembering which ones were already used.

Stored in ``scenes.json`` next to the config (portable, never %APPDATA%). One
instance per file is shared by all three tabs (:func:`get_library`) so a change
made on one tab shows on the others. Nothing here touches Qt.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from pathlib import Path

from scene_renderer import TAG_RE, find_tags, parse_scenarios, render

SCENES_NAME = "scenes.json"
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ORDER_SEQUENTIAL = "sequential"
ORDER_SHUFFLE = "shuffle"


class SceneLibrary:
    def __init__(self, path: Path):
        self._path = Path(path)
        self.order = ORDER_SEQUENTIAL
        self.auto_advance = True
        self._tags: dict[str, dict] = {}
        self._listeners: list = []
        self._load()

    # ---------------------------------------------------------------- disk
    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.order = ORDER_SHUFFLE if data.get("order") == ORDER_SHUFFLE else ORDER_SEQUENTIAL
        self.auto_advance = bool(data.get("auto_advance", True))
        for tag, t in (data.get("tags") or {}).items():
            if not isinstance(t, dict) or not TAG_NAME_RE.match(str(tag)):
                continue
            snippets = []
            for s in t.get("snippets") or []:
                if isinstance(s, dict) and str(s.get("text", "")).strip():
                    snippets.append({"id": str(s.get("id") or uuid.uuid4().hex[:10]),
                                     "name": str(s.get("name", "")), "text": str(s["text"])})
            ids = {s["id"] for s in snippets}
            cur = str(t.get("current", ""))
            self._tags[str(tag)] = {
                "snippets": snippets,
                "current": cur if cur in ids else (snippets[0]["id"] if snippets else ""),
                "used": [i for i in t.get("used") or [] if i in ids],
            }

    def save(self) -> bool:
        data = {"version": 1, "order": self.order, "auto_advance": self.auto_advance, "tags": self._tags}
        try:
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._path)
            return True
        except OSError:
            return False

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _changed(self) -> None:
        self.save()
        for fn in list(self._listeners):
            try:
                fn()
            except RuntimeError:        # a Qt widget that has been deleted
                self._listeners.remove(fn)

    # ---------------------------------------------------------------- tags
    def tags(self) -> list[str]:
        return list(self._tags)

    def has(self, tag: str) -> bool:
        return tag in self._tags

    def add_tag(self, tag: str) -> bool:
        tag = tag.strip()
        if not TAG_NAME_RE.match(tag) or tag in self._tags:
            return False
        self._tags[tag] = {"snippets": [], "current": "", "used": []}
        self._changed()
        return True

    def delete_tag(self, tag: str) -> None:
        if self._tags.pop(tag, None) is not None:
            self._changed()

    def set_options(self, order: str | None = None, auto_advance: bool | None = None) -> None:
        if order in (ORDER_SEQUENTIAL, ORDER_SHUFFLE):
            self.order = order
        if auto_advance is not None:
            self.auto_advance = bool(auto_advance)
        self._changed()

    # ------------------------------------------------------------ snippets
    def snippets(self, tag: str) -> list[dict]:
        return list(self._tags.get(tag, {}).get("snippets", []))

    def add_snippet(self, tag: str, name: str, text: str) -> str:
        t = self._tags[tag]
        sid = uuid.uuid4().hex[:10]
        t["snippets"].append({"id": sid, "name": name.strip(), "text": text.strip()})
        if not t["current"]:
            t["current"] = sid
        self._changed()
        return sid

    def update_snippet(self, tag: str, sid: str, name: str, text: str) -> None:
        for s in self._tags[tag]["snippets"]:
            if s["id"] == sid and (s["name"], s["text"]) != (name, text):
                s["name"], s["text"] = name, text
                self._changed()
                return

    def delete_snippet(self, tag: str, sid: str) -> None:
        t = self._tags[tag]
        idx = self.current_index(tag)
        t["snippets"] = [s for s in t["snippets"] if s["id"] != sid]
        t["used"] = [i for i in t["used"] if i != sid]
        if t["current"] == sid:
            n = len(t["snippets"])
            t["current"] = t["snippets"][min(max(idx, 0), n - 1)]["id"] if n else ""
        self._changed()

    # ------------------------------------------------------------- current
    def current_index(self, tag: str) -> int:
        t = self._tags.get(tag)
        if not t:
            return -1
        for i, s in enumerate(t["snippets"]):
            if s["id"] == t["current"]:
                return i
        return -1

    def set_current(self, tag: str, index: int) -> None:
        t = self._tags[tag]
        if 0 <= index < len(t["snippets"]) and t["snippets"][index]["id"] != t["current"]:
            t["current"] = t["snippets"][index]["id"]
            self._changed()

    def step(self, tag: str, delta: int) -> None:
        n = len(self._tags[tag]["snippets"])
        if n:
            self.set_current(tag, (max(self.current_index(tag), 0) + delta) % n)

    def is_used(self, tag: str, sid: str) -> bool:
        return sid in self._tags.get(tag, {}).get("used", ())

    def used_count(self, tag: str) -> int:
        return len(self._tags.get(tag, {}).get("used", ()))

    def reset_used(self, tag: str | None = None) -> None:
        for name, t in self._tags.items():
            if tag is None or name == tag:
                t["used"] = []
        self._changed()

    def advance(self, tags) -> list[str]:
        """Mark each tag's current snippet used, then move it to the next unused
        one (next in list, or a random unused one when shuffling). Returns the
        tags that had no unused snippet left — those stay where they are."""
        exhausted = []
        for tag in tags:
            t = self._tags.get(tag)
            if not t or not t["snippets"]:
                continue
            if t["current"] and t["current"] not in t["used"]:
                t["used"].append(t["current"])
            n = len(t["snippets"])
            start = max(self.current_index(tag), 0)
            unused = [i for i in range(n) if t["snippets"][i]["id"] not in t["used"]]
            if not unused:
                exhausted.append(tag)
            elif self.order == ORDER_SHUFFLE:
                t["current"] = t["snippets"][random.choice(unused)]["id"]
            else:
                nxt = next((i for i in range(start + 1, start + n + 1) if (i % n) in unused), unused[0])
                t["current"] = t["snippets"][nxt % n]["id"]
        self._changed()
        return exhausted

    # -------------------------------------------------------------- render
    def values(self) -> dict[str, str]:
        out = {}
        for tag, t in self._tags.items():
            i = self.current_index(tag)
            if i >= 0:
                out[tag] = t["snippets"][i]["text"]
        return out

    def render(self, body: str) -> tuple[str, list[str]]:
        """Body with every known tag replaced by its current snippet; the second
        value lists tags that stayed as ``{{tag}}`` because they have no snippet."""
        return render(body, self.values())

    # -------------------------------------------------------------- import
    def import_paste(self, tag: str, text: str) -> int:
        """Split a pasted AI reply into named snippets (see parse_scenarios)."""
        found = parse_scenarios(text)
        for s in found:
            t = self._tags[tag]
            sid = uuid.uuid4().hex[:10]
            t["snippets"].append({"id": sid, "name": s["name"], "text": s["text"]})
            if not t["current"]:
                t["current"] = sid
        if found:
            self._changed()
        return len(found)

    def import_placeholder(self, path: Path) -> tuple[int, int]:
        """Merge a Document Update Placeholder ``data.json``: its tags and
        snippets are added (a snippet whose text is already there is skipped).
        Returns (tags touched, snippets added)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        tags_touched = added = 0
        for tag, t in (data.get("tags") or {}).items():
            if not TAG_NAME_RE.match(str(tag)):
                continue
            mine = self._tags.setdefault(str(tag), {"snippets": [], "current": "", "used": []})
            have = {s["text"].strip() for s in mine["snippets"]}
            n0 = added
            for s in (t.get("snippets") or []) if isinstance(t, dict) else []:
                text = str(s.get("text", "")).strip() if isinstance(s, dict) else ""
                if text and text not in have:
                    have.add(text)
                    sid = uuid.uuid4().hex[:10]
                    mine["snippets"].append({"id": sid, "name": str(s.get("name", "")), "text": text})
                    if not mine["current"]:
                        mine["current"] = sid
                    added += 1
            tags_touched += 1 if added > n0 else 0
        if added:
            self._changed()
        return tags_touched, added


_libraries: dict[str, SceneLibrary] = {}


def get_library(path: Path) -> SceneLibrary:
    """The one shared library for this file (all tabs use the same object)."""
    key = str(Path(path).resolve())
    if key not in _libraries:
        _libraries[key] = SceneLibrary(path)
    return _libraries[key]


__all__ = ["SceneLibrary", "get_library", "find_tags", "TAG_RE", "SCENES_NAME",
           "ORDER_SEQUENTIAL", "ORDER_SHUFFLE", "TAG_NAME_RE"]
