"""Prompt history (with the settings each prompt ran under) and the big
pop-out prompt editor.

History lives in ``<workflow>.prompt_history.json`` next to the workflow —
the same sidecar file the Chain Automator writes, so entries from either
app show up in both. Entries written here carry extra keys (``prompts``,
``settings``, ``source``, ``sources``, ``results``, ``hidden``) that the
Automator simply ignores.

Favorites live in their OWN file, ``<workflow>.prompt_favorites.json``: a
starred prompt is a copy, not a flag on the history row, so clearing old
history can never take a favorite with it (v2.8.0 — it did, once). A history
row shows a star when a favorite with the same prompt and settings exists.

Nothing is ever dropped from the file: ``hidden`` only takes an entry out of
the default list, and the Archived tab brings it back. The history is meant to
be a complete record, so curation is a view, not a deletion.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTabBar, QTextEdit,
    QVBoxLayout, QWidget,
)

from ui.styles import COLORS
from ui.widgets import NoScrollComboBox

from workflow_tools import FAVORITES_SUFFIX, HISTORY_SUFFIX  # noqa: F401  (single source of truth)
APP_TAG = "ComfyUI Video Creator"


# --------------------------------------------------------------------- #
# File access
# --------------------------------------------------------------------- #

def history_path(workflow_path: Path) -> Path:
    return workflow_path.parent / f"{workflow_path.stem}{HISTORY_SUFFIX}"


def load_history(workflow_path: Path) -> list[dict]:
    try:
        with open(history_path(workflow_path), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(workflow_path: Path, entries: list[dict]) -> None:
    path = history_path(workflow_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def favorites_path(workflow_path: Path) -> Path:
    return workflow_path.parent / f"{workflow_path.stem}{FAVORITES_SUFFIX}"


def load_favorites(workflow_path: Path) -> list[dict]:
    try:
        with open(favorites_path(workflow_path), encoding="utf-8") as f:
            data = json.load(f)
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_favorites(workflow_path: Path, entries: list[dict]) -> None:
    path = favorites_path(workflow_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def find_favorite(favorites: list[dict], entry: dict) -> dict | None:
    """The favorite standing for this prompt + settings, if any."""
    return next((f for f in favorites if _same_run(f, entry)), None)


def _favorite_copy(entry: dict) -> dict:
    copy = {k: v for k, v in entry.items() if k not in ("favorite", "hidden")}
    copy["favorited"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return copy


def add_favorite(workflow_path: Path, entry: dict) -> bool:
    """Copy a history entry into the favorites file. False if already there."""
    favs = load_favorites(workflow_path)
    if find_favorite(favs, entry) is not None:
        return False
    favs.append(_favorite_copy(entry))
    save_favorites(workflow_path, favs)
    return True


def remove_favorite(workflow_path: Path, entry: dict) -> bool:
    """Drop the favorite for this prompt + settings. History is untouched."""
    favs = load_favorites(workflow_path)
    keep = [f for f in favs if not _same_run(f, entry)]
    if len(keep) == len(favs):
        return False
    save_favorites(workflow_path, keep)
    return True


def migrate_favorites(workflow_path: Path) -> int:
    """One-time move of the old ``favorite: true`` flags into the favorites
    file. The flag is cleared from history once copied, so an unstar later
    is not undone by the next migration pass. Returns how many moved."""
    entries = load_history(workflow_path)
    flagged = [e for e in entries if e.get("favorite")]
    if not flagged:
        return 0
    favs = load_favorites(workflow_path)
    moved = 0
    for e in flagged:
        if find_favorite(favs, e) is None:
            favs.append(_favorite_copy(e))
            moved += 1
        e.pop("favorite", None)
    save_favorites(workflow_path, favs)
    save_history(workflow_path, entries)
    return moved


def make_entry(prompts: list[tuple[str, str, str, bool, str]], settings: dict, source: str) -> dict:
    """prompts: (node_id, key, label, negative, text) tuples."""
    positives = [t.strip() for _n, _k, _l, neg, t in prompts if not neg and t.strip()]
    negatives = [t.strip() for _n, _k, _l, neg, t in prompts if neg and t.strip()]
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "positive": "\n\n".join(positives),
        "negative": "\n\n".join(negatives),
        "prompts": {f"{nid}|{key}": {"label": label, "negative": neg, "text": text}
                    for nid, key, label, neg, text in prompts},
        "settings": settings,
        "source": source,
        "results": [],
        "app": APP_TAG,
    }


def _same_run(a: dict, b: dict) -> bool:
    """Same prompt and same settings. The source image is deliberately NOT
    part of this: running one prompt over five images is one history entry
    with five results, not five near-identical entries (v2.6.0 tried that
    and it flooded the list). Which image made which file is kept per
    result in ``sources`` — see ``add_results``."""
    return (a.get("positive") == b.get("positive") and a.get("negative") == b.get("negative")
            and a.get("settings") == b.get("settings"))


def append_entry(workflow_path: Path, entry: dict) -> int:
    """Append unless it exactly repeats the latest entry (same prompt AND
    same settings). Returns the index of the entry that now represents it."""
    entries = load_history(workflow_path)
    if entries and _same_run(entries[-1], entry):
        return len(entries) - 1
    entries.append(entry)
    save_history(workflow_path, entries)
    return len(entries) - 1


def find_or_append_entry(workflow_path: Path, entry: dict) -> int:
    """Index of the entry with this prompt + settings, anywhere in the history;
    appended only when none exists. Used for runs started from Reuse Settings,
    which must not add a fresh "attempt" row each time but whose result still
    has to be recorded so the Library knows which source it came from."""
    entries = load_history(workflow_path)
    for i in range(len(entries) - 1, -1, -1):
        if _same_run(entries[i], entry):
            return i
    entries.append(entry)
    save_history(workflow_path, entries)
    return len(entries) - 1


def entry_matches(a: dict, b: dict) -> bool:
    """Whether two dicts are the same history entry.

    Entries carry no id, so identity is (timestamp, positive prompt, settings)
    — the triple Delete has always used. ``append_entry`` refuses to record a
    run that repeats the previous one with the same prompt and settings, so a
    false match needs two genuinely different runs logged in the same second
    with identical text and settings.
    """
    return (a.get("timestamp") == b.get("timestamp")
            and a.get("positive") == b.get("positive")
            and a.get("settings") == b.get("settings"))


def is_hidden(entry: dict) -> bool:
    return bool(entry.get("hidden"))


def set_entry_flag(workflow_path: Path, entry: dict, key: str, value: bool) -> bool:
    """Persist ``hidden`` on one entry. Returns whether it landed.

    Re-reads the file rather than writing back the whole in-memory list, so a
    run recorded by the app (or the Chain Automator) while the dialog sat open
    is not clobbered by a tick-box.
    """
    entries = load_history(workflow_path)
    hit = False
    for e in entries:
        if entry_matches(e, entry):
            e[key] = bool(value)
            hit = True
    if hit:
        save_history(workflow_path, entries)
        entry[key] = bool(value)      # keep the row the dialog holds in step
    return hit


def set_entries_flag(workflow_path: Path, targets: list[dict], key: str, value: bool) -> int:
    """``set_entry_flag`` for many entries of one workflow: one read, one
    write. Returns how many of ``targets`` were found and updated."""
    entries = load_history(workflow_path)
    done = 0
    for t in targets:
        hit = False
        for e in entries:
            if entry_matches(e, t):
                e[key] = bool(value)
                hit = True
        if hit:
            t[key] = bool(value)          # keep the row the dialog holds in step
            done += 1
    if done:
        save_history(workflow_path, entries)
    return done


def delete_entries(workflow_path: Path, targets: list[dict]) -> None:
    """Remove every history entry matching one of ``targets`` — one read, one write."""
    entries = load_history(workflow_path)
    save_history(workflow_path, [e for e in entries
                                 if not any(entry_matches(e, t) for t in targets)])


def add_results(workflow_path: Path, index: int, results: list[str],
                timing: dict | None = None, source: str = "") -> None:
    """Attach a finished run's output names — and how long it took — to
    the entry written when it was queued. ``timing`` is the worker's
    ``run_timing`` dict; its keys land on the entry as-is (``run_seconds``,
    ``render_seconds``, and from v2.3.0 ``sampler_steps`` / ``step_seconds`` /
    ``sampler_seconds``), so older entries simply lack them. ``source`` is
    the image/video this particular run started from; it is stored per
    result file in ``sources`` so one entry can hold runs over several
    images and the Library still shows the right one for each file."""
    entries = load_history(workflow_path)
    if 0 <= index < len(entries):
        existing = entries[index].setdefault("results", [])
        for r in results:
            if r not in existing:
                existing.append(r)
        if source:
            sources = entries[index].setdefault("sources", {})
            for r in results:
                sources[r] = source
        for key in ("run_seconds", "render_seconds", "sampler_steps", "step_seconds", "sampler_seconds"):
            if timing and timing.get(key) is not None:
                entries[index][key] = timing[key]
        save_history(workflow_path, entries)


def format_seconds(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def describe_steps(e: dict) -> str:
    """"48 steps @ 3.2 s/step" when the run timed its sampler, else ""."""
    steps, per = e.get("sampler_steps"), e.get("step_seconds")
    if not isinstance(steps, int) or not isinstance(per, (int, float)) or steps <= 0:
        return ""
    return f"{steps} steps @ {per:.1f} s/step"


def describe_timing(e: dict) -> str:
    """"12m 34s (render 11m 50s · 48 steps @ 3.2 s/step)" for an entry
    that recorded its run time; the render part is dropped when it isn't
    known or is the whole run anyway, the steps part when the sampler
    wasn't timed. "" for entries made before timing was recorded."""
    run = e.get("run_seconds")
    if not isinstance(run, (int, float)):
        return ""
    text = format_seconds(run)
    inner = []
    render = e.get("render_seconds")
    if isinstance(render, (int, float)) and int(render) < int(run):
        inner.append(f"render {format_seconds(render)}")
    if describe_steps(e):
        inner.append(describe_steps(e))
    if inner:
        text += " (" + " · ".join(inner) + ")"
    return text


def describe_settings(settings: dict | None) -> str:
    if not settings:
        return ""
    bits = []
    loras = [l for l in settings.get("loras", []) if l.get("name") and l.get("name") != "None"]
    if loras:
        bits.append("LoRAs: " + " · ".join(
            f"{Path(l['name']).stem} ({', '.join(f'{v:g}' for v in l.get('strengths', {}).values()) or '-'})"
            for l in loras))
    seed = settings.get("seed")
    bits.append(f"Seed {seed}" if seed is not None else "Seed random")
    if settings.get("steps") is not None:
        bits.append(f"Steps {settings['steps']}")
    if settings.get("megapixels") is not None:
        bits.append(f"{settings['megapixels']:g} MP")
    length = settings.get("length")
    if length:
        val = length.get("value")
        bits.append(f"{length.get('label', 'Length')}: {val:g}" if isinstance(val, (int, float))
                    else f"{length.get('label', 'Length')}: {val}")
    if settings.get("video_input_mode"):
        bits.append(f"input {settings['video_input_mode']}")
    if settings.get("text_to_video"):
        bits.append("text → video")
    if settings.get("mode"):
        bits.append(settings["mode"])
    return "  |  ".join(bits)


def source_for_result(e: dict, result: str) -> str:
    """The image/video that made ``result``: the per-file record first,
    then the entry-level source older sidecars (pre-v2.6.1) wrote."""
    return ((e.get("sources") or {}).get(result) or e.get("source") or "") if result else ""


def format_entry(e: dict, result: str | None = None) -> str:
    """Multi-line human-readable dump of one history entry.

    The Prompt History dialog calls this with no ``result`` and gets no
    source line at all — an entry can stand for runs over several images,
    and the list is about the prompt, not the file. The Library passes the
    file it is showing and gets that file's own source."""
    lines = [f"Saved: {e.get('timestamp', '?')}"]
    if describe_timing(e):
        lines.append(f"Generated in: {describe_timing(e)}")
    if describe_steps(e) and isinstance(e.get("sampler_seconds"), (int, float)):
        lines.append(f"Sampler: {describe_steps(e)} — about {format_seconds(e['sampler_seconds'])} denoising")
    if result and source_for_result(e, result):
        lines.append(f"Source: {source_for_result(e, result)}")
    lines.append("")
    prompts = e.get("prompts") or {}
    if prompts:
        for p in prompts.values():
            lines += [f"── {p.get('label', 'Prompt')} ──", p.get("text", ""), ""]
    else:
        lines += ["── Positive ──", e.get("positive", ""), ""]
        if e.get("negative"):
            lines += ["── Negative ──", e.get("negative", ""), ""]
    s = e.get("settings") or {}
    if s:
        lines.append("── Settings ──")
        lines.append(f"Workflow: {s.get('workflow', '?')}   Mode: {s.get('mode', '?')}")
        seed = s.get("seed")
        lines.append(f"Seed: {seed if seed is not None else 'random'}")
        if s.get("steps") is not None:
            lines.append(f"Steps: {s['steps']}")
        if s.get("megapixels") is not None:
            lines.append(f"Megapixels: {s['megapixels']:g}")
        if s.get("length"):
            val = s["length"].get("value")
            lines.append(f"{s['length'].get('label', 'Length')}: {val:g}" if isinstance(val, (int, float))
                         else f"{s['length'].get('label', 'Length')}: {val}")
        for l in s.get("loras", []):
            strengths = ", ".join(f"{k}={v:g}" for k, v in (l.get("strengths") or {}).items())
            lines.append(f"LoRA {l.get('label', '')}: {l.get('name', 'None')}  {strengths}")
        if s.get("video_input_mode"):
            lines.append(f"Video input: {s['video_input_mode']}   Append to source: {s.get('extend_stitch')}")
        if s.get("text_to_video"):
            lines.append("Text → Video (no source image or video)")
        lines.append("")
    if e.get("results"):
        lines.append("── Results ──")
        lines += e["results"]
    return "\n".join(lines)


_LOOKUP_CACHE: dict[str, tuple[float, list[dict]]] = {}


def find_entry_for_result(workflow_dir: Path, filename: str) -> tuple[Path, dict] | None:
    """Scan every history file under the workflow folder for the entry whose
    results list names this file. Returns (workflow json path, entry)."""
    if not workflow_dir or not workflow_dir.is_dir():
        return None
    for hist in workflow_dir.rglob(f"*{HISTORY_SUFFIX}"):
        try:
            mtime = hist.stat().st_mtime
        except OSError:
            continue
        key = str(hist)
        cached = _LOOKUP_CACHE.get(key)
        if cached is None or cached[0] != mtime:
            try:
                with open(hist, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = []
            entries = data if isinstance(data, list) else []
            _LOOKUP_CACHE[key] = (mtime, entries)
        else:
            entries = cached[1]
        for entry in reversed(entries):
            if filename in (entry.get("results") or []):
                wf_path = hist.with_name(hist.name[: -len(HISTORY_SUFFIX)] + ".json")
                return wf_path, entry
    return None


# --------------------------------------------------------------------- #
# Dialogs
# --------------------------------------------------------------------- #

class PromptExpandDialog(QDialog):
    """Large pop-out editor for one prompt field."""

    def __init__(self, title: str, text: str, font: QFont, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit — {title}")
        self.setMinimumSize(900, 600)
        self.resize(1300, 820)
        self.setStyleSheet(parent.window().styleSheet() if parent else "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {COLORS['accent_hover']}; font-weight: bold; font-size: 12pt;")
        layout.addWidget(lbl)
        self._edit = QTextEdit()
        self._edit.setAcceptRichText(False)
        self._edit.setPlainText(text)
        size = max(font.pointSize() + 1, 11)
        self._edit.setFont(QFont(font.family(), size))
        # App stylesheet's QWidget font-size beats setFont(); override per widget.
        self._edit.setStyleSheet(f"font-size: {size}pt;")
        layout.addWidget(self._edit, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._edit.setFocus()

    def text(self) -> str:
        return self._edit.toPlainText()


class PromptHistoryDialog(QDialog):
    """Search, filter, curate, inspect and reuse history entries — for the
    current template or across every template's history.

    The file keeps everything ever run. These tabs decide what you look at:
    star the prompts worth coming back to, archive the ones you never want to
    see again, and nothing is deleted either way. Ctrl/Shift-click (or Ctrl+A)
    selects many rows; Archive and Delete act on all of them at once.
    """
    use_prompt = pyqtSignal(dict)        # entry — prompt text only
    use_all = pyqtSignal(dict)           # entry — prompt + settings

    ALL_WORKFLOWS = "__all__"
    DATE_MODES = [("all", "All dates"), ("year", "Year"), ("month", "Month"), ("day", "Day")]

    # Views. "All" means all VISIBLE — Archived is the way back to the rest.
    # (The stored flag is still ``hidden`` so older sidecars read as-is.)
    FAVORITES, RECENT, ALL, HIDDEN = range(4)
    VIEWS = [(FAVORITES, "★ Favorites"), (RECENT, "Recent"), (ALL, "All"), (HIDDEN, "Archived")]
    RECENT_LIMIT = 100

    def __init__(self, workflow_path: Path, parent=None, workflow_dir: Path | None = None):
        super().__init__(parent)
        self._workflow_path = workflow_path
        self._workflow_dir = workflow_dir
        self._current_rel = self._rel(workflow_path)
        # (rel, workflow json path, entry, kind) for every entry, newest
        # first. kind is "history" (from the history sidecar) or "favorite"
        # (from the favorites file) — they are separate records.
        self._rows: list[tuple[str, Path, dict, str]] = []
        self._filtered: list[tuple[str, Path, dict, str]] = []
        self._selected: tuple[str, Path, dict, str] | None = None
        self._favorites: list[dict] = []     # every favorite, for the star lookup
        self._count_base = ""                # "N of M"; the selection count is appended to it
        self._load_rows()

        self.setWindowTitle(f"Prompt History — {workflow_path.name}")
        self.setMinimumSize(1000, 620)
        self.resize(1360, 800)
        self.setStyleSheet(parent.window().styleSheet() if parent else "")
        self._build_ui()
        self._rebuild_date_values()
        self._populate()

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #

    def _rel(self, wf_path: Path) -> str:
        if self._workflow_dir is not None:
            try:
                return wf_path.relative_to(self._workflow_dir).as_posix()
            except ValueError:
                pass
        return wf_path.name

    def _sidecars(self, suffix: str) -> list[Path]:
        """Every workflow (json path) with a sidecar of this suffix, own first."""
        files: list[Path] = []
        if self._workflow_dir is not None and self._workflow_dir.is_dir():
            files = sorted(self._workflow_dir.rglob(f"*{suffix}"), key=lambda p: str(p).lower())
        own = self._workflow_path.parent / f"{self._workflow_path.stem}{suffix}"
        if own not in files:
            files.insert(0, own)
        return [f.with_name(f.name[: -len(suffix)] + ".json") for f in files]

    def _load_rows(self):
        self._rows = []
        self._favorites = []
        for wf_path in self._sidecars(HISTORY_SUFFIX):
            migrate_favorites(wf_path)      # old favorite flags -> favorites file
            rel = self._rel(wf_path)
            for e in load_history(wf_path):
                if isinstance(e, dict):
                    self._rows.append((rel, wf_path, e, "history"))
        for wf_path in self._sidecars(FAVORITES_SUFFIX):
            rel = self._rel(wf_path)
            for e in load_favorites(wf_path):
                self._rows.append((rel, wf_path, e, "favorite"))
                self._favorites.append(e)
        self._rows.sort(key=lambda r: r[2].get("timestamp", ""), reverse=True)

    def _starred(self, entry: dict) -> bool:
        """Whether a favorite with this prompt + settings exists."""
        return find_favorite(self._favorites, entry) is not None

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        self._tabs = QTabBar()
        self._tabs.setExpanding(False)
        self._tabs.setToolTip(
            "Favorites — the prompts you starred, kept in their own file so clearing\n"
            "            history never touches them\n"
            "Recent — the newest entries you haven't archived\n"
            "All — everything you haven't archived\n"
            "Archived — tucked away, still in the file; select and press Unarchive to bring back")
        for _key, label in self.VIEWS:
            self._tabs.addTab(label)
        self._tabs.currentChanged.connect(lambda _i: self._populate())
        root.addWidget(self._tabs)

        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("Template:"))
        self._wf_combo = NoScrollComboBox()
        self._wf_combo.setToolTip("The workflow JSON each history file belongs to")
        counts: dict[str, int] = {}
        for rel, _p, _e, kind in self._rows:
            if kind == "history":
                counts[rel] = counts.get(rel, 0) + 1
        self._wf_combo.addItem(f"All templates ({sum(counts.values())})", self.ALL_WORKFLOWS)
        self._wf_combo.addItem(f"{self._current_rel} ({counts.get(self._current_rel, 0)})  — current", self._current_rel)
        for rel in sorted(counts, key=str.lower):
            if rel != self._current_rel:
                self._wf_combo.addItem(f"{rel} ({counts[rel]})", rel)
        self._wf_combo.setCurrentIndex(1)
        self._wf_combo.currentIndexChanged.connect(self._on_filter_source_changed)
        wrow.addWidget(self._wf_combo, stretch=1)
        root.addLayout(wrow)

        frow = QHBoxLayout()
        frow.addWidget(QLabel("Date:"))
        self._date_mode = NoScrollComboBox()
        for key, label in self.DATE_MODES:
            self._date_mode.addItem(label, key)
        self._date_mode.setFixedWidth(110)
        self._date_mode.currentIndexChanged.connect(self._on_filter_source_changed)
        frow.addWidget(self._date_mode)
        self._date_value = NoScrollComboBox()
        self._date_value.setMinimumWidth(190)
        self._date_value.currentIndexChanged.connect(lambda _i: self._populate())
        frow.addWidget(self._date_value)
        frow.addSpacing(14)
        frow.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by prompt text, LoRA name, seed, steps, result file, source image…")
        self._search.textChanged.connect(self._populate)
        frow.addWidget(self._search, stretch=1)
        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("status_dim")
        frow.addWidget(self._count_lbl)
        root.addLayout(frow)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.setStyleSheet("QListWidget { font-family: 'Segoe UI'; font-size: 9.5pt; }")
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ctrl/Shift-click, drag, Ctrl+A. The preview follows the current row;
        # Archive and Delete act on the whole selection.
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.currentRowChanged.connect(self._on_select)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        split.addWidget(self._list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        rl.addWidget(self._preview, stretch=1)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([560, 800])
        root.addWidget(split, stretch=1)

        brow = QHBoxLayout()
        self._use_btn = QPushButton("Use prompt")
        self._use_btn.setToolTip("Load only the prompt text into the editor")
        self._use_btn.clicked.connect(lambda: self._emit(self.use_prompt))
        brow.addWidget(self._use_btn)
        self._use_all_btn = QPushButton("Use prompt + settings")
        self._use_all_btn.setToolTip("Load the prompt and restore the LoRAs, strengths, seed, steps, megapixels and length it ran with")
        self._use_all_btn.clicked.connect(lambda: self._emit(self.use_all))
        brow.addWidget(self._use_all_btn)
        brow.addSpacing(18)
        self._fav_btn = QPushButton("★ Favorite")
        self._fav_btn.setObjectName("secondary_btn")
        self._fav_btn.setToolTip("Copy this prompt + settings into the favorites file "
                                 "(<workflow>.prompt_favorites.json). Deleting or archiving "
                                 "history never touches favorites.")
        self._fav_btn.clicked.connect(self._toggle_favorite)
        brow.addWidget(self._fav_btn)
        self._hide_btn = QPushButton("Archive")
        self._hide_btn.setObjectName("secondary_btn")
        self._hide_btn.setToolTip("Take the selected entries out of the list (Ctrl/Shift-click or "
                                  "Ctrl+A to select many). They stay in the history file and "
                                  "come back from the Archived tab.")
        self._hide_btn.clicked.connect(self._toggle_hidden)
        brow.addWidget(self._hide_btn)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("secondary_btn")
        self._del_btn = del_btn
        del_btn.setToolTip("Remove the selected entries from the history file for good (favorites "
                           "are kept separately and are not affected). On the Favorites tab: "
                           "remove the favorite only. To just get it out of the way, use Archive.")
        del_btn.clicked.connect(self._delete)
        brow.addWidget(del_btn)
        brow.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary_btn")
        close_btn.clicked.connect(self.close)
        brow.addWidget(close_btn)
        root.addLayout(brow)

    # ------------------------------------------------------------------ #
    # Filtering
    # ------------------------------------------------------------------ #

    def _workflow_rows(self) -> list[tuple[str, Path, dict]]:
        sel = self._wf_combo.currentData()
        if sel == self.ALL_WORKFLOWS:
            return self._rows
        return [r for r in self._rows if r[0] == sel]

    @staticmethod
    def _date_key(entry: dict, mode: str) -> str:
        ts = entry.get("timestamp", "") or ""
        return {"year": ts[:4], "month": ts[:7], "day": ts[:10]}.get(mode, "")

    def _on_filter_source_changed(self, *_):
        self._rebuild_date_values()
        self._populate()

    def _rebuild_date_values(self):
        mode = self._date_mode.currentData()
        prev = self._date_value.currentData()
        self._date_value.blockSignals(True)
        self._date_value.clear()
        if mode == "all":
            self._date_value.setEnabled(False)
            self._date_value.addItem("—", "")
        else:
            self._date_value.setEnabled(True)
            counts: dict[str, int] = {}
            for _r, _p, e, _k in self._workflow_rows():
                k = self._date_key(e, mode)
                if k:
                    counts[k] = counts.get(k, 0) + 1
            for k in sorted(counts, reverse=True):
                self._date_value.addItem(f"{k}  ({counts[k]})", k)
            idx = self._date_value.findData(prev) if prev else -1
            self._date_value.setCurrentIndex(idx if idx >= 0 else 0)
        self._date_value.blockSignals(False)

    # An H3 prompt opens with a long templated preamble — the reference clause
    # ("For the target video, at 0.00 seconds ... is fully referenced"), then
    # the shot-1 framing — that is word-for-word identical across every run off
    # the same template. A preview taken from the top therefore makes all 58
    # rows read the same, which is useless when the job is picking out the ones
    # worth starring. Two steps fix it: jump past the known section header, then
    # drop whatever prefix the rows on screen actually turn out to share.
    PREVIEW_SKIP = ("integrated_multimodal_description:", "[Shot 1]")
    PREVIEW_WIDTH = 90
    PREFIX_SCAN = 1500       # H3 preambles run long; no point looking past this
    PREFIX_MIN = 30          # below this it is a coincidence, not boilerplate
    PREFIX_SHARE = 0.5       # the boilerplate only has to be the majority

    @classmethod
    def _prompt_body(cls, e: dict) -> str:
        """The entry's prompt as one line, past any known section header."""
        text = (e.get("positive")
                or next(iter((e.get("prompts") or {}).values()), {}).get("text", "")
                or "")
        for marker in cls.PREVIEW_SKIP:
            at = text.find(marker)
            if at != -1:
                text = text[at + len(marker):]
                break
        return " ".join(text.split())

    @classmethod
    def _shared_prefix(cls, bodies: list[str]) -> str:
        """The boilerplate opener the rows on screen share, to the last whole word.

        Deliberately a MAJORITY rather than all of them: one entry written
        against a different template, or hand-edited, would otherwise drag the
        common prefix to nothing and put every row back to reading the same.
        Rows that do not start with it are simply left untrimmed.
        """
        if len(bodies) < 2:
            return ""
        openers = Counter(b[:cls.PREFIX_MIN] for b in bodies if len(b) >= cls.PREFIX_MIN)
        if not openers:
            return ""
        opener, n = openers.most_common(1)[0]
        if n < 2 or n < len(bodies) * cls.PREFIX_SHARE:
            return ""
        group = [b for b in bodies if b.startswith(opener)]
        limit = min(cls.PREFIX_SCAN, min(len(b) for b in group))
        first = group[0]
        i = 0
        while i < limit and all(b[i] == first[i] for b in group):
            i += 1
        # Never cut mid-word: back up to the last space in the shared run.
        space = first.rfind(" ", 0, i)
        if space > 0:
            i = space + 1
        return first[:i] if i >= cls.PREFIX_MIN else ""

    @classmethod
    def _clip(cls, body: str, prefix: str) -> str:
        text = body[len(prefix):] if prefix and body.startswith(prefix) else body
        text = text.lstrip(" ,.;:-—")
        return text[:cls.PREVIEW_WIDTH] + ("…" if len(text) > cls.PREVIEW_WIDTH else "")

    @staticmethod
    def _entry_text(rel: str, e: dict) -> str:
        parts = [rel, e.get("positive", ""), e.get("negative", ""), describe_settings(e.get("settings")),
                 " ".join(e.get("results", []) or []), e.get("source", "") or "",
                 " ".join((e.get("sources") or {}).values())]
        for p in (e.get("prompts") or {}).values():
            parts.append(p.get("text", ""))
        return "\n".join(parts).lower()

    def _view_rows(self, rows: list) -> list:
        """Apply the selected tab to an already workflow/date/search-filtered list."""
        view = self._tabs.currentIndex()
        if view == self.FAVORITES:
            # The favorites file, and nothing else — its own space.
            return [r for r in rows if r[3] == "favorite"]
        history = [r for r in rows if r[3] == "history"]
        if view == self.HIDDEN:
            return [r for r in history if is_hidden(r[2])]
        visible = [r for r in history if not is_hidden(r[2])]
        if view == self.RECENT:
            # Strictly newest first and capped: "recent" answers "what did I
            # just run", so floating favourites into it would defeat the tab.
            return visible[:self.RECENT_LIMIT]
        # All — the browse-everything view, so starred prompts lead.
        return sorted(visible, key=lambda r: not self._starred(r[2]))

    def _update_tab_counts(self, rows: list):
        history = [r for r in rows if r[3] == "history"]
        counts = {
            self.FAVORITES: sum(1 for r in rows if r[3] == "favorite"),
            self.RECENT: min(self.RECENT_LIMIT, sum(1 for r in history if not is_hidden(r[2]))),
            self.ALL: sum(1 for r in history if not is_hidden(r[2])),
            self.HIDDEN: sum(1 for r in history if is_hidden(r[2])),
        }
        for key, label in self.VIEWS:
            self._tabs.setTabText(key, f"{label} ({counts[key]})")

    def _populate(self):
        q = self._search.text().strip().lower()
        mode = self._date_mode.currentData()
        dval = self._date_value.currentData() if mode != "all" else ""
        show_wf = self._wf_combo.currentData() == self.ALL_WORKFLOWS
        rows = self._workflow_rows()
        matched = [
            r for r in rows
            if (not dval or self._date_key(r[2], mode) == dval)
            and (not q or q in self._entry_text(r[0], r[2]))
        ]
        self._update_tab_counts(matched)
        self._filtered = self._view_rows(matched)

        keep = self._selected
        bodies = [self._prompt_body(e) for _r, _p, e, _k in self._filtered]
        prefix = self._shared_prefix(bodies)
        self._list.blockSignals(True)
        self._list.clear()
        for (rel, _p, e, kind), body in zip(self._filtered, bodies):
            preview = self._clip(body, prefix)
            starred = kind == "favorite" or self._starred(e)
            line = ("★ " if starred else "") + e.get("timestamp", "?")
            if show_wf:
                line += f"   [{rel}]"
            settings = describe_settings(e.get("settings"))
            if settings:
                line += f"   {settings}"
            if e.get("results"):
                line += f"   → {Path(e['results'][-1]).name}"
            if describe_timing(e):
                line += f"   ⏱ {describe_timing(e)}"
            self._list.addItem(QListWidgetItem(line + "\n    " + preview))
        self._list.blockSignals(False)

        self._count_base = f"{len(self._filtered)} of {len(rows)}"
        row = next((n for n, r in enumerate(self._filtered)
                    if keep is not None and r[1] == keep[1] and r[3] == keep[3]
                    and entry_matches(r[2], keep[2])), 0)
        if self._filtered:
            self._list.setCurrentRow(row)
            self._on_select(row)
        else:
            self._selected = None
            self._preview.setPlainText("")
        self._update_buttons()

    def _on_select(self, row: int):
        if row < 0 or row >= len(self._filtered):
            self._selected = None
            self._preview.setPlainText("")
            return
        self._selected = self._filtered[row]
        rel, _p, e, kind = self._selected
        head = f"Workflow: {rel}\n" if rel != self._current_rel else ""
        if kind == "favorite" and e.get("favorited"):
            head += f"Favorited: {e['favorited']}\n"
        self._preview.setPlainText(head + format_entry(e))
        self._update_buttons()

    def _picked(self) -> list[tuple[str, Path, dict, str]]:
        """The selected rows, in list order."""
        rows = sorted(i.row() for i in self._list.selectedIndexes())
        return [self._filtered[r] for r in rows if 0 <= r < len(self._filtered)]

    def _update_buttons(self):
        """Buttons follow the selection: Use/Favorite want exactly one row,
        Archive and Delete take any number."""
        picked = self._picked()
        n = len(picked)
        history = [r for r in picked if r[3] == "history"]
        favorites = [r for r in picked if r[3] == "favorite"]
        for b in (self._use_btn, self._use_all_btn, self._fav_btn):
            b.setEnabled(n == 1)
        if n == 1:
            starred = picked[0][3] == "favorite" or self._starred(picked[0][2])
            self._fav_btn.setText("★ Unfavorite" if starred else "★ Favorite")
        # A favorite is its own record: no archive button for it.
        self._hide_btn.setEnabled(bool(history))
        all_hidden = bool(history) and all(is_hidden(r[2]) for r in history)
        count = f" ({len(history)})" if len(history) > 1 else ""
        self._hide_btn.setText(("Unarchive" if all_hidden else "Archive") + count)
        self._del_btn.setEnabled(n > 0)
        if favorites and not history:
            self._del_btn.setText("Remove favorite" + (f"s ({n})" if n > 1 else ""))
        else:
            self._del_btn.setText("Delete" + (f" ({n})" if n > 1 else ""))
        self._count_lbl.setText(self._count_base + (f" · {n} selected" if n > 1 else ""))

    def _save_failed(self, wf_path: Path):
        QMessageBox.warning(self, "Could not save",
                            f"Some entries are no longer in {wf_path.name}'s history file.")
        self._load_rows()

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def _emit(self, signal):
        picked = self._picked()
        if len(picked) == 1:
            signal.emit(picked[0][2])
            self.close()

    def _toggle_favorite(self):
        """Star = copy into the favorites file; unstar = remove that copy.
        Either way the history file is left exactly as it was."""
        picked = self._picked()
        if len(picked) != 1:
            return
        _rel, wf_path, entry, kind = picked[0]
        if kind == "favorite" or self._starred(entry):
            remove_favorite(wf_path, entry)
        else:
            add_favorite(wf_path, entry)
        self._reload()

    def _reload(self):
        self._load_rows()
        self._rebuild_date_values()
        self._populate()

    def _after_bulk(self, first_row: int):
        """Rebuild, then leave the cursor where the removed rows were so a
        run of Archive clicks works down the list instead of jumping to the top."""
        self._reload()
        if self._filtered:
            self._list.setCurrentRow(min(first_row, len(self._filtered) - 1))

    def _by_workflow(self, rows) -> dict[Path, list[dict]]:
        grouped: dict[Path, list[dict]] = {}
        for _rel, wf_path, entry, _kind in rows:
            grouped.setdefault(wf_path, []).append(entry)
        return grouped

    def _toggle_hidden(self):
        """Archive every selected entry — or, when they are all archived
        already, bring them all back."""
        history = [r for r in self._picked() if r[3] == "history"]
        if not history:
            return
        first_row = min(i.row() for i in self._list.selectedIndexes())
        hide = not all(is_hidden(r[2]) for r in history)
        failed = None
        for wf_path, entries in self._by_workflow(history).items():
            if set_entries_flag(wf_path, entries, "hidden", hide) != len(entries):
                failed = wf_path
        if failed is not None:
            self._save_failed(failed)
        self._after_bulk(first_row)

    def _delete(self):
        picked = self._picked()
        if not picked:
            return
        first_row = min(i.row() for i in self._list.selectedIndexes())
        n = len(picked)
        favorites = [r for r in picked if r[3] == "favorite"]
        history = [r for r in picked if r[3] == "history"]
        if favorites and not history:
            what = "this favorite" if n == 1 else f"these {n} favorites"
            if QMessageBox.question(
                    self, "Remove favorite" + ("s" if n > 1 else ""),
                    f"Remove {what}?\n\n"
                    f"Only the favorites file changes — the history entries they came "
                    f"from (if they still exist) are not touched.") != QMessageBox.StandardButton.Yes:
                return
            for _rel, wf_path, entry, _kind in favorites:
                remove_favorite(wf_path, entry)
            self._after_bulk(first_row)
            return
        what = "this history entry" if len(history) == 1 else f"these {len(history)} history entries"
        if QMessageBox.question(
                self, "Delete entry" if len(history) == 1 else "Delete entries",
                f"Delete {what} for good?\n\n"
                f"Favorites are kept in their own file and are not affected.\n"
                f"To keep the records but take them out of the list, "
                f"press Archive instead.") != QMessageBox.StandardButton.Yes:
            return
        for wf_path, entries in self._by_workflow(history).items():
            delete_entries(wf_path, entries)
        self._after_bulk(first_row)
