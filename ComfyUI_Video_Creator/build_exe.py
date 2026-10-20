"""Build ComfyUI_Video_Creator.exe with PyInstaller and deploy it to
P:\\Apps\\AICoded\\ComfyUI Video Creator.

Run with the repo .venv (build.bat does this automatically) — it has PyQt6,
requests, websocket-client and Pillow. The shared venv also carries heavy
ML packages, so every one of them is excluded or the EXE balloons ~10x.

Pass --no-deploy to build only (the EXE stays in dist/) — for a build
made while the deployed app is busy running.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
APP_NAME = "ComfyUI_Video_Creator"
OUTPUT = Path(r"P:\Apps\AICoded\ComfyUI Video Creator")
FFMPEG_SOURCES = [
    Path(r"P:\Apps\AICoded\ComfyUI Chain Automator\ffmpeg.exe"),
]

EXCLUDES = [
    "torch", "torchvision", "torchaudio", "tensorflow", "transformers", "cv2",
    "scipy", "pandas", "matplotlib", "onnx", "onnxruntime", "triton", "IPython",
    "jupyter", "sklearn", "numba", "jax", "safetensors", "tokenizers", "einops",
    "av", "soundfile", "playwright", "numpy",
    # boto3/botocore are NOT excluded any more: model_sync.py needs them (v2.13.0)
]

VENV_PY = ROOT.parent / ".venv" / "Scripts" / "python.exe"
try:
    import PyQt6  # noqa: F401
    import PyInstaller  # noqa: F401
except ImportError:
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
        print(f"PyQt6/PyInstaller missing in {sys.executable}; re-running with {VENV_PY}")
        sys.exit(subprocess.call([str(VENV_PY), __file__, *sys.argv[1:]]))
    print("ERROR: PyQt6 and PyInstaller are required. Build with the repo .venv.")
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
        "--add-data", f"{ROOT / 'ui' / 'icons' / 'chevron_down.png'};ui/icons",
        "--collect-all", "PyQt6",
        "--hidden-import", "requests",
        "--hidden-import", "websocket",
        "--hidden-import", "PIL",
        "--hidden-import", "boto3",
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
    stale = OUTPUT / f"{APP_NAME}.old.exe"
    if stale.exists():
        try:
            stale.unlink()   # fails harmlessly if that old instance is still running
        except OSError:
            pass
    # A running EXE can't be overwritten, but Windows lets it be renamed —
    # so the deploy never has to wait for the user to close the app; the
    # next launch simply picks up the new file.
    if target.exists():
        try:
            with open(target, "ab"):
                pass
        except OSError:
            print("Deployed EXE is running — renaming it aside so the new build can land")
            target.replace(stale)
    shutil.copy2(exe_src, target)

    shutil.copy2(ROOT / "app_icon.ico", OUTPUT / "app_icon.ico")
    # Never overwrite the live config next to the deployed EXE.
    if not (OUTPUT / "video_creator_config.json").exists() and (ROOT / "video_creator_config.json").exists():
        shutil.copy2(ROOT / "video_creator_config.json", OUTPUT / "video_creator_config.json")
    # Ship ffmpeg next to the EXE (thumbnails, last-frame, stitching).
    if not (OUTPUT / "ffmpeg.exe").exists():
        for src in FFMPEG_SOURCES:
            if src.exists():
                shutil.copy2(src, OUTPUT / "ffmpeg.exe")
                print(f"Copied ffmpeg.exe from {src}")
                break
        else:
            print("WARNING: no ffmpeg.exe found to ship — set FFmpeg path in Settings or drop ffmpeg.exe next to the EXE")

    sync = Path(r"P:\Apps\AICoded\Sync-StartMenuShortcuts.ps1")
    if sync.exists():
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(sync)],
                       capture_output=True, text=True)
        print("Start Menu shortcuts synced")

    print(f"\nDeployed to: {OUTPUT}")
    print("Done.")


if __name__ == "__main__":
    main()
