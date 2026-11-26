"""Copy planning for File Copy Move Manager.

The planner is the single place that decides what happens to every source file:
where it will be written once the folder structure, date folders and duplicate
numbering have all been applied (the *pre-destination*), and whether it needs to
be written at all.

    Preview      shows the plan  -> pre-destination vs. what is there now
    The copier   executes it     -> it never re-decides, so Preview == Copy
    Multi-source uses it too     -> one rule set for both tabs

Every decision comes from comparing against what is *really* on disk, so there is
no hidden state to drift: once a copy has finished without errors, planning again
produces nothing left to copy.

Matching rules (a source file is "already there" when ...)
  * Incremental ON : an existing file has the same size and the same date
                     (within 2 s, or exactly 1 h apart = daylight-saving quirk).
                     That is the documented meaning of Incremental: size + date
                     are trusted, also between sources (two sources with one
                     name, size and date are the same file). If only the date
                     differs, the contents are compared (MD5) so identical files
                     are not reported as changed (files over 256 MB are not hashed).
  * Incremental OFF: nothing is trusted; same-size files are compared by their
                     bytes (MD5), at the destination and between sources.
  * "Existing file" means the natural name *and* its numbered siblings
    (photo.png, photo_001.png, photo_002.png ...), so numbered copies made by an
    earlier run are recognised instead of being copied again.

When a file is not there yet
  * the natural name is free            -> NEW (if several *different* files want it,
                                           the newest one gets it)
  * a different file already has the name:
      - "newest wins" (Incremental ON, and either a mirror layout or "Number
        duplicate files" off):
            source newer than the file at the destination   -> REFRESH: it changed,
                                                               so copy it over the older copy
            source older (or the same date)                 -> OLDER: skipped, file is older
        (in a mirror layout the destination path belongs to this one source, so only a
        *newer destination* blocks the update)
      - otherwise "Number duplicate files" on               -> NUMBERED (photo_001.png ...),
                                                               nothing is overwritten
      - otherwise (off, Incremental off)                    -> NAME_TAKEN (skipped, never
                                                               overwritten)

All dates are the file's MODIFIED date (mtime), never the created date: copying a file
resets its created date to "now" but preserves its modified date, so only the modified
date means the same thing on both sides of a copy.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections import defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from folder_organization import FolderOrganizer, FolderStructure

DATE_TOLERANCE_S = 2.0                          # FAT/exFAT round timestamps to 2 s
DST_SHIFT_S = 3600.0                            # an exact 1 h gap = daylight-saving artefact
CONTENT_CHECK_MAX_BYTES = 256 * 1024 * 1024     # Incremental only: bigger files are not hashed
MAX_PATH_LEN = 245                              # stay clear of Windows' 260-char limit
HASH_WORKERS = 4
TEMP_PREFIX = "~fcmm_"                          # a copy in progress is written as ~fcmm_<id>.partial
TEMP_SUFFIX = ".partial"                        # ... and renamed into place only when complete
_HASH_CHUNK = 1024 * 1024
_NUMBERED = re.compile(r"^(?P<stem>.+)_(?P<n>\d{3,})$")

SourceFile = namedtuple("SourceFile", "path rel size mtime")
_Cand = namedtuple("_Cand", "norm real size mtime")


class PlanCancelled(Exception):
    """Raised while planning when the user presses Cancel."""


class Action(str, Enum):
    NEW = "new"                          # nothing there yet -> copy
    NUMBERED = "numbered"                # a different file has the name -> copy as name_001 ...
    REFRESH = "refresh"                  # same name, source is NEWER than the destination copy -> copy over it
    UP_TO_DATE = "up_to_date"            # destination has the same size + date -> skip
    SAME_CONTENT = "same_content"        # destination is identical (date differs) -> skip
    DUPLICATE_SOURCE = "duplicate_source"  # same image as another source being copied -> skip
    OLDER = "older"                      # same name, source is OLDER than the destination copy -> skip
    NAME_TAKEN = "name_taken"            # different file has the name, nothing may be overwritten -> skip


WRITE_ACTIONS = frozenset({Action.NEW, Action.NUMBERED, Action.REFRESH})


@dataclass(slots=True)
class PlanItem:
    """One source file and what will happen to it."""
    source_path: str
    size: int
    src_mtime: float                    # the date the destination copy will carry
    pre_dest: str                       # full path the file will be written to / already is at
    action: Action
    cur_dest: Optional[str] = None      # what exists now at the destination that it is compared with
    cur_size: Optional[int] = None
    cur_mtime: Optional[float] = None
    # The other source file this row is related to:
    #   DUPLICATE_SOURCE -> the file that is copied on this one's behalf
    #   NUMBERED         -> the file that took the plain name in this same copy (when nothing
    #                       on disk was in the way, i.e. cur_dest is empty)
    #   OLDER            -> the newer file that makes this one "older": the source that takes
    #                       (or replaces) the plain name in this copy, or a newer copy of the
    #                       version that is already at the destination
    ref: Optional[str] = None

    @property
    def writes(self) -> bool:
        return self.action in WRITE_ACTIONS


class Plan:
    """One PlanItem per source file, in copy order."""

    def __init__(self, items: List[PlanItem], dest_folder: str):
        self.items = items
        self.dest_folder = dest_folder
        self.leftover_temp_files: List[str] = []    # ~fcmm_*.partial left by an interrupted copy
        self.counts: Dict[Action, int] = {a: 0 for a in Action}
        self.bytes_to_copy = 0
        self._to_copy: List[PlanItem] = []
        for it in items:
            self.counts[it.action] += 1
            if it.action in WRITE_ACTIONS:
                self._to_copy.append(it)
                self.bytes_to_copy += it.size

    @property
    def to_copy(self) -> List[PlanItem]:
        return self._to_copy

    @property
    def copy_count(self) -> int:
        return len(self._to_copy)

    @property
    def skipped_count(self) -> int:
        return len(self.items) - len(self._to_copy)


# ── small helpers ────────────────────────────────────────────────────────────

def stamps_match(size_a: int, mtime_a: float, size_b: int, mtime_b: float) -> bool:
    """Same size and same modified date (2 s tolerance, or exactly 1 h apart)."""
    if size_a != size_b:
        return False
    gap = abs(mtime_a - mtime_b)
    return gap <= DATE_TOLERANCE_S or abs(gap - DST_SHIFT_S) <= DATE_TOLERANCE_S


def planned_name(dest_dir: str, filename: str, max_len: int = MAX_PATH_LEN) -> str:
    """The file name to use in dest_dir; shortened (…_tr_001) only if the path is too long."""
    if len(os.path.join(dest_dir, filename)) <= max_len:
        return filename
    stem, ext = os.path.splitext(filename)
    suffix = "_tr_001"
    allowed = max(1, max_len - len(dest_dir) - len(os.sep) - len(suffix) - len(ext))
    return f"{stem[:allowed]}{suffix}{ext}"


def compute_md5(path: str, cancel_check: Optional[Callable[[], bool]] = None) -> str:
    """MD5 of a file, read in 1 MB chunks. Raises PlanCancelled if cancel_check() turns true."""
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        while True:
            if cancel_check is not None and cancel_check():
                raise PlanCancelled()
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class _Progress:
    """Throttled (stage, done, total) reporter."""

    def __init__(self, callback, min_interval: float = 0.2):
        self._cb = callback
        self._min = min_interval
        self._last = 0.0

    def __call__(self, stage: str, done: int, total: int) -> None:
        if self._cb is None:
            return
        now = time.monotonic()
        if done >= total or now - self._last >= self._min:
            self._last = now
            self._cb(stage, done, total)


class _Hasher:
    """Hashes files in a small thread pool; results are cached for the whole plan."""

    def __init__(self, workers: int, cancelled: Callable[[], bool], report: _Progress):
        self._workers = max(1, workers)
        self._cancelled = cancelled
        self._report = report
        self._cache: Dict[str, Optional[str]] = {}

    def get(self, path: str) -> Optional[str]:
        return self._cache.get(path)

    def compute(self, paths: Iterable[str]) -> None:
        todo = [p for p in dict.fromkeys(paths) if p not in self._cache]
        if not todo:
            return

        def work(p: str):
            try:
                return p, compute_md5(p, self._cancelled)
            except PlanCancelled:
                raise
            except OSError:
                return p, None          # unreadable: never matches anything

        total, done = len(todo), 0
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = [pool.submit(work, p) for p in todo]
            try:
                for fut in as_completed(futures):
                    path, digest = fut.result()
                    self._cache[path] = digest
                    done += 1
                    self._report("Comparing file contents", done, total)
            except PlanCancelled:
                for f in futures:
                    f.cancel()
                raise


class _DirListing:
    """What is in one destination folder right now."""
    __slots__ = ("files", "numbered", "claimed", "temps")

    def __init__(self):
        self.files: Dict[str, Tuple[str, int, float]] = {}       # norm name -> (real name, size, mtime)
        self.numbered: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}   # (stem, ext) -> [(n, norm name)]
        self.claimed: set = set()                                 # every name in use, files and folders
        self.temps: List[str] = []                                # leftover ~fcmm_*.partial files


def _scan_dir(path: str) -> _DirListing:
    listing = _DirListing()
    try:
        with os.scandir(path) as entries:
            for e in entries:
                norm = os.path.normcase(e.name)
                listing.claimed.add(norm)
                if e.name.startswith(TEMP_PREFIX) and e.name.endswith(TEMP_SUFFIX):
                    listing.temps.append(os.path.join(path, e.name))      # not a real file: never matched
                    continue
                try:
                    if not e.is_file():
                        continue
                    st = e.stat()
                except OSError:
                    continue
                listing.files[norm] = (e.name, st.st_size, st.st_mtime)
                stem, ext = os.path.splitext(norm)
                m = _NUMBERED.match(stem)
                if m:
                    listing.numbered.setdefault((m.group("stem"), ext), []).append((int(m.group("n")), norm))
    except OSError:
        pass            # folder missing or unreadable: treated as empty
    return listing


def _candidates(listing: _DirListing, name_key: str) -> List[_Cand]:
    """The existing files that could be this name: the name itself, then name_001, name_002 ..."""
    out: List[_Cand] = []
    base = listing.files.get(name_key)
    if base is not None:
        out.append(_Cand(name_key, *base))
    stem, ext = os.path.splitext(name_key)
    for _n, norm in sorted(listing.numbered.get((stem, ext), ())):
        real, size, mtime = listing.files[norm]
        out.append(_Cand(norm, real, size, mtime))
    return out


class _Cluster:
    """Source files in one group that are the same file (same size + date)."""
    __slots__ = ("size", "mtime", "members", "match", "kind", "same_size")

    def __init__(self, size: int, mtime: float, first: int):
        self.size = size
        self.mtime = mtime
        self.members = [first]          # indices into the source list, in (mtime, path) order
        self.match: Optional[_Cand] = None      # existing destination file that already represents it
        self.kind: Optional[str] = None         # "stamp" or "content"
        self.same_size: List[_Cand] = []        # existing same-size files that need a content check


class _Variant:
    """One distinct image headed for one destination name (clusters merged by content)."""
    __slots__ = ("size", "md5", "clusters", "dest", "action", "cur", "copy_idx", "date")

    def __init__(self, cluster: _Cluster, md5: Optional[str]):
        self.size = cluster.size
        self.md5 = md5
        self.clusters = [cluster]
        self.dest = ""
        self.action: Optional[Action] = None
        self.cur: Optional[Tuple[str, int, float]] = None
        self.copy_idx = cluster.members[0]       # which source file is copied (set by pick_newest)
        self.date = cluster.mtime                # the modified date the copy will carry

    def pick_newest(self, sources: List[SourceFile]) -> None:
        """Copy the NEWEST copy of this image: with "newest wins" the date of an image is the date
        of its newest copy, and the destination file carries that date."""
        best = None
        for c in self.clusters:
            for i in c.members:
                if best is None or (sources[i].mtime, sources[best].path.lower()) > \
                        (sources[best].mtime, sources[i].path.lower()):
                    best = i
        self.copy_idx = best
        self.date = sources[best].mtime


class _Group:
    """All sources that want the same destination folder + file name."""
    __slots__ = ("dir_key", "name_key", "dest_dir", "name", "members", "cands",
                 "clusters", "variants", "next_n", "occ_date", "occ_src")

    def __init__(self, dir_key: str, name_key: str, dest_dir: str, name: str):
        self.dir_key = dir_key
        self.name_key = name_key
        self.dest_dir = dest_dir
        self.name = name
        self.members: List[int] = []
        self.cands: List[_Cand] = []
        self.clusters: List[_Cluster] = []
        self.variants: List[_Variant] = []
        self.next_n = 1
        # The newest date at which the version that is at the plain name now is known: its own
        # date, or a newer copy of that same version among the sources (e.g. re-stamped by a backup).
        self.occ_date: Optional[float] = None
        self.occ_src: Optional[str] = None      # the source that has that newer date, if any


def _cluster_by_stamp(sources: List[SourceFile], members: List[int]) -> List[_Cluster]:
    """Incremental: sources with the same size and date are the same file (that is what Incremental means)."""
    order = sorted(members, key=lambda i: (sources[i].mtime, sources[i].path.lower()))
    clusters: List[_Cluster] = []
    for i in order:
        s = sources[i]
        for c in clusters:
            if stamps_match(c.size, c.mtime, s.size, s.mtime):
                c.members.append(i)
                break
        else:
            clusters.append(_Cluster(s.size, s.mtime, i))
    return clusters


def _cluster_by_content(sources: List[SourceFile], members: List[int], hasher: "_Hasher") -> List[_Cluster]:
    """Non-incremental: sources are the same file only if their bytes are identical."""
    order = sorted(members, key=lambda i: (sources[i].mtime, sources[i].path.lower()))
    clusters: List[_Cluster] = []
    seen: Dict[Tuple[int, str], _Cluster] = {}
    for i in order:
        s = sources[i]
        digest = hasher.get(s.path)
        if digest is not None and (s.size, digest) in seen:
            seen[(s.size, digest)].members.append(i)
            continue
        c = _Cluster(s.size, s.mtime, i)
        clusters.append(c)
        if digest is not None:
            seen[(s.size, digest)] = c
    return clusters


def _same_size_members(sources: List[SourceFile], members: List[int]) -> List[str]:
    """Paths of the members that share their size with another member (the only ones worth hashing)."""
    counts: Dict[int, int] = defaultdict(int)
    for i in members:
        counts[sources[i].size] += 1
    return [sources[i].path for i in members if counts[sources[i].size] > 1]


# ── the planner ──────────────────────────────────────────────────────────────

def build_plan(
    files: Iterable[tuple],
    dest_folder: str,
    *,
    preserve_structure: bool = False,
    folder_structure: FolderStructure = FolderStructure.FLAT,
    number_duplicates: bool = True,
    incremental: bool = False,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str, int, int], None]] = None,
    hash_workers: int = HASH_WORKERS,
) -> Plan:
    """
    Plan a copy/move.

    Args:
        files: (full_path, rel_path, size, mtime) for every source file, in the
               order they should be copied.
        dest_folder: destination root.
        progress: optional callback(stage, done, total).

    Reads the destination and (when contents must be compared) the files
    involved; writes nothing. Raises PlanCancelled if cancel_check() turns true.
    """
    cancelled = cancel_check or (lambda: False)
    report = _Progress(progress)

    def check() -> None:
        if cancelled():
            raise PlanCancelled()

    sources = [SourceFile(*f) for f in files]
    dest_root = os.path.normpath(dest_folder)
    mirror = bool(preserve_structure) or folder_structure == FolderStructure.PRESERVE

    # 1 ── which destination folder + name does each source want? ─────────────
    groups: Dict[Tuple[str, str], _Group] = {}
    dir_paths: Dict[str, str] = {}
    for idx, src in enumerate(sources):
        if mirror:
            rel_dir = os.path.dirname(src.rel)
            dest_dir = os.path.normpath(os.path.join(dest_root, rel_dir)) if rel_dir else dest_root
        else:
            sub = FolderOrganizer.subfolder_for_mtime(src.mtime, folder_structure)
            dest_dir = os.path.join(dest_root, sub) if sub else dest_root
        name = planned_name(dest_dir, os.path.basename(src.path))
        dir_key = os.path.normcase(dest_dir)
        key = (dir_key, os.path.normcase(name))
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group(dir_key, key[1], dest_dir, name)
            dir_paths.setdefault(dir_key, dest_dir)
        group.members.append(idx)
        if idx % 4096 == 0:
            check()
    check()

    # 2 ── what is in those destination folders right now? ────────────────────
    listings: Dict[str, _DirListing] = {}
    for n, (dir_key, path) in enumerate(sorted(dir_paths.items()), 1):
        check()
        listings[dir_key] = _scan_dir(path)
        report("Reading destination folders", n, len(dir_paths))

    # 3 ── match every set of identical sources against the existing files ────
    hasher = _Hasher(hash_workers, cancelled, report)
    if not incremental:
        # Verify-by-content mode: sources that share a name and a size are told apart by their bytes.
        shared_size_paths: List[str] = []
        for group in groups.values():
            shared_size_paths.extend(_same_size_members(sources, group.members))
        check()
        hasher.compute(shared_size_paths)
    need_hash: List[str] = []
    for group in groups.values():
        group.cands = _candidates(listings[group.dir_key], group.name_key)
        group.clusters = (_cluster_by_stamp(sources, group.members) if incremental
                          else _cluster_by_content(sources, group.members, hasher))
        for c in group.clusters:
            if incremental:
                hit = next((k for k in group.cands if stamps_match(c.size, c.mtime, k.size, k.mtime)), None)
                if hit is not None:
                    c.match, c.kind = hit, "stamp"
                    continue
            same_size = [k for k in group.cands if k.size == c.size]
            if not same_size or (incremental and c.size > CONTENT_CHECK_MAX_BYTES):
                continue            # sizes differ => certainly different (or too big to hash)
            c.same_size = same_size
            need_hash.append(sources[c.members[0]].path)
            need_hash.extend(os.path.join(group.dest_dir, k.real) for k in same_size)
    check()
    hasher.compute(need_hash)
    for group in groups.values():
        for c in group.clusters:
            if c.match is not None or not c.same_size:
                continue
            digest = hasher.get(sources[c.members[0]].path)
            if digest is None:
                continue
            for k in c.same_size:
                if hasher.get(os.path.join(group.dest_dir, k.real)) == digest:
                    c.match = k
                    c.kind = "stamp" if stamps_match(c.size, c.mtime, k.size, k.mtime) else "content"
                    break

    # 4 ── what is left is not at the destination: merge identical images ─────
    merge_hash: List[str] = []
    unmatched: Dict[int, List[_Cluster]] = {}
    for group in groups.values():
        rest = [c for c in group.clusters if c.match is None]
        unmatched[id(group)] = rest
        by_size: Dict[int, List[_Cluster]] = defaultdict(list)
        for c in rest:
            by_size[c.size].append(c)
        for size, same in by_size.items():
            if len(same) > 1 and (not incremental or size <= CONTENT_CHECK_MAX_BYTES):
                merge_hash.extend(sources[c.members[0]].path for c in same)
    check()
    hasher.compute(merge_hash)
    for group in groups.values():
        for c in unmatched[id(group)]:
            digest = hasher.get(sources[c.members[0]].path)
            home = None
            if digest is not None:
                home = next((v for v in group.variants if v.size == c.size and v.md5 == digest), None)
            if home is None:
                group.variants.append(_Variant(c, digest))
            else:
                home.clusters.append(c)
        for v in group.variants:
            v.pick_newest(sources)
        # Newest first: the newest of several different files with one name is the one that gets
        # the plain name; the others are older (or, with numbering on, get name_001 ...).
        group.variants.sort(key=lambda v: (-v.date, sources[v.copy_idx].path.lower()))

    # 5 ── give every image a destination name and build the plan items ───────
    items: List[Optional[PlanItem]] = [None] * len(sources)
    by_dir: Dict[str, List[_Group]] = defaultdict(list)
    for group in groups.values():
        by_dir[group.dir_key].append(group)

    # "Newest wins": with Incremental on, a different file that has the name is compared by date —
    # newer sources update it, older ones are skipped. A mirror layout always works this way (the
    # path belongs to one source); in a date/flat layout it applies when numbering is off, because
    # numbering on means "keep every different file".
    newest_wins = incremental and (mirror or not number_duplicates)

    def newer_than_destination(variant: _Variant, group: _Group) -> bool:
        if mirror:      # one source per path: update unless the destination copy is newer
            return variant.date >= group.occ_date - DATE_TOLERANCE_S
        # date/flat: a tie must not flip-flop between two different images, so strictly newer
        return variant.date > group.occ_date + DATE_TOLERANCE_S

    for n, dir_key in enumerate(sorted(by_dir), 1):
        check()
        listing = listings[dir_key]
        claimed = set(listing.claimed)
        ordered = sorted(by_dir[dir_key], key=lambda g: g.name_key)
        later: List[Tuple[_Group, _Variant]] = []

        # Natural names first, so a numbered name can never steal another file's own name.
        for group in ordered:
            natural = os.path.join(group.dest_dir, group.name)
            occupant = listing.files.get(group.name_key)
            if occupant is not None:
                group.occ_date = occupant[2]
                for c in group.clusters:
                    if c.match is not None and c.match.norm == group.name_key:
                        for i in c.members:
                            if sources[i].mtime > group.occ_date:
                                group.occ_date, group.occ_src = sources[i].mtime, sources[i].path
            for vi, variant in enumerate(group.variants):
                if vi == 0 and group.name_key not in claimed:
                    variant.dest, variant.action, variant.cur = natural, Action.NEW, None
                    claimed.add(group.name_key)
                elif (vi == 0 and occupant is not None and newest_wins
                        and newer_than_destination(variant, group)):
                    variant.dest, variant.action = natural, Action.REFRESH
                    variant.cur = (os.path.join(group.dest_dir, occupant[0]), occupant[1], occupant[2])
                else:
                    later.append((group, variant))

        for group, variant in later:
            natural = os.path.join(group.dest_dir, group.name)
            occupant = listing.files.get(group.name_key)
            variant.cur = (
                (os.path.join(group.dest_dir, occupant[0]), occupant[1], occupant[2]) if occupant else None
            )
            winner = group.variants[0] if group.variants[0] is not variant else None
            takes_the_name = winner is not None and winner.action in (Action.NEW, Action.REFRESH)
            if newest_wins and (occupant is not None or takes_the_name):
                # A newer version of this name is at the destination, or is being copied there now.
                variant.dest, variant.action = natural, Action.OLDER
            elif number_duplicates:
                stem, ext = os.path.splitext(group.name)
                while True:
                    candidate = f"{stem}_{group.next_n:03d}{ext}"
                    group.next_n += 1
                    candidate_key = os.path.normcase(candidate)
                    if candidate_key not in claimed:
                        break
                claimed.add(candidate_key)
                variant.dest, variant.action = os.path.join(group.dest_dir, candidate), Action.NUMBERED
            else:
                variant.dest, variant.action = natural, Action.NAME_TAKEN

        for group in ordered:
            winner = group.variants[0] if group.variants else None
            winner_src = sources[winner.copy_idx].path if winner is not None else None
            replaced = winner is not None and winner.action is Action.REFRESH     # destination copy is being replaced
            for c in group.clusters:
                k = c.match
                if k is None:
                    continue
                path = os.path.join(group.dest_dir, k.real)
                if replaced and k.norm == group.name_key:
                    # These sources match the copy at the destination only until the newer file
                    # replaces it; afterwards they are older, and Preview says so now.
                    action, ref = Action.OLDER, winner_src
                else:
                    action, ref = (Action.UP_TO_DATE if c.kind == "stamp" else Action.SAME_CONTENT), None
                for i in c.members:
                    s = sources[i]
                    items[i] = PlanItem(s.path, s.size, s.mtime, path, action, path, k.size, k.mtime, ref=ref)
            for vi, variant in enumerate(group.variants):
                copy_idx = variant.copy_idx
                cur_dest, cur_size, cur_mtime = variant.cur or (None, None, None)
                took_the_name = None
                if (variant.action is Action.NUMBERED and cur_dest is None and vi > 0
                        and group.variants[0].action is Action.NEW):
                    took_the_name = sources[group.variants[0].copy_idx].path
                newer_one = None
                if variant.action is Action.OLDER:
                    if vi > 0 and winner.action in (Action.NEW, Action.REFRESH):
                        newer_one = winner_src                  # the file that takes / replaces the plain name
                    elif group.occ_src:
                        newer_one = group.occ_src               # a newer copy of the version at the destination
                for c in variant.clusters:
                    for i in c.members:
                        s = sources[i]
                        if variant.action is Action.NAME_TAKEN:
                            items[i] = PlanItem(s.path, s.size, s.mtime, variant.dest, Action.NAME_TAKEN,
                                                cur_dest, cur_size, cur_mtime)
                        elif variant.action is Action.OLDER:
                            items[i] = PlanItem(s.path, s.size, s.mtime, variant.dest, Action.OLDER,
                                                cur_dest, cur_size, cur_mtime, ref=newer_one)
                        elif i == copy_idx:
                            items[i] = PlanItem(s.path, s.size, s.mtime, variant.dest, variant.action,
                                                cur_dest, cur_size, cur_mtime, ref=took_the_name)
                        else:
                            items[i] = PlanItem(s.path, s.size, s.mtime, variant.dest, Action.DUPLICATE_SOURCE,
                                                ref=sources[copy_idx].path)
        report("Comparing with destination", n, len(by_dir))

    plan = Plan([it for it in items if it is not None], dest_root)
    plan.leftover_temp_files = [p for listing in listings.values() for p in listing.temps]
    return plan
