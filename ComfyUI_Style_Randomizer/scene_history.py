"""History of the AI scene generator's Scenario + Idea pairs.

Every Generate click records the pair, so a Scenario/Idea that worked can be
found and reused later. Kept in scene_history.json next to the config (which is
next to the EXE - this app is portable), newest first.
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

FILE_NAME = "scene_history.json"
MAX_ENTRIES = 300


def history_path(config) -> Path:
    """scene_history.json beside the app's config file."""
    return Path(config.config_path).parent / FILE_NAME


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def load(path: Path) -> list[dict]:
    """All saved entries, newest first. A missing or damaged file is an empty history."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and (e.get("scenario") or e.get("idea"))]


def _save(path: Path, entries: list[dict]) -> None:
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries[:MAX_ENTRIES], indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)            # never leave a half-written history behind


def record(path: Path, scenario: str, idea: str, count: int = 0,
           provider: str = "", model: str = "", note: str = "") -> None:
    """Remember a Scenario + Idea pair. The same pair again moves to the top
    (with its use count bumped) instead of being listed twice."""
    scenario, idea = _clean(scenario), _clean(idea)
    if not (scenario or idea):
        return
    entries = load(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for e in entries:
        if e.get("scenario") == scenario and e.get("idea") == idea:
            entries.remove(e)
            e.update(time=now, count=count, provider=provider, model=model,
                     uses=int(e.get("uses", 1)) + 1)
            if note:
                e["note"] = note
            entries.insert(0, e)
            break
    else:
        entries.insert(0, {
            "id": uuid.uuid4().hex[:8], "time": now, "scenario": scenario, "idea": idea,
            "count": count, "provider": provider, "model": model, "uses": 1, "note": note,
        })
    _save(path, entries)


def delete(path: Path, entry_id: str) -> None:
    _save(path, [e for e in load(path) if e.get("id") != entry_id])


def delete_scenario(path: Path, scenario: str) -> int:
    """Remove a Scenario together with every Idea tied to it. Returns how many entries went."""
    entries = load(path)
    keep = [e for e in entries if e.get("scenario", "") != scenario]
    _save(path, keep)
    return len(entries) - len(keep)


def group_by_scenario(entries: list[dict]) -> list[dict]:
    """Tie the Ideas to their Scenario. Entries are one Scenario + Idea pair each
    (newest first); this gathers all pairs sharing a Scenario into one group:
    {"scenario", "note", "time", "uses", "entries": [newest idea first]}.
    Groups come out ordered by their most recently used Idea."""
    groups: dict[str, dict] = {}
    for e in entries:
        key = e.get("scenario", "")
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"scenario": key, "note": "", "time": e.get("time", ""),
                               "uses": 0, "entries": []}
        g["entries"].append(e)
        g["uses"] += int(e.get("uses", 1))
        if not g["note"] and e.get("note"):
            g["note"] = e["note"]
    return list(groups.values())


def search(entries: list[dict], text: str) -> list[dict]:
    """Entries containing every word of `text` (any case) in note, scenario or idea."""
    words = _clean(text).lower().split()
    if not words:
        return list(entries)
    out = []
    for e in entries:
        hay = " ".join(str(e.get(k, "")) for k in ("note", "scenario", "idea")).lower()
        if all(w in hay for w in words):
            out.append(e)
    return out
