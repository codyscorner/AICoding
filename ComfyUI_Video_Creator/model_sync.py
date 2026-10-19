"""Model inventory + two-way sync between the local ComfyUI models folder and
the RunPod volume.

Grown from the Chain Automator's `lora_sync.py` (LoRAs only, upload only):
here every model file a workflow names is covered — checkpoints, diffusion
models, VAEs, text encoders, CLIP vision, upscalers, ControlNets and LoRAs —
and files move in whichever direction they are missing:

  * referenced + local + not on the pod   -> uploaded before the run
  * referenced + on the pod + not local   -> downloaded before the run
  * referenced + nowhere                  -> reported; the run would fail on
                                             the server with "model not found"

The pod's folder is read through RunPod's S3-compatible API (same profile /
endpoint / quirks as the S3 Browser app and the Chain Automator: long read
timeout for the server-side multipart merge, retries, "already landed" check
before re-uploading, size verified after every transfer).

boto3 is imported lazily so the app still starts without it (local-only
users) and a broken S3 config can never break a workflow load.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

MODEL_EXTS = {".safetensors", ".sft", ".pt", ".pt2", ".pth", ".ckpt", ".bin", ".pkl", ".gguf", ".onnx"}
_LORA_KEY_RE = re.compile(r"^lora(_name|_\d+)$")

# Config keys (all in video_creator_config.json next to the EXE)
CFG_MODEL_CHECK = "model_check_enabled"
CFG_MODELS_DIR = "models_dir"               # local ComfyUI/models; blank = parent of loras_dir
CFG_S3_PROFILE = "s3_profile_name"
CFG_S3_REGION = "s3_region"
CFG_S3_ENDPOINT = "s3_endpoint_url"
CFG_S3_BUCKET = "s3_bucket_name"
CFG_S3_MODELS_PREFIX = "s3_models_prefix"   # ComfyUI/models inside the bucket
# Off by default: a pod run only needs the file ON THE POD. Base models that
# live only on the volume (a 35 GB Flux2 text encoder, say) must not be pulled
# down to the PC before every run unless the user asked for local copies.
CFG_DOWNLOAD = "model_sync_download"

S3_DEFAULTS = {
    CFG_MODEL_CHECK: True,
    CFG_DOWNLOAD: False,
    CFG_MODELS_DIR: "",
    CFG_S3_PROFILE: "runpod-s3",
    CFG_S3_REGION: "",
    CFG_S3_ENDPOINT: "",
    CFG_S3_BUCKET: "",
    CFG_S3_MODELS_PREFIX: "runpod-slim/ComfyUI/models/",
}

TRANSFER_RETRY_ATTEMPTS = 6
TRANSFER_RETRY_BASE_DELAY = 1.0
# The pod's folder listing is reused this long, so queueing twenty runs from
# a multi-select doesn't list the volume twenty times.
REMOTE_CACHE_SECONDS = 120

# Input key -> the models/ subfolders ComfyUI resolves it against. The first
# entry is where a file goes when it has to be created on the other side;
# every entry is searched when looking for it. ComfyUI keeps legacy names
# (unet, clip) as aliases of the new ones, and a user's install may have the
# file in either.
_KEY_FOLDERS: dict[str, list[str]] = {
    "ckpt_name": ["checkpoints"],
    "unet_name": ["diffusion_models", "unet"],
    "vae_name": ["vae"],
    "clip_name": ["text_encoders", "clip"],
    "clip_name1": ["text_encoders", "clip"],
    "clip_name2": ["text_encoders", "clip"],
    "clip_name3": ["text_encoders", "clip"],
    "clip_name4": ["text_encoders", "clip"],
    "control_net_name": ["controlnet"],
    "style_model_name": ["style_models"],
    "gligen_name": ["gligen"],
    "hypernetwork_name": ["hypernetworks"],
    "photomaker_model_name": ["photomaker"],
    "audio_encoder_name": ["audio_encoders"],
}
# Class-type overrides for ambiguous keys.
_CLASS_KEY_FOLDERS: dict[tuple[str, str], list[str]] = {
    ("CLIPVisionLoader", "clip_name"): ["clip_vision"],
    ("UpscaleModelLoader", "model_name"): ["upscale_models"],
    ("LatentUpscaleModelLoader", "model_name"): ["latent_upscale_models"],
}


# ---------------------------------------------------------------------- #
# Workflow scanning
# ---------------------------------------------------------------------- #

@dataclass(frozen=True)
class ModelRef:
    name: str                 # as written in the workflow (may contain a subfolder)
    folders: tuple[str, ...]  # models/ subfolders to look in; [0] is canonical
    kind: str                 # short label for messages: "LoRA", "diffusion model", ...

    @property
    def rel(self) -> str:
        return self.name.replace("\\", "/")


_KIND_LABEL = {
    "loras": "LoRA", "checkpoints": "checkpoint", "diffusion_models": "diffusion model",
    "vae": "VAE", "text_encoders": "text encoder", "clip_vision": "CLIP vision",
    "upscale_models": "upscale model", "latent_upscale_models": "latent upscaler",
    "controlnet": "ControlNet", "style_models": "style model", "gligen": "GLIGEN",
    "hypernetworks": "hypernetwork", "photomaker": "PhotoMaker", "audio_encoders": "audio encoder",
}


def _folders_for(class_type: str, key: str) -> list[str] | None:
    if (class_type, key) in _CLASS_KEY_FOLDERS:
        return _CLASS_KEY_FOLDERS[(class_type, key)]
    if _LORA_KEY_RE.match(key):
        return ["loras"]
    if key in _KEY_FOLDERS:
        return _KEY_FOLDERS[key]
    # Unknown loader with a "<something>_name" key: fall back on the class
    # type's own words so new node packs still get checked somewhere sane.
    if key.endswith("_name") and "upscale" in class_type.lower():
        return ["upscale_models"]
    return None


def models_in_workflow(workflow: dict) -> list[ModelRef]:
    """Every model file the (final, edits applied) workflow names, deduped."""
    out: dict[tuple[str, str], ModelRef] = {}
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type") or "")
        for key, value in (node.get("inputs") or {}).items():
            if not isinstance(value, str):
                continue
            value = value.strip()
            if not value or value.lower() == "none" or Path(value).suffix.lower() not in MODEL_EXTS:
                continue
            folders = _folders_for(ct, key)
            if not folders:
                continue
            ref = ModelRef(value, tuple(folders), _KIND_LABEL.get(folders[0], folders[0]))
            out.setdefault((folders[0], ref.rel.lower()), ref)
    return sorted(out.values(), key=lambda r: (r.folders[0], r.rel.lower()))


# ---------------------------------------------------------------------- #
# Local models folder
# ---------------------------------------------------------------------- #

def local_models_dir(config: dict) -> Path | None:
    """Settings > Models > Models folder, else the parent of the LoRAs folder
    (which is ComfyUI/models/loras in every install we know of)."""
    explicit = (config.get(CFG_MODELS_DIR) or "").strip()
    if explicit:
        return Path(explicit)
    loras = (config.get("loras_dir") or "").strip()
    if loras and Path(loras).name.lower() == "loras":
        return Path(loras).parent
    return None


@dataclass
class LocalStatus:
    present: dict[ModelRef, Path] = field(default_factory=dict)   # ref -> file on disk
    folder_of: dict[ModelRef, str] = field(default_factory=dict)  # ref -> subfolder it was found in
    missing: list[ModelRef] = field(default_factory=list)
    case_mismatch: dict[ModelRef, str] = field(default_factory=dict)  # Windows finds it, the Linux pod won't
    root: Path | None = None


def check_local(config: dict, refs: list[ModelRef]) -> LocalStatus:
    st = LocalStatus(root=local_models_dir(config))
    if st.root is None or not st.root.is_dir():
        st.missing = list(refs)
        return st
    # O(refs), not a recursive walk: a LoRA folder with thousands of files
    # (plus previews and metadata sidecars) took three minutes to index over
    # the network share. Each ref is looked up directly, and only its own
    # parent folder is listed for the case-insensitive fallback — Windows
    # finds "Foo.safetensors" for "foo.safetensors", the Linux pod won't.
    dir_cache: dict[Path, dict[str, str]] = {}

    def names_in(d: Path) -> dict[str, str]:
        if d not in dir_cache:
            try:
                dir_cache[d] = {e.name.lower(): e.name for e in d.iterdir()}
            except OSError:
                dir_cache[d] = {}
        return dir_cache[d]

    for ref in refs:
        found = False
        for folder in ref.folders:
            candidate = st.root / folder / Path(ref.rel)
            if candidate.is_file():
                # is_file() is case-insensitive on Windows; confirm the spelling
                actual = names_in(candidate.parent).get(candidate.name.lower(), candidate.name)
                st.present[ref] = candidate.with_name(actual)
                st.folder_of[ref] = folder
                if actual != candidate.name:
                    st.case_mismatch[ref] = str(Path(ref.rel).with_name(actual)).replace("\\", "/")
                found = True
                break
        if not found:
            st.missing.append(ref)
    return st


# ---------------------------------------------------------------------- #
# RunPod volume via S3
# ---------------------------------------------------------------------- #

def s3_configured(config: dict) -> bool:
    return bool(
        (config.get(CFG_S3_ENDPOINT) or "").strip()
        and (config.get(CFG_S3_BUCKET) or "").strip()
        and (config.get(CFG_S3_PROFILE) or "").strip()
    )


def check_enabled(config: dict) -> bool:
    return bool(config.get(CFG_MODEL_CHECK, True)) and s3_configured(config)


def import_s3_browser_config(path: str | Path) -> dict:
    """Read the S3 Browser app's config.json (profile_name / region /
    endpoint_url / bucket_name) into this app's config keys."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for src, dst in (
        ("profile_name", CFG_S3_PROFILE), ("region", CFG_S3_REGION),
        ("endpoint_url", CFG_S3_ENDPOINT), ("bucket_name", CFG_S3_BUCKET),
    ):
        if data.get(src):
            out[dst] = str(data[src]).strip()
    return out


class S3ModelStore:
    """Thin S3 client scoped to the pod's ComfyUI/models folder."""

    def __init__(self, config: dict):
        import boto3  # lazy: optional dependency, slow import
        from botocore.config import Config as BotoConfig

        self.bucket = (config.get(CFG_S3_BUCKET) or "").strip()
        self.prefix = (config.get(CFG_S3_MODELS_PREFIX) or S3_DEFAULTS[CFG_S3_MODELS_PREFIX]).strip()
        if self.prefix and not self.prefix.endswith("/"):
            self.prefix += "/"
        session = boto3.session.Session(profile_name=(config.get(CFG_S3_PROFILE) or "").strip() or None)
        self._client = session.client(
            "s3",
            region_name=(config.get(CFG_S3_REGION) or "").strip() or None,
            endpoint_url=(config.get(CFG_S3_ENDPOINT) or "").strip(),
            # RunPod merges multipart chunks server-side after
            # CompleteMultipartUpload and can take minutes to answer for
            # large files — the default 60s read timeout would abort the wait
            # and trigger a full re-upload.
            config=BotoConfig(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                read_timeout=1800,
                retries={"max_attempts": 3},
            ),
        )

    def key_for(self, folder: str, rel: str) -> str:
        return f"{self.prefix}{folder}/{rel}"

    def test_connection(self) -> None:
        self._client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix, MaxKeys=1)

    def list_folder(self, folder: str) -> dict[str, int]:
        """Relative path inside models/<folder>/ -> size, recursive."""
        pfx = f"{self.prefix}{folder}/"
        out: dict[str, int] = {}
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=pfx):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(pfx):]
                if rel and not rel.endswith("/") and not Path(rel).name.startswith(".s3compat-merge-"):
                    out[rel] = obj["Size"]
        return out

    def list_folders(self) -> list[str]:
        """Top-level subfolders under models/ (what the pod actually has)."""
        resp = self._client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix, Delimiter="/")
        return sorted(p["Prefix"][len(self.prefix):].rstrip("/") for p in resp.get("CommonPrefixes", []))

    def object_size(self, key: str) -> int:
        return self._client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]

    def upload(self, local_path: Path, key: str, progress_cb=None) -> None:
        self._client.upload_file(str(local_path), self.bucket, key, Callback=progress_cb)

    def download(self, key: str, local_path: Path, progress_cb=None) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = local_path.with_name(local_path.name + ".part")
        self._client.download_file(self.bucket, key, str(tmp), Callback=progress_cb)
        tmp.replace(local_path)


# Remote listings are cached per (endpoint, bucket, prefix, folder) for a
# short while; transfers update the cache themselves so the next check in
# the same queue sees the file without another listing.
_remote_cache: dict[tuple, tuple[float, dict[str, int]]] = {}


def _cache_key(config: dict, folder: str) -> tuple:
    return ((config.get(CFG_S3_ENDPOINT) or "").strip(), (config.get(CFG_S3_BUCKET) or "").strip(),
            (config.get(CFG_S3_MODELS_PREFIX) or "").strip(), folder)


def _remote_listing(store: S3ModelStore, config: dict, folder: str) -> dict[str, int]:
    k = _cache_key(config, folder)
    hit = _remote_cache.get(k)
    if hit and time.time() - hit[0] < REMOTE_CACHE_SECONDS:
        return hit[1]
    listing = store.list_folder(folder)
    _remote_cache[k] = (time.time(), listing)
    return listing


def forget_remote_cache():
    _remote_cache.clear()


def _cache_add(config: dict, folder: str, rel: str, size: int):
    k = _cache_key(config, folder)
    hit = _remote_cache.get(k)
    if hit:
        hit[1][rel] = size


@dataclass
class RemoteStatus:
    present: dict[ModelRef, int] = field(default_factory=dict)      # ref -> size on pod
    folder_of: dict[ModelRef, str] = field(default_factory=dict)    # ref -> subfolder it was found in
    missing: list[ModelRef] = field(default_factory=list)
    error: str = ""                                                 # non-empty = could not check


def check_remote(config: dict, refs: list[ModelRef]) -> RemoteStatus:
    st = RemoteStatus()
    try:
        store = S3ModelStore(config)
        listings = {f: _remote_listing(store, config, f)
                    for f in sorted({f for r in refs for f in r.folders})}
    except ImportError:
        st.error = ("boto3 is not installed in the Python running this app. The built EXE "
                    "bundles it; when running from source use the repo .venv (run.bat does)")
        return st
    except Exception as e:  # noqa: BLE001
        st.error = f"{type(e).__name__}: {e}"
        return st
    for ref in refs:
        for folder in ref.folders:
            if ref.rel in listings[folder]:
                st.present[ref] = listings[folder][ref.rel]
                st.folder_of[ref] = folder
                break
        else:
            st.missing.append(ref)
    return st


# ---------------------------------------------------------------------- #
# Plan: what has to move, and which way
# ---------------------------------------------------------------------- #

@dataclass
class TransferJob:
    direction: str      # "upload" | "download"
    ref: ModelRef
    folder: str         # models/ subfolder on both sides
    local_path: Path
    size: int

    @property
    def label(self) -> str:
        return f"{self.ref.kind}: {self.folder}/{self.ref.rel}"


@dataclass
class SyncPlan:
    uploads: list[TransferJob] = field(default_factory=list)
    downloads: list[TransferJob] = field(default_factory=list)
    nowhere: list[ModelRef] = field(default_factory=list)         # missing on both sides
    optional_downloads: list[TransferJob] = field(default_factory=list)  # on the pod, not local; only run if the user says so
    size_mismatch: dict[ModelRef, tuple[int, int]] = field(default_factory=dict)  # (local, pod)
    case_mismatch: dict[ModelRef, str] = field(default_factory=dict)
    error: str = ""                                               # pod could not be checked
    local_root: Path | None = None

    @property
    def jobs(self) -> list[TransferJob]:
        return self.uploads + self.downloads

    @property
    def clean(self) -> bool:
        return not (self.uploads or self.downloads or self.nowhere or self.error)

    @property
    def total_bytes(self) -> int:
        return sum(j.size for j in self.jobs)


def plan_sync(config: dict, refs: list[ModelRef]) -> SyncPlan:
    plan = SyncPlan()
    if not refs:
        return plan
    local = check_local(config, refs)
    plan.local_root = local.root
    plan.case_mismatch = dict(local.case_mismatch)
    remote = check_remote(config, refs)
    if remote.error:
        plan.error = remote.error
        return plan
    for ref in refs:
        here = ref in local.present
        there = ref in remote.present
        if here and there:
            lsize = local.present[ref].stat().st_size
            if lsize != remote.present[ref]:
                plan.size_mismatch[ref] = (lsize, remote.present[ref])
        elif here:
            p = local.present[ref]
            plan.uploads.append(TransferJob("upload", ref, local.folder_of[ref], p, p.stat().st_size))
        elif there:
            if local.root is None:
                plan.nowhere.append(ref)        # nowhere to put it
                continue
            folder = remote.folder_of[ref]
            job = TransferJob("download", ref, folder, local.root / folder / Path(ref.rel), remote.present[ref])
            # The pod run has what it needs either way. The download only
            # matters for running the workflow locally, so unless the user
            # asked for it always, it is offered rather than started.
            (plan.downloads if config.get(CFG_DOWNLOAD, False) else plan.optional_downloads).append(job)
        else:
            plan.nowhere.append(ref)
    return plan


def fmt_rate(bps: float) -> str:
    return f"{bps / 1e6:.1f} MB/s" if bps >= 1e6 else f"{bps / 1e3:.0f} KB/s"


def fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:
        return "—"
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def fmt_size(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    return f"{n / 1e6:.0f} MB"


# ---------------------------------------------------------------------- #
# Qt workers
# ---------------------------------------------------------------------- #

class ModelCheckWorker(QThread):
    """Runs plan_sync off the UI thread (folder walk + S3 listings)."""
    done = pyqtSignal(object)   # SyncPlan

    def __init__(self, config: dict, refs: list[ModelRef]):
        super().__init__()
        self._config = config
        self._refs = list(refs)

    def run(self):
        self.done.emit(plan_sync(self._config, self._refs))


class TransferCancelled(Exception):
    """Raised inside boto3's progress callback to abort the transfer in
    flight. s3transfer propagates it out of upload_file / download_file within
    a few seconds and tidies its own parts, which is the only way to stop a
    35 GB download short of killing the process."""


class TransferWorker(QThread):
    """Moves the planned files: uploads to the pod, downloads to the local
    models folder. Each file is retried with backoff and its size verified.
    Cancel aborts the file in flight (not just "after this file")."""
    log = pyqtSignal(str)
    # bytes_done / bytes_total are `object`, NOT `int`: a pyqtSignal(int) is a C++ 32-bit int and silently wraps
    # anything over 2.1 GB (an 18 GB file showed as "855 MB" and the bytes sent went negative).
    progress = pyqtSignal(object, object, str, int, int)   # bytes_done, bytes_total, label, files_done, files_total
    finished_ok = pyqtSignal(list)                    # [(label, error)] — empty = all good

    def __init__(self, config: dict, jobs: list[TransferJob]):
        super().__init__()
        self._config = config
        self._jobs = list(jobs)
        self._cancelled = False
        self._total = sum(j.size for j in jobs)

    def cancel(self):
        self._cancelled = True

    def run(self):
        errors: list[tuple[str, str]] = []
        try:
            store = S3ModelStore(self._config)
        except ImportError:
            self.finished_ok.emit([("(connection)", "boto3 is not installed in the Python running this app — use the built EXE or the repo .venv")])
            return
        except Exception as e:  # noqa: BLE001
            self.finished_ok.emit([("(connection)", f"{type(e).__name__}: {e}")])
            return

        done_bytes = 0
        n = len(self._jobs)
        for i, job in enumerate(self._jobs):
            if self._cancelled:
                errors.append((job.label, "cancelled"))
                continue
            key = store.key_for(job.folder, job.ref.rel)
            verb = "Uploading" if job.direction == "upload" else "Downloading"
            self.log.emit(f"{verb} {i + 1}/{n}: {job.label} ({fmt_size(job.size)})")
            last_error: Exception | None = None
            for attempt in range(1, TRANSFER_RETRY_ATTEMPTS + 1):
                if self._cancelled:
                    break
                sent = 0
                merge_logged = False
                shown = ("↓ Downloading to this PC — " if job.direction == "download" else "↑ Uploading to the pod — ") + job.label
                if attempt > 1:
                    shown += f"   (attempt {attempt} of {TRANSFER_RETRY_ATTEMPTS} — restarted from 0)"

                def cb(chunk: int, _job=job, _shown=shown):
                    nonlocal sent, merge_logged
                    if self._cancelled:
                        raise TransferCancelled()
                    sent += chunk
                    self.progress.emit(done_bytes + sent, self._total, _shown, i, n)
                    if _job.direction == "upload" and not merge_logged and sent >= _job.size:
                        merge_logged = True
                        self.log.emit(f"  {_job.ref.rel}: all bytes sent, waiting for the pod to merge the upload...")

                try:
                    if job.direction == "upload":
                        store.upload(job.local_path, key, cb)
                    else:
                        store.download(key, job.local_path, cb)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    if self._cancelled or isinstance(exc, TransferCancelled):
                        last_error = TransferCancelled("cancelled")
                        self.log.emit(f"  {job.ref.rel}: cancelled after {fmt_size(sent)}")
                        if job.direction == "download":
                            try:
                                job.local_path.with_name(job.local_path.name + ".part").unlink(missing_ok=True)
                            except OSError:
                                pass
                        break
                    if job.direction == "upload":
                        # The final CompleteMultipartUpload can time out during
                        # RunPod's server-side merge even though the object landed.
                        try:
                            if store.object_size(key) == job.size:
                                last_error = None
                                break
                        except Exception:  # noqa: BLE001
                            pass
                    last_error = exc
                    if attempt < TRANSFER_RETRY_ATTEMPTS:
                        delay = TRANSFER_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        self.log.emit(f"  {job.ref.rel}: attempt {attempt} failed ({type(exc).__name__}), retrying in {delay:.0f}s")
                        time.sleep(delay)
            if last_error is not None:
                errors.append((job.label, str(last_error)))
                self.log.emit(f"  FAILED: {job.label}: {last_error}")
            else:
                # Verify size so a truncated file is never trusted on either side.
                try:
                    if job.direction == "upload":
                        got = store.object_size(key)
                        where = "on the pod"
                    else:
                        got = job.local_path.stat().st_size
                        where = f"in {job.local_path.parent}"
                    if got != job.size:
                        errors.append((job.label, f"size after transfer {got} != expected {job.size}"))
                        self.log.emit(f"  WARNING: {job.ref.rel} landed with the wrong size ({got} vs {job.size})")
                    else:
                        self.log.emit(f"  OK: {job.ref.rel} is {where}")
                        if job.direction == "upload":
                            _cache_add(self._config, job.folder, job.ref.rel, job.size)
                except Exception as e:  # noqa: BLE001
                    self.log.emit(f"  {job.ref.rel}: transferred, could not verify size ({e})")
            done_bytes += job.size
            self.progress.emit(done_bytes, self._total, job.label, i + 1, n)
        self.finished_ok.emit(errors)
