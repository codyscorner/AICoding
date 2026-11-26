"""ffmpeg helpers: locate the binary, grab a thumbnail frame, and probe."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def resolve_ffmpeg(configured: str, base_dir: Path) -> str:
    """Configured path if it exists → ffmpeg.exe next to the app → PATH."""
    configured = (configured or "").strip()
    if configured and Path(configured).exists():
        return configured
    bundled = base_dir / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return "ffmpeg"


def _run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace",
    )


def extract_thumbnail(ffmpeg: str, video: Path, dst: Path) -> bool:
    try:
        r = _run([ffmpeg, "-y", "-i", str(video), "-vframes", "1", "-q:v", "3", str(dst)], timeout=20)
        return r.returncode == 0 and dst.exists()
    except Exception:
        return False


@dataclass
class VideoProps:
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    duration: float = 0.0


_RES_RE = re.compile(r"Video:.*?\s(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe(ffmpeg: str, path: Path) -> VideoProps:
    """Parse ffmpeg's own stream dump so we don't depend on ffprobe."""
    p = VideoProps()
    try:
        r = _run([ffmpeg, "-hide_banner", "-i", str(path)], timeout=30)
    except Exception:
        return p
    text = r.stderr or ""
    m = _RES_RE.search(text)
    if m:
        p.width, p.height = int(m.group(1)), int(m.group(2))
    m = _FPS_RE.search(text)
    if m:
        p.fps = float(m.group(1))
    m = _DUR_RE.search(text)
    if m:
        p.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    p.has_audio = "Audio:" in text
    return p


def extract_embedded_prompt(path: Path) -> dict | None:
    """Read the ComfyUI API-format prompt VHS_VideoCombine bakes into every
    mp4 it writes (a `{"prompt": ...}` JSON blob sitting in the container,
    same place the VHS Metadata Parser app reads it from). Returns the raw
    node-id -> node dict (link structure intact, literal values as run), or
    None if the file has none (not ComfyUI output, or not mp4)."""
    if path.suffix.lower() != ".mp4":
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    idx = data.find(b'{"prompt"')
    if idx == -1:
        return None
    chunk = bytearray()
    depth = 0
    for b in data[idx:]:
        if b >= 128:
            continue
        ch = chr(b)
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        chunk.append(b)
        if depth == 0:
            break
    try:
        outer = json.loads(chunk.decode("utf-8"))
        prompt = outer.get("prompt")
        if isinstance(prompt, str):
            prompt = json.loads(prompt)
        return prompt if isinstance(prompt, dict) else None
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
