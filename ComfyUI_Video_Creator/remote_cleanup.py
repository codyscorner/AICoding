"""Delete a result file from the RunPod volume once it is safely on this PC.

ComfyUI writes every finished video into <ComfyUI>/output on the pod's network
volume, and nothing ever removes it, so the volume (billed per GB) fills up
with clips that were already downloaded. When Settings > Models > "Delete
results from the pod volume after download" is ticked, each file is removed
through RunPod's S3-compatible API right after it has been saved locally.

A file is only deleted when ALL of these hold, so a half-written or
truncated download can never cost the only good copy:
  * the object exists on the volume and its size equals the local file's size,
  * the local file is not empty,
  * the pod reported it as a real output (not a temp/preview file).

Any failure (no boto3, bad credentials, S3 hiccup, size mismatch) is logged and
swallowed: the video is already downloaded, so cleanup must never fail a run.

RunPod S3 quirks respected (see the S3 Browser app): single-object
`delete_object` only (bulk DeleteObjects answers 307), and the run's folder is
a real directory node that survives its files, so empty parent folders are
removed bottom-up.

The second half of this module is the bulk "Clean up pod folders" button
(Settings > Models): it lists everything under this app's own two folders on
the volume - <output prefix>VideoCreator/ (results, plus the first-frame .png
and -audio intermediates the per-run delete never sees) and
<input prefix>VideoCreator/ (the source images/videos uploaded for each run)
- shows the totals for confirmation, then deletes file by file on a QThread.
Nothing outside those two folders is ever listed or touched.

boto3 is imported lazily so the app starts without it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal

CFG_DELETE_AFTER = "s3_delete_outputs_after_download"
CFG_OUTPUT_PREFIX = "s3_output_prefix"        # ComfyUI/output inside the bucket
DEFAULT_OUTPUT_PREFIX = "runpod-slim/ComfyUI/output/"
CFG_INPUT_PREFIX = "s3_input_prefix"          # ComfyUI/input inside the bucket
DEFAULT_INPUT_PREFIX = "runpod-slim/ComfyUI/input/"

# The subfolder this app uses under both ComfyUI/output and ComfyUI/input
# (run_worker uploads to input/VideoCreator/ and results are written to
# output/VideoCreator/<run id>/). The bulk cleanup never leaves these two.
APP_FOLDER = "VideoCreator"

# The object can lag a moment behind the pod's /view endpoint, and RunPod's
# endpoint answers an occasional transient 403/404 on HeadObject.
_HEAD_ATTEMPTS = 4
_HEAD_DELAY = 2.0


def norm_prefix(value: str | None, default: str) -> str:
    """Bucket prefix with forward slashes and exactly one trailing slash."""
    prefix = (value or "").strip().replace("\\", "/") or default
    return prefix if prefix.endswith("/") else prefix + "/"


def make_client(config):
    """boto3 S3 client for the RunPod volume, built from the Settings values.
    Raises if boto3 is missing or the connection fields are blank."""
    import boto3
    from botocore.config import Config as BotoConfig
    endpoint = (config.get("s3_endpoint_url") or "").strip()
    if not endpoint or not (config.get("s3_bucket_name") or "").strip():
        raise ValueError("S3 endpoint and bucket are not set (Settings > Models)")
    session = boto3.session.Session(
        profile_name=(config.get("s3_profile_name") or "").strip() or None)
    return session.client(
        "s3",
        region_name=(config.get("s3_region") or "").strip() or None,
        endpoint_url=endpoint,
        config=BotoConfig(s3={"addressing_style": "path"}, signature_version="s3v4",
                          read_timeout=120, retries={"max_attempts": 3}),
    )


def enabled(config) -> bool:
    """Setting ticked AND the S3 connection filled in."""
    return bool(
        config.get(CFG_DELETE_AFTER, False)
        and (config.get("s3_endpoint_url") or "").strip()
        and (config.get("s3_bucket_name") or "").strip()
        and (config.get("s3_profile_name") or "").strip()
    )


class OutputCleaner:
    """One per worker; the S3 client is built on first use."""

    def __init__(self, config, log: Callable[[str], None]):
        self._config = config
        self._log = log
        self._client = None
        self._failed = False          # client could not be built: stay quiet after the first message
        self.bucket = (config.get("s3_bucket_name") or "").strip()
        self.prefix = norm_prefix(config.get(CFG_OUTPUT_PREFIX), DEFAULT_OUTPUT_PREFIX)

    # ------------------------------------------------------------------ #

    def _get_client(self):
        if self._client is not None or self._failed:
            return self._client
        try:
            self._client = make_client(self._config)
        except Exception as e:  # noqa: BLE001
            self._failed = True
            self._log(f"Pod cleanup skipped — S3 not usable: {e}")
        return self._client

    def _remote_size(self, key: str) -> int | None:
        """Size of the object, or None if it never showed up."""
        from botocore.exceptions import ClientError
        for attempt in range(_HEAD_ATTEMPTS):
            try:
                return self._client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
            except ClientError:
                if attempt < _HEAD_ATTEMPTS - 1:
                    time.sleep(_HEAD_DELAY)
        return None

    def _prune_empty_dirs(self, subfolder_parts: list[str]) -> None:
        """Remove the (now empty) run folders, deepest first. A folder is only
        touched when a listing shows nothing under it, and a non-empty one is
        refused by RunPod anyway."""
        for depth in range(len(subfolder_parts), 0, -1):
            dir_key = self.prefix + "/".join(subfolder_parts[:depth]) + "/"
            try:
                resp = self._client.list_objects_v2(Bucket=self.bucket, Prefix=dir_key, MaxKeys=2)
                others = [o for o in resp.get("Contents", []) if o["Key"] != dir_key]
                if others:
                    return
                self._client.delete_object(Bucket=self.bucket, Key=dir_key)
            except Exception:  # noqa: BLE001 — leftover empty folder is harmless
                return

    # ------------------------------------------------------------------ #

    def delete_if_downloaded(self, file_info: dict, local_path: Path) -> bool:
        """Delete the pod-side copy of `file_info` (a ComfyUI {filename,
        subfolder, type} record) if `local_path` is a complete copy of it."""
        try:
            if (file_info.get("type") or "output") != "output":
                return False
            name = file_info["filename"]
            parts = [p for p in (file_info.get("subfolder") or "").replace("\\", "/").split("/") if p]
            if ".." in parts or ".." in name or "/" in name or "\\" in name:
                return False
            client = self._get_client()
            if client is None:
                return False
            local_size = Path(local_path).stat().st_size
            if local_size <= 0:
                self._log(f"Pod cleanup: kept {name} on the volume (local copy is empty)")
                return False
            key = self.prefix + "/".join(parts + [name])
            remote_size = self._remote_size(key)
            if remote_size is None:
                self._log(f"Pod cleanup: {name} not found on the volume at {key} — check Settings > "
                          f"Models > Output prefix")
                return False
            if remote_size != local_size:
                self._log(f"Pod cleanup: kept {name} on the volume (pod {remote_size:,} bytes vs "
                          f"local {local_size:,})")
                return False
            client.delete_object(Bucket=self.bucket, Key=key)
            self._prune_empty_dirs(parts)
            self._log(f"Deleted {name} from the pod volume (verified {local_size // 1024:,} KB downloaded)")
            return True
        except Exception as e:  # noqa: BLE001
            self._log(f"Pod cleanup failed for {file_info.get('filename', '?')}: {e}")
            return False


# ====================================================================== #
# Bulk cleanup of this app's folders on the volume (Settings > Models)
# ====================================================================== #

@dataclass
class FolderScan:
    """Everything found under one of the app's folders on the volume."""
    label: str                      # "Results" / "Uploaded sources"
    prefix: str                     # full bucket prefix, trailing slash
    files: list[tuple[str, int]] = field(default_factory=list)   # (key, size)
    folders: list[str] = field(default_factory=list)             # dir keys, deepest first, root excluded

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def size(self) -> int:
        return sum(sz for _, sz in self.files)


def app_folders(config) -> list[tuple[str, str]]:
    """(label, prefix) of the two folders this app owns on the volume."""
    out = norm_prefix(config.get(CFG_OUTPUT_PREFIX), DEFAULT_OUTPUT_PREFIX)
    inp = norm_prefix(config.get(CFG_INPUT_PREFIX), DEFAULT_INPUT_PREFIX)
    return [("Results", out + APP_FOLDER + "/"), ("Uploaded sources", inp + APP_FOLDER + "/")]


def _walk_folders(client, bucket: str, prefix: str) -> list[str]:
    """Every folder node below `prefix` (not `prefix` itself). RunPod hides
    folder nodes from a flat listing but reports them as CommonPrefixes of a
    delimiter listing, so this walks one level at a time."""
    found: list[str] = []
    pending = [prefix]
    while pending:
        cur = pending.pop()
        token = None
        while True:
            kw = {"Bucket": bucket, "Prefix": cur, "Delimiter": "/"}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            for cp in resp.get("CommonPrefixes", []):
                sub = cp["Prefix"]
                if sub != cur and sub.startswith(prefix):
                    found.append(sub)
                    pending.append(sub)
            token = resp.get("NextContinuationToken")
            if not token:
                break
    return found


def scan_folders(client, bucket: str, folders: list[tuple[str, str]]) -> list[FolderScan]:
    """List files and folder nodes under each of the app's folders. Folders
    come back deepest first, so deleting in order never hits a non-empty
    parent."""
    scans = []
    for label, prefix in folders:
        scan = FolderScan(label, prefix)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == prefix:
                    continue
                if key.endswith("/"):           # a folder node that did show up
                    if key not in scan.folders:
                        scan.folders.append(key)
                    continue
                scan.files.append((key, int(obj.get("Size", 0))))
        for d in _walk_folders(client, bucket, prefix):
            if d not in scan.folders:
                scan.folders.append(d)
        scan.folders.sort(key=lambda k: k.count("/"), reverse=True)
        scans.append(scan)
    return scans


def fmt_size(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    return f"{max(n, 0) // 1024:,} KB"


class FolderScanWorker(QThread):
    """Lists the app's folders on the volume without blocking the dialog."""
    scanned = pyqtSignal(list)          # list[FolderScan]
    failed = pyqtSignal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config

    def run(self):
        try:
            client = make_client(self._config)
            bucket = (self._config.get("s3_bucket_name") or "").strip()
            self.scanned.emit(scan_folders(client, bucket, app_folders(self._config)))
        except ImportError:
            self.failed.emit("boto3 is not installed in the Python running this app - use the built EXE or the repo .venv")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class FolderCleanupWorker(QThread):
    """Deletes everything a FolderScan found, one object per request (RunPod
    refuses bulk DeleteObjects), files first then folders deepest-first.
    Cancel stops after the object in flight; what is already gone stays gone."""
    progress = pyqtSignal(int, int, str)        # done, total, key
    finished_cleanup = pyqtSignal(int, int, int, list)   # files deleted, folders deleted, bytes freed, errors
    failed = pyqtSignal(str)

    def __init__(self, config: dict, scans: list[FolderScan], parent=None):
        super().__init__(parent)
        self._config = config
        self._scans = scans
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            client = make_client(self._config)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        bucket = (self._config.get("s3_bucket_name") or "").strip()
        total = sum(s.count + len(s.folders) for s in self._scans)
        done = files = folders = freed = 0
        errors: list[str] = []
        for scan in self._scans:
            for key, size in scan.files:
                if self._cancel:
                    break
                self.progress.emit(done, total, key)
                try:
                    client.delete_object(Bucket=bucket, Key=key)
                    files += 1
                    freed += size
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{key}: {e}")
                done += 1
            if self._cancel:
                break
            for dir_key in scan.folders:        # deepest first; all empty now
                if self._cancel:
                    break
                self.progress.emit(done, total, dir_key)
                try:
                    client.delete_object(Bucket=bucket, Key=dir_key)
                    folders += 1
                except Exception as e:  # noqa: BLE001 - a leftover empty folder costs nothing
                    errors.append(f"{dir_key}: {e}")
                done += 1
        self.progress.emit(done, total, "")
        self.finished_cleanup.emit(files, folders, freed, errors)
