"""
make_icons.py — Generate app icons via ComfyUI + convert to .ico

Saves:
  - PNG  ->  IconMaker/output/<AppName>.png
  - ICO  ->  IconMaker/output/<AppName>.ico  (16,32,48,256)
  - ICO is also copied to the project folder as app_icon.ico
"""

import datetime
import json
import os
import random
import shutil
import time
import urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
COMFY_URL     = os.environ.get("COMFY_URL", "http://127.0.0.1:8000")
COMFY_OUTPUT  = Path("P:/AI/ComfyLocal/ComfyUI_windows_portable/ComfyUI/output")
OUTPUT_DIR    = Path(__file__).parent / "output"
WORKFLOW_FILE = Path(__file__).parent / "qwen_T2Image_2512_API.json"
PROJECTS_ROOT = Path(__file__).parent.parent
ICO_SIZES     = [16, 32, 48, 256]
PROMPT_HISTORY_FILE = OUTPUT_DIR / "prompt_history.json"
SKIP_PROJECT_DIRS = {".venv", ".git", "__pycache__", "IconMaker", "node_modules", "output"}

# ── App definitions ───────────────────────────────────────────────────────────
APPS = [
    {
        "name": "Calculator",
        "project_folder": "Calculator",
        "prompt": (
            "Minimalist flat app icon, dark blue background #1a1a2e, "
            "a glowing white calculator with illuminated digit display showing numbers, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "DesktopVideoBrowser",
        "project_folder": "Desktop Video Browser",
        "prompt": (
            "Minimalist flat app icon, dark charcoal background #1c1c1c, "
            "a glowing film strip with a play button overlaid on a folder, "
            "representing video file browsing, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FaceFinder",
        "project_folder": "FaceFinder",
        "prompt": (
            "Minimalist flat app icon, deep dark teal background #0d1f1f, "
            "a glowing face silhouette inside a circular target/scan reticle, "
            "representing AI face detection, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FileCopyManager",
        "project_folder": "File Copy Manager",
        "prompt": (
            "Minimalist flat app icon, dark blue-grey background #1a1a2e, "
            "two glowing file document silhouettes with a bright arrow copying "
            "from one to the other, clean vector style, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FileHashDedupe",
        "project_folder": "File Hash Dedupe",
        "prompt": (
            "Minimalist flat app icon, dark green background #0d1f0d, "
            "two overlapping glowing file document silhouettes with a fingerprint "
            "symbol between them representing duplicate detection, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FileRenameMover",
        "project_folder": "File Rename Mover",
        "prompt": (
            "Minimalist flat app icon, dark purple background #1a0d2e, "
            "a glowing file document with a pencil editing the filename and "
            "a small arrow showing movement, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FileFinder",
        "project_folder": "FileFinder",
        "prompt": (
            "Minimalist flat app icon, dark indigo background #0d0d2e, "
            "a glowing magnifying glass over a stack of file documents, "
            "representing file search across drives, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FilePropertiesUpdater",
        "project_folder": "FilePropertiesUpdater",
        "prompt": (
            "Minimalist flat app icon, dark slate background #1a1a1a, "
            "a glowing MP4 film frame with a small wrench or edit symbol, "
            "representing metadata editing, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FirstFrameMp4",
        "project_folder": "First Frame mp4",
        "prompt": (
            "Minimalist flat app icon, dark navy background #0d0d1f, "
            "a glowing film strip with the first frame highlighted and a "
            "camera shutter symbol, representing frame extraction from video, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "Games",
        "project_folder": "Games",
        "prompt": (
            "Minimalist flat app icon, dark space black background #0a0a0f, "
            "a glowing white rocket with landing legs descending toward a platform "
            "with exhaust flames, representing Falcon 9 landing simulation, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ImagePeopleSorter",
        "project_folder": "Image People Sorter",
        "prompt": (
            "Minimalist flat app icon, dark warm background #1f1408, "
            "a glowing person silhouette being sorted into a folder with an "
            "arrow, representing AI people detection and image sorting, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ImageResize",
        "project_folder": "Image Resize",
        "prompt": (
            "Minimalist flat app icon, dark teal background #081f1f, "
            "a glowing image frame with resize arrows pointing outward from "
            "the corners, representing batch image resizing, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ImageDedupeSearch",
        "project_folder": "Image_Dedupe_Search",
        "prompt": (
            "Minimalist flat app icon, dark purple-black background #120d1f, "
            "two overlapping glowing image frames with a neural network node "
            "pattern between them representing AI duplicate image detection, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "LunarLander",
        "project_folder": "Games/Lunar_Lander",
        "prompt": (
            "Minimalist flat app icon, dark space background #050510, "
            "a glowing lunar lander module descending toward a cratered moon "
            "surface with stars, clean vector style, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "MissileCommandGame",
        "project_folder": "MissileCommandGame",
        "prompt": (
            "Minimalist flat app icon, dark olive-black background #0f0f05, "
            "glowing incoming missiles as streaks from the top with "
            "explosion bursts defending cities at the bottom, "
            "classic arcade style, clean vector, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "NAS_Backup",
        "project_folder": "NAS_Backup",
        "prompt": (
            "Minimalist flat app icon, dark navy blue background #0e1a2b, "
            "a glowing teal shield with a checkmark and a small clock symbol "
            "inside representing reliable scheduled backup, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "NetworkToggleStatus",
        "project_folder": "NetworkToggleStatus",
        "prompt": (
            "Minimalist flat app icon, dark gunmetal background #0f1418, "
            "a glowing network topology with nodes and connections and a "
            "toggle switch symbol, representing network adapter control, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "PictureFlipper",
        "project_folder": "Picture_Fipper",
        "prompt": (
            "Minimalist flat app icon, dark warm grey background #1a1510, "
            "a glowing image frame with a person silhouette and two mirrored "
            "flip arrows, representing AI image orientation correction, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "StopWatch",
        "project_folder": "StopWatch",
        "prompt": (
            "Minimalist flat app icon, dark charcoal background #141414, "
            "a glowing stopwatch with a bold sweep hand and lap tick marks, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "Unzipper",
        "project_folder": "Unzipper",
        "prompt": (
            "Minimalist flat app icon, dark brown background #1a1005, "
            "a glowing ZIP archive being opened with files bursting outward "
            "and an unzip arrow, clean vector style, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ComfyUI_Metadata_Viewer",
        "project_folder": "ComfyUI_Metadata_Viewer",
        "prompt": (
            "Minimalist flat app icon, dark retro background #1a0a1a, "
            "a glowing VHS tape cassette with a small code bracket symbol "
            "representing metadata parsing, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "AIImageGenerator",
        "project_folder": "AI_Image_Generator",
        "prompt": (
            "Minimalist flat app icon, dark deep purple background #120a1f, "
            "a glowing neural network pattern forming a paintbrush stroke that "
            "transforms into a vivid landscape image, representing AI image generation, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ClipboardQueueLoader",
        "project_folder": "clipboard-queue-loader",
        "prompt": (
            "Minimalist flat app icon, dark slate blue background #0d1520, "
            "a glowing clipboard with a stacked queue of items and a bright "
            "loading arrow, representing clipboard history management, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ComfyUIWorkflowEditor",
        "project_folder": "Cumfy_Workflow_Editor",
        "prompt": (
            "Minimalist flat app icon, dark charcoal background #111111, "
            "glowing node graph with connecting lines and edit cursor, "
            "representing a visual workflow editor for AI pipelines, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ComfyUIChainAutomator",
        "project_folder": "ComfyUI_Chain_Automator",
        "prompt": (
            "Minimalist flat app icon, dark navy background #0a0f1f, "
            "a glowing chain of connected film frames with a play button "
            "and automation arrows, representing automated video segment chaining, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FolderBackupArchiver",
        "project_folder": "7z_Folder_backup",
        "prompt": (
            "Minimalist flat app icon, dark forest green background #0a1a0a, "
            "a glowing folder with a zipper and a shield checkmark, "
            "representing compressed folder backup and archiving, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "IMDBPhotoDownloader",
        "project_folder": "IMDB_Scraper",
        "prompt": (
            "Minimalist flat app icon, dark amber background #1a1200, "
            "a glowing movie star silhouette with a downward arrow and "
            "a film reel, representing celebrity photo downloading, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "BulkFileRandomizer",
        "project_folder": "Bulk File Randomizer",
        "prompt": (
            "Minimalist flat app icon, dark midnight blue background #0d0d2e, "
            "a glowing stack of file documents with shuffle arrows swirling "
            "around them representing random file renaming and ordering, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "Asteroids",
        "project_folder": "Games/Asteorids",
        "prompt": (
            "Minimalist flat app icon, deep space black background #050508, "
            "a glowing white vector triangle spaceship firing bullets at "
            "jagged asteroid rocks in a classic arcade style, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "JPG2PNG",
        "project_folder": "JPG2PNG_Converter",
        "prompt": (
            "Minimalist flat app icon, dark teal background #081a18, "
            "a glowing JPG badge transforming with a bright arrow into a "
            "PNG badge with transparency checkerboard, representing image "
            "format conversion, clean vector style, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ScreenSnap",
        "project_folder": "ScreenSnap",
        "prompt": (
            "Minimalist flat app icon, dark charcoal background #0f0f0f, "
            "a glowing monitor screen with a crosshair selection marquee and "
            "a small annotation arrow pointing to a highlighted region, "
            "representing screen capture and annotation, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "WinFolderMover",
        "project_folder": "WinFolderMover",
        "prompt": (
            "Minimalist flat app icon, dark crimson red background #2b1010, "
            "a glowing white arrow pointing right with a folder silhouette "
            "being pushed across, clean vector style, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "ComfyUIStyleRandomizer",
        "project_folder": "ComfyUI_Style_Randomizer",
        "prompt": (
            "Minimalist flat app icon, dark indigo background #0d0d1a, "
            "a glowing image frame with a paint palette overlaid and swirling "
            "colorful style strokes radiating outward with a dice symbol in the "
            "corner representing random style selection, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "PromptEnhancer",
        "project_folder": "PromptEnhancer",
        "prompt": (
            "Minimalist flat app icon, dark violet background #14103a, "
            "a glowing magic wand with a sparkle trail transforming a plain "
            "line of text into a glowing structured paragraph, representing "
            "AI prompt writing and enhancement, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "TodoList",
        "project_folder": "TodoList",
        "prompt": (
            "Minimalist flat app icon, dark navy background #1a1a2e, "
            "a glowing violet checklist clipboard with two checked boxes in "
            "bright green and one empty box, purple #7b2fff and lavender accents, "
            "representing a simple to-do list, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "S3Browser",
        "project_folder": "S3_Broswer",
        "prompt": (
            "Minimalist flat app icon, dark slate navy background #0d1626, "
            "a glowing cyan cloud with a folder and file document hanging below it "
            "connected by thin lines, and a small upload/download arrow pair, "
            "representing browsing cloud object storage, "
            "clean vector style, no text, square icon, sharp edges, "
            "modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "FolderSync",
        "project_folder": "FolderSync",
        "prompt": (
            "Minimalist flat app icon, deep dark plum background #1a0a1c, "
            "two glowing hot magenta circular arrows chasing each other in a "
            "continuous sync loop, with a small folder tab on the left and right "
            "of the loop, neon pink #ff2d95 glow, representing two-way folder "
            "synchronization, clean vector style, no text, square icon, "
            "sharp edges, modern Windows app icon design, 512x512"
        ),
    },
    {
        "name": "IconMaker",
        "project_folder": "IconMaker",
        "prompt": (
            "Minimalist flat app icon, dark charcoal background #0f140a, "
            "a glowing electric lime green #b6ff00 blacksmith anvil with a small "
            "rounded-square app icon tile being forged on top and bright sparks "
            "flying, representing an icon generator, clean vector style, no text, "
            "square icon, sharp edges, modern Windows app icon design, 512x512"
        ),
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_workflow() -> dict:
    with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def submit_prompt(workflow: dict) -> str:
    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    return result["prompt_id"]


def wait_for_completion(prompt_id: str, timeout: int = 600) -> bool:
    print(f"  Waiting", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}") as resp:
            history = json.loads(resp.read())
        if prompt_id in history:
            print(" done.")
            return True
        print(".", end="", flush=True)
    print(" TIMEOUT.")
    return False


def get_output_filename(prompt_id: str) -> str | None:
    with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}") as resp:
        history = json.loads(resp.read())
    entry = history.get(prompt_id, {})
    for node_output in entry.get("outputs", {}).values():
        images = node_output.get("images", [])
        if images:
            return images[0]["filename"]
    return None


def build_ico_image(png_path: Path, padding_pct: int = 0, corner_radius_pct: int = 0):
    """Load a PNG and apply optional padding (shrink onto a transparent canvas)
    and rounded corners, returning a PIL Image ready to save as .ico."""
    from PIL import Image, ImageChops, ImageDraw

    img = Image.open(png_path).convert("RGBA")
    size = img.size[0]

    if padding_pct > 0:
        pad = int(size * padding_pct / 100)
        inner_size = max(1, size - 2 * pad)
        resized = img.resize((inner_size, inner_size), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(resized, (pad, pad), resized)
        img = canvas

    if corner_radius_pct > 0:
        radius = int(size * corner_radius_pct / 100)
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
        img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))

    return img


def convert_to_ico(png_path: Path, ico_path: Path, padding_pct: int = 0, corner_radius_pct: int = 0) -> None:
    img = build_ico_image(png_path, padding_pct, corner_radius_pct)
    img.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"  ICO  -> {ico_path.name}")


def load_prompt_history() -> dict:
    if PROMPT_HISTORY_FILE.exists():
        try:
            return json.loads(PROMPT_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def append_prompt_history(app_name: str, prompt: str, seed: int) -> None:
    history = load_prompt_history()
    history.setdefault(app_name, []).append({
        "prompt": prompt,
        "seed": seed,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    OUTPUT_DIR.mkdir(exist_ok=True)
    PROMPT_HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def find_projects_missing_icon(projects_root: Path = PROJECTS_ROOT) -> list[str]:
    """List project folders (containing at least one .py file) that aren't
    already in APPS and don't have an app_icon.ico yet."""
    known_folders = {app["project_folder"] for app in APPS}
    missing = []
    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_PROJECT_DIRS or entry.name.startswith("."):
            continue
        if entry.name in known_folders:
            continue
        if not any(entry.glob("*.py")):
            continue
        if (entry / "app_icon.ico").exists():
            continue
        missing.append(entry.name)
    return missing


# ── Main ──────────────────────────────────────────────────────────────────────

NEW_APPS = {
    "FolderSync",
    "IconMaker",
}


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    base_workflow = load_workflow()

    apps_to_run = [a for a in APPS if a["name"] in NEW_APPS]
    total = len(apps_to_run)
    for idx, app in enumerate(apps_to_run, 1):
        name           = app["name"]
        project_folder = PROJECTS_ROOT / app["project_folder"]

        print(f"\n[{idx}/{total}] {name}")
        print("-" * 40)

        # Build workflow
        workflow = json.loads(json.dumps(base_workflow))
        workflow["91"]["inputs"]["value"]        = app["prompt"]
        workflow["86:3"]["inputs"]["seed"]        = random.randint(1, 2**31)
        workflow["86:58"]["inputs"]["width"]      = 512
        workflow["86:58"]["inputs"]["height"]     = 512
        workflow["60"]["inputs"]["filename_prefix"] = f"icon_{name}"
        # Local ComfyUI now ships Qwen-Image 2.1 instead of the 2512 files the
        # workflow JSON names, so point the loaders at what is installed.
        workflow["86:37"]["inputs"]["unet_name"]  = "qwen_image_2.1_int8_convrot.safetensors"
        workflow["86:38"]["inputs"]["clip_name"]  = "qwen3vl_8b_int8_convrot.safetensors"
        workflow["86:39"]["inputs"]["vae_name"]   = "qwen_image_2.1_vae_bf16.safetensors"

        # Submit
        prompt_id = submit_prompt(workflow)

        # Wait
        if not wait_for_completion(prompt_id):
            print(f"  SKIPPED — timed out")
            continue

        # Get filename
        filename = get_output_filename(prompt_id)
        if not filename:
            print(f"  SKIPPED — no output filename found")
            continue

        # Copy PNG
        src_png = COMFY_OUTPUT / filename
        dst_png = OUTPUT_DIR / f"{name}.png"
        shutil.copy2(src_png, dst_png)
        print(f"  PNG  -> {dst_png.name}")

        # Convert to ICO
        ico_path = OUTPUT_DIR / f"{name}.ico"
        convert_to_ico(dst_png, ico_path)

        # Copy ICO into project folder
        if project_folder.exists():
            project_ico = project_folder / "app_icon.ico"
            shutil.copy2(ico_path, project_ico)
            print(f"  COPY -> {project_folder.name}/app_icon.ico")
        else:
            print(f"  WARN — project folder not found: {project_folder}")

    print(f"\n{'=' * 40}")
    print(f"Done! {total} icons generated.")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
