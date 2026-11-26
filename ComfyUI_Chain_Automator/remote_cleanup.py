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

boto3 is imported lazily so the app starts without it.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

CFG_DELETE_AFTER = "s3_delete_outputs_after_download"
CFG_OUTPUT_PREFIX = "s3_output_prefix"        # ComfyUI/output inside the bucket
DEFAULT_OUTPUT_PREFIX = "runpod-slim/ComfyUI/output/"

# The object can lag a moment behind the pod's /view endpoint, and RunPod's
# endpoint answers an occasional transient 403/404 on HeadObject.
_HEAD_ATTEMPTS = 4
_HEAD_DELAY = 2.0


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
        prefix = (config.get(CFG_OUTPUT_PREFIX) or DEFAULT_OUTPUT_PREFIX).strip().replace("\\", "/")
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"

    # ------------------------------------------------------------------ #

    def _get_client(self):
        if self._client is not None or self._failed:
            return self._client
        try:
            import boto3
            from botocore.config import Config as BotoConfig
            session = boto3.session.Session(
                profile_name=(self._config.get("s3_profile_name") or "").strip() or None)
            self._client = session.client(
                "s3",
                region_name=(self._config.get("s3_region") or "").strip() or None,
                endpoint_url=(self._config.get("s3_endpoint_url") or "").strip(),
                config=BotoConfig(s3={"addressing_style": "path"}, signature_version="s3v4",
                                  read_timeout=120, retries={"max_attempts": 3}),
            )
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
