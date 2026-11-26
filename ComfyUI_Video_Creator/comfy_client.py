"""Thin ComfyUI HTTP/websocket client — works the same against a local
server and a RunPod HTTPS proxy URL.
"""

from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Callable

import requests

from workflow_tools import STATUS_NODE_LABELS


class ComfyClient:
    def __init__(self, base_url: str, log: Callable[[str], None] | None = None):
        self.url = base_url.rstrip("/")
        self.client_id = str(uuid.uuid4())
        self._log = log or (lambda _m: None)

    # ------------------------------------------------------------------ #
    # Basic calls
    # ------------------------------------------------------------------ #

    def test(self) -> dict:
        r = requests.get(f"{self.url}/system_stats", timeout=15)
        r.raise_for_status()
        return r.json()

    def upload(self, path: Path, subfolder: str = "", overwrite: bool = True) -> str:
        """Upload an image or video into ComfyUI's input folder. Returns the
        name a Load node should reference (``subfolder/name`` when nested)."""
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = {"type": "input", "overwrite": "true" if overwrite else "false"}
        if subfolder:
            data["subfolder"] = subfolder
        with open(path, "rb") as f:
            r = requests.post(
                f"{self.url}/upload/image",
                files={"image": (path.name, f, ctype)},
                data=data,
                timeout=600,
            )
        r.raise_for_status()
        info = r.json()
        name = info.get("name", path.name)
        sub = info.get("subfolder", "") or ""
        return f"{sub}/{name}" if sub else name

    def queue(self, workflow: dict) -> str:
        r = requests.post(
            f"{self.url}/prompt",
            json={"prompt": workflow, "client_id": self.client_id, "extra_data": {"extra_pnginfo": {}}},
            timeout=60,
        )
        if r.status_code >= 400:
            # ComfyUI returns a JSON body describing which node failed validation
            try:
                body = r.json()
            except ValueError:
                body = r.text
            raise RuntimeError(f"ComfyUI rejected the workflow ({r.status_code}): {_format_prompt_error(body)}")
        return r.json()["prompt_id"]

    def list_models(self, folder: str = "loras") -> list[str]:
        """Names the server's Load LoRA nodes accept. Newer ComfyUI exposes
        /models/<folder>; older builds only have /object_info."""
        try:
            r = requests.get(f"{self.url}/models/{folder}", timeout=20)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return [str(x) for x in data]
        except (requests.RequestException, ValueError):
            pass
        r = requests.get(f"{self.url}/object_info/LoraLoaderModelOnly", timeout=20)
        r.raise_for_status()
        info = r.json().get("LoraLoaderModelOnly", {})
        opts = (info.get("input", {}).get("required", {}).get("lora_name") or [[]])[0]
        return [str(x) for x in opts] if isinstance(opts, list) else []

    def history(self, prompt_id: str) -> dict:
        r = requests.get(f"{self.url}/history/{prompt_id}", timeout=20)
        r.raise_for_status()
        return r.json().get(prompt_id, {})

    def interrupt(self, prompt_id: str = "") -> None:
        if prompt_id:
            try:
                requests.post(f"{self.url}/queue", json={"delete": [prompt_id]}, timeout=10)
            except Exception:
                pass
        try:
            requests.post(f"{self.url}/interrupt", timeout=10)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Waiting
    # ------------------------------------------------------------------ #

    def wait(self, prompt_id: str, workflow: dict,
             on_step: Callable[[int, int, str], None],
             on_phase: Callable[[str], None],
             cancelled: Callable[[], bool]) -> None:
        """Block until the prompt finishes. Live step progress over the
        websocket, HTTP polling if the socket is unavailable. Raises on a
        server-side execution error."""
        try:
            import websocket
        except ImportError:
            self._poll(prompt_id, cancelled)
            return

        ws_url = self.url.replace("https://", "wss://").replace("http://", "ws://")
        try:
            ws = websocket.create_connection(f"{ws_url}/ws?clientId={self.client_id}", timeout=20)
        except Exception as e:  # noqa: BLE001
            self._log(f"Websocket unavailable ({type(e).__name__}) — polling instead")
            self._poll(prompt_id, cancelled)
            return

        start = time.time()
        last_minute = 0
        logged_node = None
        started = False
        try:
            while not cancelled():
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    # Quiet stretch (model load, VAE decode) — confirm via
                    # history so a missed finish can't hang us forever.
                    try:
                        if self._history_done(prompt_id):
                            return
                    except requests.RequestException:
                        pass
                    minute = int(time.time() - start) // 60
                    if minute > last_minute:
                        last_minute = minute
                        self._log(f"Running... ({minute}m)")
                    continue
                except Exception:
                    self._log("Websocket dropped — polling instead")
                    self._poll(prompt_id, cancelled)
                    return

                if isinstance(msg, bytes):
                    continue  # binary preview frames
                try:
                    payload = json.loads(msg)
                except ValueError:
                    continue
                mtype = payload.get("type")
                data = payload.get("data", {}) or {}
                if mtype == "progress":
                    on_step(int(data.get("value", 0)), int(data.get("max", 1)),
                            str(data.get("node") or ""))
                    minute = int(time.time() - start) // 60
                    if minute > last_minute:
                        last_minute = minute
                        self._log(f"Running... ({minute}m)")
                elif mtype == "executing" and data.get("prompt_id") == prompt_id:
                    node_id = data.get("node")
                    if node_id is None:
                        return  # prompt finished
                    if not started:
                        started = True
                        self._log("ComfyUI started processing")
                    if node_id != logged_node:
                        logged_node = node_id
                        ct = (workflow.get(node_id) or {}).get("class_type", "")
                        label = STATUS_NODE_LABELS.get(ct)
                        if label:
                            on_phase(label)
                elif mtype == "execution_error" and data.get("prompt_id") == prompt_id:
                    raise RuntimeError(_format_exec_error(data))
                elif mtype == "execution_interrupted" and data.get("prompt_id") == prompt_id:
                    return
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _history_done(self, prompt_id: str) -> bool:
        h = self.history(prompt_id)
        if not h:
            return False
        status = h.get("status", {}) or {}
        if status.get("completed", False):
            return True
        msgs = status.get("messages", []) or []
        if msgs and msgs[-1][0] == "execution_error":
            raise RuntimeError(_format_exec_error(msgs[-1][1]))
        if status.get("status_str") == "error":
            raise RuntimeError("ComfyUI reported an execution error — check the server console.")
        return False

    def _poll(self, prompt_id: str, cancelled: Callable[[], bool]) -> None:
        elapsed = 0
        while not cancelled():
            time.sleep(3)
            elapsed += 3
            try:
                q = requests.get(f"{self.url}/queue", timeout=10).json()
                running = [item[1] for item in q.get("queue_running", [])]
                pending = [item[1] for item in q.get("queue_pending", [])]
                if prompt_id in running:
                    if elapsed % 60 == 0:
                        self._log(f"Running... ({elapsed // 60}m)")
                    continue
                if prompt_id in pending:
                    if elapsed % 60 == 0:
                        self._log(f"Queued... ({elapsed // 60}m)")
                    continue
                if self._history_done(prompt_id):
                    return
                if elapsed % 60 == 0:
                    self._log(f"Waiting for history... ({elapsed // 60}m)")
            except requests.RequestException as e:
                self._log(f"Poll error: {e}")

    # ------------------------------------------------------------------ #
    # Outputs
    # ------------------------------------------------------------------ #

    @staticmethod
    def collect_outputs(history_entry: dict, preferred_nodes: list[str]) -> list[dict]:
        """File records ({filename, subfolder, type}) the prompt produced.
        Video-output nodes are checked first; ComfyUI's native SaveVideo
        reports under the "images" key, VHS_VideoCombine under "gifs"."""
        outputs = history_entry.get("outputs", {}) or {}
        video_exts = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif")

        for nid in preferred_nodes:
            node_out = outputs.get(nid, {}) or {}
            files = node_out.get("videos") or node_out.get("gifs") or node_out.get("images") or []
            if files:
                return sorted(files, key=lambda f: f.get("filename", ""))

        for node_out in outputs.values():
            files = node_out.get("videos") or node_out.get("gifs") or []
            if files:
                return sorted(files, key=lambda f: f.get("filename", ""))

        for node_out in outputs.values():
            files = [f for f in node_out.get("images", []) if f.get("filename", "").lower().endswith(video_exts)]
            if files:
                return sorted(files, key=lambda f: f.get("filename", ""))

        for node_out in outputs.values():
            files = node_out.get("images") or []
            if files:
                return sorted(files, key=lambda f: f.get("filename", ""))
        return []

    def download(self, file_info: dict, dest: Path, attempts: int = 6) -> Path:
        params = {
            "filename": file_info["filename"],
            "subfolder": file_info.get("subfolder", "") or "",
            "type": file_info.get("type", "output") or "output",
        }
        dl = None
        for attempt in range(attempts):
            dl = requests.get(f"{self.url}/view", params=params, timeout=600, stream=True)
            if dl.status_code == 200:
                break
            self._log(f"Not ready, retrying ({attempt + 1}/{attempts})...")
            time.sleep(5)
        dl.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in dl.iter_content(1024 * 1024):
                f.write(chunk)
        return dest


# --------------------------------------------------------------------- #
# Error formatting
# --------------------------------------------------------------------- #

def _format_exec_error(data: dict) -> str:
    node_type = data.get("node_type", "")
    node_id = data.get("node_id", "")
    msg = data.get("exception_message", "") or data.get("exception_type", "") or "unknown error"
    where = f" in node {node_id} ({node_type})" if node_id or node_type else ""
    return f"ComfyUI execution error{where}: {msg}"


def _format_prompt_error(body) -> str:
    if not isinstance(body, dict):
        return str(body)[:800]
    err = body.get("error", {})
    parts = []
    if isinstance(err, dict):
        parts.append(err.get("message", "") or "")
        if err.get("details"):
            parts.append(str(err["details"]))
    node_errors = body.get("node_errors", {}) or {}
    for nid, info in node_errors.items():
        ct = info.get("class_type", "")
        for e in info.get("errors", []) or []:
            parts.append(f"node {nid} ({ct}): {e.get('message', '')} {e.get('details', '')}".strip())
    return "; ".join(p for p in parts if p)[:1200] or str(body)[:800]
