"""IMDB Photo Downloader — GUI v1.2.8"""

VERSION = "1.2.8"

import csv
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

# When frozen by PyInstaller, Playwright resolves its browser cache relative
# to the ephemeral _MEI extraction folder instead of the normal persistent
# %LOCALAPPDATA%\ms-playwright location. Pin it before importing playwright
# so installed browsers are found across runs.
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"),
)

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QProgressBar, QCheckBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds, doubles each retry


def human_delay(lo: float, hi: float) -> None:
    """Sleep a randomized interval instead of a fixed one. Uniform, identical
    gaps between every request/scroll/download is itself a bot fingerprint on
    top of the headless-Chromium signals; jittering pacing looks (and is)
    less mechanical, and it's gentler on IMDB's servers too."""
    time.sleep(random.uniform(lo, hi))


def human_view_delay() -> None:
    """Sleep like someone actually looking at a photo before deciding to save
    it: never under 2s, usually 2-6s, occasionally lingering up to 10s. Used
    between image downloads, where a fixed sub-second gap is an obvious tell
    that cadence-monitoring can key on."""
    time.sleep(random.triangular(2.0, 10.0, 4.0))

# ------------------------------------------------------------------ #
# Colors / style
# ------------------------------------------------------------------ #

BG       = "#13131f"
BG_MED   = "#1c1c2e"
BG_LIGHT = "#252540"
ACCENT   = "#6c5ce7"
ACCENT_H = "#7d6ff0"
FG       = "#e0e0f0"
FG_DIM   = "#7070a0"
BORDER   = "#2e2e50"
SUCCESS  = "#4caf8a"
ERROR    = "#ff6b6b"

STYLESHEET = f"""
    QMainWindow, QWidget {{
        background-color: {BG};
        color: {FG};
        font-family: "Segoe UI";
        font-size: 10pt;
    }}
    QLabel {{ color: {FG}; }}
    QLineEdit {{
        background-color: {BG_LIGHT};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 10pt;
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton {{
        background-color: {ACCENT};
        color: white;
        font-weight: bold;
        border: none;
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 10pt;
    }}
    QPushButton:hover {{ background-color: {ACCENT_H}; }}
    QPushButton:disabled {{ background-color: {BG_LIGHT}; color: {FG_DIM}; }}
    QPushButton#cancel_btn {{
        background-color: {BG_LIGHT};
        color: {FG_DIM};
        border: 1px solid {BORDER};
    }}
    QPushButton#cancel_btn:hover {{ background-color: {ERROR}; color: white; }}
    QPushButton#browse_btn {{
        background-color: {BG_LIGHT};
        color: {FG_DIM};
        border: 1px solid {BORDER};
        padding: 6px 12px;
    }}
    QPushButton#browse_btn:hover {{ background-color: {BG_MED}; color: {FG}; }}
    QListWidget {{
        background-color: {BG_MED};
        color: {FG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        font-size: 9pt;
        font-family: Consolas;
        padding: 4px;
    }}
    QProgressBar {{
        background-color: {BG_LIGHT};
        border: 1px solid {BORDER};
        border-radius: 4px;
        height: 18px;
        text-align: center;
        color: white;
        font-size: 8pt;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 3px;
    }}
"""

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Path(__file__).parent resolves inside PyInstaller's ephemeral _MEI extraction
# folder when frozen, not next to the persistent EXE, so settings never survive
# a restart. Anchor to sys.executable's directory instead when frozen.
SETTINGS_FILE = (
    Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
) / "imdb_downloader_settings.json"


# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #

DEFAULT_SETTINGS = {
    "root_dir": "",
    "full_res_default": False,
    "window_w": 820,
    "window_h": 600,
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text()))
        except Exception:
            pass
    return settings


def save_settings(settings: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
    except Exception:
        pass


# ------------------------------------------------------------------ #
# Pure helpers (unit-testable without a browser)
# ------------------------------------------------------------------ #

def extract_id(url: str) -> tuple[str, str]:
    m = re.search(r"(tt|nm)\d+", url)
    if not m:
        raise ValueError(f"Could not find an IMDB title or name ID in: {url}")
    imdb_id = m.group()
    return imdb_id, "name" if imdb_id.startswith("nm") else "title"


def parse_url_queue(text: str) -> list[str]:
    """Split a multi-line textbox into a deduped, ordered list of non-blank URLs."""
    seen = []
    for line in text.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.append(line)
    return seen


def search_imdb(query: str) -> list[dict]:
    """Look up movie/show/person titles by name via IMDB's public autocomplete
    endpoint — the same JSON the site's own search box uses. Each result
    reports whether IMDB has poster art for it ("has_image"), which is a
    quick signal (not a guarantee) that its media gallery has photos too."""
    query = query.strip()
    if not query:
        return []
    key = re.sub(r"[^a-z0-9]", "", query.lower())
    first = key[:1] or "a"
    safe_q = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")
    if not safe_q:
        return []
    url = f"https://v2.sg.media-imdb.com/suggestion/{first}/{safe_q}.json"
    try:
        resp = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("d", []):
        imdb_id = item.get("id", "")
        if not re.match(r"^(tt|nm)\d+$", imdb_id):
            continue
        results.append({
            "id": imdb_id,
            "title": item.get("l", imdb_id),
            "year": item.get("y"),
            "type": item.get("q", ""),
            "has_image": "i" in item,
        })
    return results


def imdb_url_for_id(imdb_id: str) -> str:
    base = "name" if imdb_id.startswith("nm") else "title"
    return f"https://www.imdb.com/{base}/{imdb_id}/"


def parse_gallery_images(html: str) -> list[dict]:
    """Extract (full_res_url, caption, mediaviewer_url) entries from a gallery page's HTML."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen_urls = set()
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if "media-amazon.com" not in src or "_V1_" not in src:
            continue
        full = re.sub(r"\._V1_.*\.(jpg|jpeg|png)", r"._V1_.\1", src)
        if full in seen_urls:
            continue
        seen_urls.add(full)
        caption = (img.get("alt") or "").strip()
        mediaviewer_url = ""
        link = img.find_parent("a")
        if link:
            href = link.get("href", "")
            if "/mediaviewer/" in href:
                mediaviewer_url = href
        found.append({"url": full, "caption": caption, "mediaviewer_url": mediaviewer_url})
    return found


def extract_full_res_from_mediaviewer(html: str, fallback_url: str) -> str:
    """Given a mediaviewer page's HTML, find the largest available image URL."""
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return og["content"]
    return fallback_url


def write_manifest(out_dir: Path, rows: list[dict]) -> None:
    """Write manifest.csv and manifest.json describing each downloaded/skipped/failed image."""
    csv_path = out_dir / "manifest.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "filename", "source_url", "caption", "status"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    json_path = out_dir / "manifest.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def download_with_retry(url: str, dest: Path, retries: int = MAX_RETRIES) -> bool:
    """Download a URL to dest, retrying with exponential backoff on failure."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=30, stream=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return True
        except Exception:
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
    return False


# ------------------------------------------------------------------ #
# Worker thread
# ------------------------------------------------------------------ #

class DownloadWorker(QThread):
    log         = pyqtSignal(str)
    progress    = pyqtSignal(int, int)
    url_started = pyqtSignal(int, int, str)   # queue index, total, url
    url_done    = pyqtSignal(int, int, int, str)  # downloaded, skipped, failed, out_dir
    finished    = pyqtSignal(int, int, int, str)  # aggregate downloaded, skipped, failed, last_out_dir
    error       = pyqtSignal(str)

    def __init__(self, urls: list[str], root_dir: Path, full_res: bool = False):
        super().__init__()
        self._urls = urls
        self._root_dir = root_dir
        self._full_res = full_res
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total_downloaded = total_skipped = total_failed = 0
        last_out_dir = ""

        for qi, url in enumerate(self._urls, 1):
            if self._cancelled:
                self.log.emit("Cancelled.")
                break

            self.url_started.emit(qi, len(self._urls), url)

            try:
                imdb_id, id_type = extract_id(url)
            except ValueError as e:
                self.error.emit(str(e))
                continue

            try:
                title_name, images = self._scrape(imdb_id, id_type)
            except Exception as e:
                self.error.emit(f"Scrape failed for {url}: {e}")
                continue

            if not images:
                self.error.emit(f"No images found on {url}.")
                continue

            safe = re.sub(r'[<>:"/\\|?*]', "_", title_name)
            out = self._root_dir / safe
            out.mkdir(parents=True, exist_ok=True)
            self.log.emit(f"Saving to: {out}")

            downloaded = skipped = failed = 0
            manifest_rows = []
            total = len(images)

            for i, entry in enumerate(images, 1):
                if self._cancelled:
                    self.log.emit("Cancelled.")
                    break

                dest = out / f"{safe}_{i:04d}.jpg"
                status = ""
                if dest.exists():
                    skipped += 1
                    status = "skipped"
                    self.log.emit(f"[{i}/{total}] Skip: {dest.name}")
                else:
                    if download_with_retry(entry["url"], dest):
                        downloaded += 1
                        status = "downloaded"
                        self.log.emit(f"[{i}/{total}] OK: {dest.name}")
                    else:
                        failed += 1
                        status = "failed"
                        self.log.emit(f"[{i}/{total}] FAIL")
                    # Only pace after an actual request — skipped files never hit the network.
                    human_view_delay()

                manifest_rows.append({
                    "index": i,
                    "filename": dest.name,
                    "source_url": entry["url"],
                    "caption": entry.get("caption", ""),
                    "status": status,
                })

                self.progress.emit(i, total)

            write_manifest(out, manifest_rows)
            self.log.emit(f"Manifest written: {out / 'manifest.csv'}")

            total_downloaded += downloaded
            total_skipped += skipped
            total_failed += failed
            last_out_dir = str(out)
            self.url_done.emit(downloaded, skipped, failed, str(out))

        self.finished.emit(total_downloaded, total_skipped, total_failed, last_out_dir)

    def _scrape(self, imdb_id: str, id_type: str) -> tuple[str, list[dict]]:
        images: list[dict] = []
        title_name = imdb_id
        base = "name" if id_type == "name" else "title"

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=DOWNLOAD_HEADERS["User-Agent"],
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            # IMDB's AWS WAF bot-check inspects navigator.webdriver; headless
            # Chromium sets it true by default, which triggers a CAPTCHA wall
            # instead of the gallery. Masking it lets the real page load.
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            page.route("**/*.{woff,woff2,ttf,otf}", lambda r: r.abort())

            self.log.emit("Opening IMDB media gallery...")
            page.goto(f"https://www.imdb.com/{base}/{imdb_id}/mediaindex/",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(random.randint(1600, 2800))

            # Title
            try:
                og = page.query_selector("meta[property='og:title']")
                if og:
                    raw = og.get_attribute("content") or ""
                    title_name = raw.split(" - Photos")[0].strip()
            except Exception:
                pass
            self.log.emit(f"Title: {title_name}")

            # Page count
            total_pages = 1
            try:
                nums = []
                for el in page.query_selector_all("a.page-link, span.page-link"):
                    try:
                        nums.append(int(el.inner_text().strip()))
                    except Exception:
                        pass
                if nums:
                    total_pages = max(nums)
            except Exception:
                pass
            self.log.emit(f"Gallery pages: {total_pages}")

            def collect(pg):
                # Scroll to bottom repeatedly to trigger lazy loading
                prev_html = ""
                for _ in range(20):
                    pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    pg.wait_for_timeout(random.randint(650, 1400))
                    html = pg.content()
                    if html == prev_html:
                        break  # no new images loaded
                    prev_html = html
                return parse_gallery_images(prev_html)

            entries = collect(page)
            images.extend(entries)
            self.log.emit(f"Page 1/{total_pages} — {len(entries)} images")

            for pg_num in range(2, total_pages + 1):
                if self._cancelled:
                    break
                page.goto(
                    f"https://www.imdb.com/{base}/{imdb_id}/mediaindex/?page={pg_num}",
                    wait_until="domcontentloaded"
                )
                entries = collect(page)
                images.extend(entries)
                self.log.emit(f"Page {pg_num}/{total_pages} — {len(entries)} images")
                human_delay(0.8, 2.2)

            if self._full_res:
                self.log.emit("Fetching full-resolution images (visiting each photo page)...")
                for entry in images:
                    if self._cancelled:
                        break
                    if not entry["mediaviewer_url"]:
                        continue
                    try:
                        mv_url = entry["mediaviewer_url"]
                        if mv_url.startswith("/"):
                            mv_url = f"https://www.imdb.com{mv_url}"
                        page.goto(mv_url, wait_until="domcontentloaded")
                        page.wait_for_timeout(random.randint(350, 900))
                        entry["url"] = extract_full_res_from_mediaviewer(page.content(), entry["url"])
                    except Exception:
                        pass  # keep gallery-resolution fallback already in entry["url"]

            browser.close()

        # de-dupe by final url, preserving order
        deduped = []
        seen = set()
        for entry in images:
            if entry["url"] not in seen:
                seen.add(entry["url"])
                deduped.append(entry)
        self.log.emit(f"Total unique images: {len(deduped)}")
        return title_name, deduped


# ------------------------------------------------------------------ #
# Main window
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker: DownloadWorker | None = None
        self._last_out_dir: Path | None = None
        self._settings = load_settings()

        self.setWindowTitle(f"IMDB Photo Downloader  v{VERSION}")
        self.setMinimumSize(700, 540)
        self.resize(
            self._settings.get("window_w", 820),
            self._settings.get("window_h", 600),
        )
        self.setStyleSheet(STYLESHEET)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Title
        title = QLabel("IMDB Photo Downloader")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size: 16pt; font-weight: bold; color: {ACCENT};")
        root.addWidget(title)

        sub = QLabel("Paste one or more IMDB title/actor URLs (one per line) — each saves to its own named subfolder")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {FG_DIM}; font-size: 9pt;")
        root.addWidget(sub)

        # Title/name search (find an IMDB URL by name instead of pasting one)
        search_row = QHBoxLayout()
        search_lbl = QLabel("Find:")
        search_lbl.setFixedWidth(90)
        search_lbl.setStyleSheet(f"color: {FG_DIM};")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Movie, show, or actor/actress name...")
        self._search_edit.returnPressed.connect(self._run_search)
        search_btn = QPushButton("🔍 Search")
        search_btn.setObjectName("browse_btn")
        search_btn.clicked.connect(self._run_search)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self._search_edit)
        search_row.addWidget(search_btn)
        root.addLayout(search_row)

        self._search_results = QListWidget()
        self._search_results.setFixedHeight(110)
        self._search_results.setVisible(False)
        self._search_results.itemDoubleClicked.connect(self._add_search_result)
        root.addWidget(self._search_results)

        search_hint = QLabel("📷 = IMDB has poster art for this result (not a guarantee its gallery has photos) · double-click to add its URL below")
        search_hint.setStyleSheet(f"color: {FG_DIM}; font-size: 8pt; font-style: italic;")
        search_hint.setVisible(False)
        self._search_hint = search_hint
        root.addWidget(search_hint)

        # URL queue input
        self._url_edit = QPlainTextEdit()
        self._url_edit.setPlaceholderText(
            "https://www.imdb.com/title/tt2543796/\nhttps://www.imdb.com/name/nm1760388/\n..."
        )
        self._url_edit.setFixedHeight(80)
        root.addWidget(self._url_edit)

        # Full-resolution option + clear search results
        full_res_row = QHBoxLayout()
        self._full_res_chk = QCheckBox("Grab full-resolution images (slower — visits each photo page)")
        self._full_res_chk.setStyleSheet(f"color: {FG_DIM};")
        self._full_res_chk.setChecked(bool(self._settings.get("full_res_default", False)))
        self._full_res_chk.toggled.connect(self._on_full_res_toggled)
        clear_results_btn = QPushButton("Clear List")
        clear_results_btn.setObjectName("browse_btn")
        clear_results_btn.setFixedWidth(110)
        clear_results_btn.clicked.connect(self._clear_search_results)
        full_res_row.addWidget(self._full_res_chk)
        full_res_row.addStretch()
        full_res_row.addWidget(clear_results_btn)
        root.addLayout(full_res_row)

        # Root folder row
        root_row = QHBoxLayout()
        root_lbl = QLabel("Root Folder:")
        root_lbl.setFixedWidth(90)
        root_lbl.setStyleSheet(f"color: {FG_DIM};")
        self._root_edit = QLineEdit(self._settings.get("root_dir", ""))
        self._root_edit.setPlaceholderText("Select a root download folder...")
        self._root_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("browse_btn")
        browse_btn.clicked.connect(self._browse_root)
        root_row.addWidget(root_lbl)
        root_row.addWidget(self._root_edit)
        root_row.addWidget(browse_btn)
        root.addLayout(root_row)

        # Info label
        self._root_info = QLabel("Downloads will be saved to:  <root folder> / <title name> /")
        self._root_info.setStyleSheet(f"color: {FG_DIM}; font-size: 8pt; font-style: italic;")
        root.addWidget(self._root_info)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._go_btn = QPushButton("⬇  Download")
        self._go_btn.setFixedHeight(42)
        self._go_btn.clicked.connect(self._start)
        self._cancel_btn = QPushButton("✕  Cancel")
        self._cancel_btn.setObjectName("cancel_btn")
        self._cancel_btn.setFixedHeight(42)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self._go_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        # Status log
        self._log = QListWidget()
        root.addWidget(self._log, stretch=1)

        # Bottom status
        self._status = QLabel("Ready")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {FG_DIM}; font-size: 9pt;")
        root.addWidget(self._status)

        # Clickable output folder link
        self._folder_link = QLabel("")
        self._folder_link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._folder_link.setStyleSheet(
            f"color: {ACCENT}; font-size: 9pt; text-decoration: underline;"
        )
        self._folder_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._folder_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._folder_link.mousePressEvent = self._open_folder
        self._folder_link.setWordWrap(True)
        root.addWidget(self._folder_link)

    def _run_search(self):
        query = self._search_edit.text().strip()
        self._search_results.clear()
        if not query:
            self._search_results.setVisible(False)
            self._search_hint.setVisible(False)
            return

        self._status.setText(f"Searching IMDB for \"{query}\"...")
        QApplication.processEvents()
        results = search_imdb(query)

        if not results:
            self._search_results.setVisible(False)
            self._search_hint.setVisible(False)
            self._status.setText(f"No matches found for \"{query}\".")
            return

        for r in results[:20]:
            year = f" ({r['year']})" if r.get("year") else ""
            cam = "📷" if r["has_image"] else "  "
            label = f"{cam} {r['title']}{year} — {r['type']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self._search_results.addItem(item)

        self._search_results.setVisible(True)
        self._search_hint.setVisible(True)
        self._status.setText(f"Found {len(results)} match(es).")

    def _clear_search_results(self):
        self._search_results.clear()
        self._search_results.setVisible(False)
        self._search_hint.setVisible(False)

    def _add_search_result(self, item: QListWidgetItem):
        imdb_id = item.data(Qt.ItemDataRole.UserRole)
        url = imdb_url_for_id(imdb_id)
        existing = self._url_edit.toPlainText()
        if url in existing.splitlines():
            self._status.setText("That URL is already in the queue.")
            return
        sep = "\n" if existing.strip() else ""
        self._url_edit.setPlainText(existing + sep + url)
        self._status.setText(f"Added: {url}")

    def _on_full_res_toggled(self, checked: bool):
        self._settings["full_res_default"] = checked
        save_settings(self._settings)

    def _browse_root(self):
        current = self._root_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Root Download Folder", current)
        if folder:
            self._root_edit.setText(folder)
            self._settings["root_dir"] = folder
            save_settings(self._settings)

    def _start(self):
        urls = parse_url_queue(self._url_edit.toPlainText())
        if not urls:
            self._status.setText("Paste at least one IMDB URL first.")
            return

        root_dir_str = self._root_edit.text().strip()
        if not root_dir_str:
            self._status.setText("Please select a root folder first.")
            return

        root_dir = Path(root_dir_str)

        self._log.clear()
        self._folder_link.setText("")
        self._progress.setRange(0, 0)
        self._go_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._status.setText("Working...")

        self._worker = DownloadWorker(urls, root_dir, full_res=self._full_res_chk.isChecked())
        self._worker.log.connect(self._on_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.url_started.connect(self._on_url_started)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)
        self._status.setText("Cancelling...")

    def _on_log(self, msg: str):
        self._log.addItem(msg)
        self._log.scrollToBottom()

    def _on_url_started(self, index: int, total: int, url: str):
        self._on_log(f"— URL {index}/{total}: {url}")

    def _on_progress(self, current: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._status.setText(f"Downloading... {current}/{total}")

    def _on_finished(self, downloaded: int, skipped: int, failed: int, out_dir: str):
        self._last_out_dir = Path(out_dir) if out_dir else None
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._go_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._status.setText(
            f"Done — Downloaded: {downloaded}  Skipped: {skipped}  Failed: {failed}"
        )
        self._on_log(f"✅ Complete — {downloaded} downloaded, {skipped} skipped, {failed} failed")
        if out_dir:
            self._folder_link.setText(f"📁 {out_dir}  (click to open in Explorer)")

    def _on_error(self, msg: str):
        self._go_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._status.setText(f"Error: {msg}")
        self._on_log(f"❌ Error: {msg}")

    def _open_folder(self, event=None):
        if self._last_out_dir and self._last_out_dir.exists():
            subprocess.Popen(f'explorer "{self._last_out_dir}"')

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._settings["window_w"] = self.width()
        self._settings["window_h"] = self.height()
        save_settings(self._settings)
        event.accept()


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    # Own taskbar identity so Windows doesn't group us under python.exe.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IMDBPhotoDownloader.App.1")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("IMDB Photo Downloader")
    # Bundled icon: PyInstaller's unpack folder when frozen, else next to the script.
    from PyQt6.QtGui import QIcon
    _icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app_icon.ico"
    _icon = QIcon(str(_icon_path)) if _icon_path.exists() else QIcon()
    app.setWindowIcon(_icon)
    window = MainWindow()
    window.setWindowIcon(_icon)
    window.show()
    sys.exit(app.exec())
