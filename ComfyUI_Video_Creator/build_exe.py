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
import time
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
APP_NAME = "ComfyUI_Video_Creator"
INTERNAL = "_internal"                           # one-folder build: the runtime lives here
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


def deploy(built: Path, output: Path):
    """Swap the EXE and its _internal folder into `output`. What was there is
    kept under timestamped .bak names (never overwritten, never deleted);
    settings and data beside the EXE are not touched. The app must be closed:
    a running one-folder app has its libraries loaded from _internal."""
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{APP_NAME}.exe"
    internal = output / INTERNAL
    if target.exists():
        try:
            with open(target, "ab"):
                pass
        except OSError:
            print(f"ERROR: {target} is running. Close the app, then build again.")
            sys.exit(1)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    moved: list[tuple[Path, Path]] = []          # (backup, original)
    try:
        for current, backup in ((internal, output / f"{INTERNAL}_{stamp}.bak"),
                                (target, output / f"{APP_NAME}_{stamp}.exe.bak")):
            if current.exists():
                current.rename(backup)
                moved.append((backup, current))
                print(f"Backed up {current.name} -> {backup.name}")
        shutil.copytree(built / INTERNAL, internal)
        shutil.copy2(built / target.name, target)
    except OSError as e:
        print(f"ERROR: deploy failed ({e}) — putting the previous version back")
        for backup, original in moved:
            if original.is_dir():
                shutil.rmtree(original)          # the half-copied new one
            backup.replace(original)
        sys.exit(1)


def main():
    print(f"Building {APP_NAME} v{version_from_main()} with {sys.executable} ...")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir", "--contents-directory", INTERNAL, "--windowed",
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

    built = DIST / APP_NAME                      # one-folder build output
    exe_src = built / f"{APP_NAME}.exe"
    if not exe_src.exists() or not (built / INTERNAL).is_dir():
        print("EXE or _internal not found in dist/ — check the PyInstaller output above")
        sys.exit(1)
    size = sum(f.stat().st_size for f in built.rglob("*") if f.is_file())
    print(f"Built {built} ({size // (1024 * 1024)} MB in the folder)")
    if "--no-deploy" in sys.argv:
        print(f"--no-deploy: leaving it in dist/, {OUTPUT} untouched")
        return

    deploy(built, OUTPUT)

    shutil.copy2(ROOT / "app_icon.ico", OUTPUT / "app_icon.ico")
    # Never overwrite the live config next to the deployed EXE.
    if not (OUTPUT / "video_creator_config.json").exists() and (ROOT / "video_creator_config.json").exists():
        shutil.copy2(ROOT / "video_creator_config.json", OUTPUT / "video_creator_config.json")
    # Ship ffmpeg next to the EXE (thumbnails, video details).
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
