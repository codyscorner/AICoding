"""Build GPU_Monitor.exe with PyInstaller and deploy it to P:\\Apps\\AICoded\\GPU Monitor.

Run with the repo .venv (build.bat does this automatically). The shared venv
also carries heavy ML packages, so each is excluded or the EXE balloons ~10x.
numpy is NOT excluded — pyqtgraph needs it.

Pass --no-deploy to build only (the EXE stays in dist/).
An existing deployed EXE is kept as a timestamped .exe.bak, never overwritten.
"""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
APP_NAME = "GPU_Monitor"
OUTPUT = Path(r"P:\Apps\AICoded\GPU Monitor")

EXCLUDES = [
    "torch", "torchvision", "torchaudio", "tensorflow", "transformers", "cv2",
    "scipy", "pandas", "matplotlib", "onnx", "onnxruntime", "triton", "IPython",
    "jupyter", "sklearn", "numba", "jax", "safetensors", "tokenizers", "einops",
    "av", "soundfile", "playwright", "boto3", "botocore", "requests", "PIL",
]

VENV_PY = ROOT.parent / ".venv" / "Scripts" / "python.exe"
try:
    import PyQt6  # noqa: F401
    import PyInstaller  # noqa: F401
    import pynvml  # noqa: F401
    import pyqtgraph  # noqa: F401
except ImportError:
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
        print(f"Dependencies missing in {sys.executable}; re-running with {VENV_PY}")
        sys.exit(subprocess.call([str(VENV_PY), __file__, *sys.argv[1:]]))
    print("ERROR: PyQt6, PyInstaller, nvidia-ml-py and pyqtgraph are required. Build with the repo .venv.")
    sys.exit(1)


def version_from_main() -> str:
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', (ROOT / "main.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def main():
    print(f"Building {APP_NAME} v{version_from_main()} with {sys.executable} ...")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", APP_NAME,
        "--icon", str(ROOT / "app_icon.ico"),
        "--add-data", f"{ROOT / 'app_icon.ico'};.",
        "--collect-data", "pyqtgraph",
        "--hidden-import", "pynvml",
        "--hidden-import", "apply_cli",
        "--hidden-import", "nvml_backend",
    ]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    cmd.append(str(ROOT / "main.py"))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        sys.exit(result.returncode)

    exe_src = DIST / f"{APP_NAME}.exe"
    if not exe_src.exists():
        print("EXE not found in dist/ — check the PyInstaller output above")
        sys.exit(1)
    print(f"Built {exe_src} ({exe_src.stat().st_size // (1024 * 1024)} MB)")
    if "--no-deploy" in sys.argv:
        print(f"--no-deploy: leaving it in dist/, {OUTPUT} untouched")
        return

    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / exe_src.name
    if target.exists():
        bak = OUTPUT / f"{APP_NAME}_{time.strftime('%Y%m%d_%H%M%S')}.exe.bak"
        shutil.copy2(target, bak)
        print(f"Kept previous EXE as {bak.name}")
    shutil.copy2(exe_src, target)
    print(f"Deployed to {target}")


if __name__ == "__main__":
    main()
