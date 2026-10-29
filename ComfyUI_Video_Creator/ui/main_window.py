import tempfile
import time
from pathlib import Path

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressDialog, QPushButton, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

import alerts
import model_sync
from config import ConfigManager
from extend_marks import MARKS_NAME, ExtendMarks
from file_ops import archive_paths, delete_paths, thumbnail_caches
from media_tools import extract_thumbnail, resolve_ffmpeg
from run_worker import RunRequest, RunWorker, _base_stem, _workflow_labels
from workflow_folders import library_dir_for
from processed import processed_sources
from ui.library_tab import LibraryTab
from ui.pod_control import PodControl
from ui.prompt_history import source_for_result
from ui.queue_dialog import QueueDialog
from ui.run_panel import RunPanel
from ui.settings_dialog import SettingsDialog
from ui.styles import COLORS, STYLESHEET
from ui.video_player import VideoPlayerDialog
from ui.widgets import THUMB_SIZE, MediaBrowser
from workflow_tools import analyze, apply_inputs, apply_turbo_toggle, load_workflow

# Width that shows exactly two thumbnail columns: two grid cells plus the
# grid spacing, the list padding, the frame and a scrollbar.
TWO_COLUMN_WIDTH = 2 * (THUMB_SIZE + 14) + 3 * 4 + 12 + 2 + 14

# Tab positions. Library → Send to Extend and Reuse Settings jump by these.
TAB_INDEX = {"image": 0, "video": 1, "text": 2, "library": 3}


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager, version: str):
        super().__init__()
        self.config = config
        self.version = version
        self._worker: RunWorker | None = None
        self._active_panel: RunPanel | None = None
        self._active_req: RunRequest | None = None
        self._queue: list[RunRequest] = []
        self._batch_runs = 0            # runs since the app was last idle; 2+ = a queue, alerted on finish
        self._queue_dlg: QueueDialog | None = None
        # Model check & sync (RunPod mode): requests wait here while the
        # workflow's model files are compared with the pod volume and any
        # missing ones copied across; then they go through _start_checked.
        self._model_queue: list[RunRequest] = []
        self._model_batch: list[RunRequest] = []
        self._model_check: model_sync.ModelCheckWorker | None = None
        self._model_check_scheduled = False
        self._transfer: model_sync.TransferWorker | None = None
        self._transfer_dlg: QProgressDialog | None = None
        self._xfer_mark: tuple[str, float, int] = ("", 0.0, 0)   # (label, t0, bytes) for the rate readout
        self._pod_only_declined: set[str] = set()                # "run on the pod" answers, this session
        self._player: VideoPlayerDialog | None = None
        self._tab_splitters: list[QSplitter] = []
        self._splits_initialised = False
        # kind -> RunPanel, filled by _build_ui; the tab order is the
        # TAB_INDEX order.
        self._panels: dict[str, RunPanel] = {}

        self.setWindowTitle(f"ComfyUI Video Creator v{version}")
        self.setStyleSheet(STYLESHEET)
        self.resize(1640, 960)
        # 1080p is the minimum supported screen; below ~860px tall the
        # prompt editors hit their floor and the Options group gets squeezed.
        self.setMinimumSize(1280, 860)
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _ffmpeg(self) -> str:
        return resolve_ffmpeg(self.config.get("ffmpeg_path", ""), Path(self.config.get("_base_dir", ".")))

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("ComfyUI Video Creator")
        title.setObjectName("header")
        header.addWidget(title)
        sub = QLabel(f"v{self.version}  ·  single-shot ComfyUI API workflows: "
                     "image → video, video → extension, text → video")
        sub.setObjectName("subtitle")
        header.addWidget(sub)
        header.addStretch()
        self._mode_lbl = QLabel("")
        self._mode_lbl.setObjectName("subtitle")
        header.addWidget(self._mode_lbl)
        self._pod = PodControl(self.config, self._generation_running, self)
        self._pod.server_changed.connect(self._update_mode_label)
        self._pod.log.connect(self._log_everywhere)
        header.addWidget(self._pod)
        refresh_btn = QPushButton("↻ Lists")
        refresh_btn.setObjectName("secondary_btn")
        refresh_btn.setToolTip("Rescan every list from disk and the server — workflows, LoRAs, "
                               "image and video folders, the Library (F5)")
        refresh_btn.clicked.connect(self.refresh_lists)
        header.addWidget(refresh_btn)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_lists)
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setObjectName("secondary_btn")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        # Sources already extended (or hidden by hand) — next to the config, like every other setting
        self._marks = ExtendMarks(self.config.config_path.parent / MARKS_NAME)
        self._tabs = QTabWidget()
        # Multi-select (here and on the Extend tab): every selected file becomes its own queued run.
        self._image_browser = MediaBrowser("image", self.config.get("image_dir", ""),
                                           self.config.get("image_sort", "Name A→Z"), self._ffmpeg,
                                           multi=True, processed_provider=lambda: self._processed_sources("image"))
        self._image_panel = RunPanel("image", self.config)
        self._tabs.addTab(self._make_tab(self._image_browser, self._image_panel), "🖼  Image → Video")

        self._video_browser = MediaBrowser("video", self.config.get("video_dir", ""),
                                           self.config.get("video_sort", "Newest First"), self._ffmpeg,
                                           multi=True, processed_provider=lambda: self._processed_sources("video"),
                                           recursive=True,     # per-workflow output lives in subfolders
                                           extend_tools=True,
                                           hide_clips=bool(self.config.get("extend_hide_clips", True)),
                                           hint="Thumbnails show each video's LAST frame — the extension's starting point")
        self._video_panel = RunPanel("video", self.config)
        self._tabs.addTab(self._make_tab(self._video_browser, self._video_panel), "🎬  Video → Extend")

        # Text → Video has nothing to pick from, so no thumbnail browser: the
        # run panel — and its prompt editor — gets the whole tab.
        self._text_panel = RunPanel("text", self.config)
        text_page = QWidget()
        text_lay = QHBoxLayout(text_page)
        text_lay.setContentsMargins(8, 8, 8, 8)
        text_lay.addWidget(self._text_panel)
        self._tabs.addTab(text_page, "✍  Text → Video")
        self._panels = {"image": self._image_panel, "video": self._video_panel, "text": self._text_panel}

        for b in (self._video_browser, self._image_browser):
            b.deleting.connect(self._on_files_deleting)
            b.deleted.connect(self._on_files_deleted)
        self._video_browser.hide_requested.connect(self._hide_extended)
        self._video_browser.unhide_requested.connect(self._unhide_extended)
        self._video_browser.send_to_library_requested.connect(self._send_to_library)
        self._video_browser.hide_clips_changed.connect(self._on_hide_clips_changed)
        self._library = LibraryTab(self.config, self._ffmpeg)
        self._library.browser.deleting.connect(self._on_files_deleting)
        self._library.browser.deleted.connect(self._on_files_deleted)
        self._library.play_requested.connect(self._play_list)
        self._library.send_to_extend.connect(self._send_to_extend)
        self._library.reuse_requested.connect(self._reuse_settings)
        # A different Library folder changes which sources count as finished.
        self._library.folder_changed.connect(lambda _f: self._refresh_processed_pickers())
        # Videos were rearranged into workflow folders: the Extend picker lists them afresh.
        self._library.files_moved.connect(self._video_browser.refresh)
        self._library.files_moved.connect(self._refresh_processed_pickers)
        self._tabs.addTab(self._library, "📚  Library")
        root.addWidget(self._tabs, stretch=1)

        self.setCentralWidget(central)
        self._wire(self._image_browser, self._image_panel, "image_dir", "image_sort")
        self._wire(self._video_browser, self._video_panel, "video_dir", "video_sort")
        self._wire_panel(self._text_panel)
        # A clone made on one tab has to show up in the other tabs' dropdowns too.
        for source in self._panels.values():
            for other in self._panels.values():
                if other is not source:
                    source.workflows_changed.connect(other.refresh_workflow_list)
                    source.loras_changed.connect(other.apply_shared_loras)
        self._video_browser.activated.connect(lambda p: self._play(str(p)))
        # Switching workflow re-filters that tab's picker (an image only counts as done for the
        # workflow that made its video) and points the Library at the same workflow.
        for kind, panel in self._panels.items():
            panel.workflow_selected.connect(lambda rel, k=kind: self._on_workflow_selected(k, rel))
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._library.follow_workflow(self._image_panel.workflow_rel)
        self._update_mode_label()
        # Initial scans run after the signals above are wired so the run
        # panels see the restored selection state.
        self._image_browser.refresh()
        self._video_browser.refresh()
        self._library.refresh()

    def _refresh_processed_pickers(self):
        self._image_browser.refresh_processed()
        self._video_browser.refresh_processed()

    def _processed_sources(self, kind: str) -> set[str]:
        """Names of the source files the workflow selected on this tab has already
        turned into a video that is still in the Library — hidden in the picker.
        Other workflows' videos don't count, so the same image stays available
        until THIS workflow has made its own; and a Library folder with no
        videos in it un-hides everything."""
        done = processed_sources(self.config.get("workflow_dir", ""),
                                 self._library.effective_folder(),
                                 self._panels[kind].workflow_rel)
        if kind == "video":
            done |= self._marks.hidden_names()      # extended already / hidden by hand
        return done

    # -- Extend picker: keep track of one set of extensions at a time ------ #

    def _hide_extended(self, paths: list):
        n = self._marks.add(paths)
        self._video_browser.refresh_processed()
        self._video_panel.append_log(f"Hid {n} video{'s' if n != 1 else ''} from the Extend list "
                                     "(Show all brings them back, or select and Unhide)")

    def _unhide_extended(self, paths: list):
        n = self._marks.remove(paths)
        self._video_browser.refresh_processed()
        self._video_panel.append_log(f"Unhid {n} video{'s' if n != 1 else ''}")

    def _on_hide_clips_changed(self, on: bool):
        self.config.set("extend_hide_clips", bool(on))
        self.config.save()

    def _send_to_library(self, paths: list):
        """Extend tab → Library: move the picked (complete) videos into the Library
        folder, inside the active workflow's own folder, so they show up in the
        Library tab and count as that workflow's finished videos."""
        root = self._library.effective_folder()
        if not root:
            QMessageBox.information(self, "Send to Library",
                                    "Set a Library (or Output) folder in Settings first (Folders).")
            return
        root_p = Path(root)
        dest = (library_dir_for(root_p, self._video_panel.workflow_rel)
                if self.config.get("output_per_workflow", True) else root_p)

        def in_library(p: Path) -> bool:
            try:
                p.resolve().relative_to(root_p.resolve())
                return True
            except (ValueError, OSError):
                return False

        todo = [Path(p) for p in paths if not in_library(Path(p))]
        if not todo:
            QMessageBox.information(self, "Send to Library",
                                    "Already in the Library folder — nothing to move.")
            return
        names = "\n".join(p.name for p in todo[:8]) + ("\n…" if len(todo) > 8 else "")
        plural = "s" if len(todo) != 1 else ""
        ans = QMessageBox.question(
            self, "Send to Library",
            f"Move {len(todo)} video{plural} into the Library?\n\n{names}\n\n→ {dest}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._on_files_deleting(todo)           # close a player that has one of these open
        browser_root = Path(self._video_browser.folder) if self._video_browser.folder else None
        caches: list[Path] = []
        for p in todo:
            caches += thumbnail_caches(p, browser_root)
        try:
            moved, errors = archive_paths(todo, dest)      # moves, keeping names unique
        except OSError as e:
            QMessageBox.warning(self, "Send to Library", f"Could not create {dest}:\n{e}")
            return
        if caches:
            delete_paths(caches)                # re-made on demand in the new folder
        if errors:
            QMessageBox.warning(self, "Send to Library", "Some files could not be moved:\n" + "\n".join(errors))
        self._video_panel.append_log(f"Sent {len(moved)} video{'s' if len(moved) != 1 else ''} to the Library: {dest}")
        self._video_browser.refresh()
        self._library.refresh()
        self._refresh_processed_pickers()

    def _on_workflow_selected(self, kind: str, rel: str):
        browser = {"image": self._image_browser, "video": self._video_browser}.get(kind)
        if browser is not None:
            browser.refresh_processed()
        if self._tabs.currentIndex() == TAB_INDEX[kind]:
            self._library.follow_workflow(rel)

    def _on_tab_changed(self, index: int):
        for kind, panel in self._panels.items():
            if index == TAB_INDEX[kind]:
                self._library.follow_workflow(panel.workflow_rel)

    def _make_tab(self, browser: MediaBrowser, panel: RunPanel) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(browser)
        split.addWidget(panel)
        # Thumbnails start two columns wide; the prompt/settings panel takes
        # the rest. Drag the divider (or resize the window) for more thumbs.
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        lay.addWidget(split)
        self._tab_splitters.append(split)
        return page

    def showEvent(self, event):
        super().showEvent(event)
        if not self._splits_initialised:
            self._splits_initialised = True
            QTimer.singleShot(0, self._init_tab_splits)
            # After the window is actually on screen, so the prompt has a
            # parent to centre on rather than appearing behind it.
            QTimer.singleShot(200, self._pod.check_on_launch)

    def _generation_running(self) -> bool:
        # A model transfer counts: the pod is about to be used, so the idle
        # stop and the spend-limit stop must wait for it like a run.
        return ((self._worker is not None and self._worker.isRunning())
                or self._transfer is not None)

    def _log_everywhere(self, msg: str):
        """Pod progress isn't tied to any one tab, so it goes to every log."""
        for panel in self._panels.values():
            panel.append_log(msg)

    def _init_tab_splits(self):
        for split in self._tab_splitters:
            total = sum(split.sizes()) or split.width()
            if total > 0:
                split.setSizes([TWO_COLUMN_WIDTH, max(total - TWO_COLUMN_WIDTH, 560)])

    def _wire(self, browser: MediaBrowser, panel: RunPanel, dir_key: str, sort_key: str):
        browser.selection_paths_changed.connect(panel.set_sources)
        browser.folder_changed.connect(lambda f: (self.config.set(dir_key, f), self.config.save()))
        browser.sort_changed.connect(lambda s: (self.config.set(sort_key, s), self.config.save()))
        self._wire_panel(panel)

    def _wire_panel(self, panel: RunPanel):
        panel.run_requested.connect(self._start)
        panel.cancel_requested.connect(self._cancel)
        panel.clear_queue_requested.connect(self._clear_queue)
        panel.show_queue_requested.connect(self._show_queue)
        panel.set_queue_probe(self._queued_duplicate)
        panel.play_requested.connect(self._play)

    def refresh_lists(self):
        """F5 / ↻ Lists: everything that lists a folder or the server is
        rescanned, so a file renamed while the app runs shows up under its
        new name without a restart. Selections and unsaved edits are kept."""
        for panel in self._panels.values():
            panel.refresh_workflow_list()
        first = self._image_panel                 # the list is shared; one reload broadcasts
        first.reload_loras_from_folder(quiet=True)
        if self.config.server_url():
            first._fetch_loras_from_server()
        self._image_browser.refresh()
        self._video_browser.refresh()
        self._library.refresh()
        self._log_everywhere("Lists refreshed — workflows, LoRAs, image/video folders, Library")

    def _update_mode_label(self):
        mode = "RunPod" if self.config.is_runpod() else "Local"
        url = self.config.server_url() or "(no URL set)"
        color = COLORS['warning'] if self.config.is_runpod() else COLORS['success']
        self._mode_lbl.setText(f"<span style='color:{color}'>●</span> {mode}  <span style='color:{COLORS['fg_dim']}'>{url}</span>")

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    def _open_settings(self):
        before = {k: self.config.get(k) for k in ("image_dir", "video_dir", "workflow_dir", "ffmpeg_path", "loras_dir", "output_dir", "library_dir")}
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return
        self._update_mode_label()
        if self.config.get("image_dir") != before["image_dir"]:
            self._image_browser.set_folder(self.config.get("image_dir", ""))
        if self.config.get("video_dir") != before["video_dir"] or self.config.get("ffmpeg_path") != before["ffmpeg_path"]:
            self._video_browser.set_folder(self.config.get("video_dir", ""))
        if self.config.get("workflow_dir") != before["workflow_dir"]:
            for panel in self._panels.values():
                panel.reload_workflows()
        if (self.config.get("output_dir") != before["output_dir"]
                or self.config.get("library_dir") != before["library_dir"]):
            self._library.set_folder(self._library.effective_folder())
            self._refresh_processed_pickers()
        for panel in self._panels.values():
            panel._font_spin.setValue(int(self.config.get("prompt_font_size", 10) or 10))
            if self.config.get("loras_dir") != before["loras_dir"]:
                panel.reload_loras_from_folder()
            panel.refresh_rewriter_status()

    # ------------------------------------------------------------------ #
    # Running
    # ------------------------------------------------------------------ #

    def _start(self, req: RunRequest):
        if not self.config.server_url():
            QMessageBox.warning(self, "No server", "Set the ComfyUI URL for the selected mode in Settings first.")
            return
        if self._pod.over_limit():
            limit = float(self.config.get("runpod_spend_limit", 0) or 0)
            QMessageBox.warning(
                self, "Spend limit reached",
                f"This pod has hit the ${limit:.2f} session limit, so no new runs are "
                "being started. It will stop once the current run finishes.\n\n"
                "Raise the limit in Settings to keep going.")
            return
        if not (self.config.get("output_dir", "") or "").strip():
            QMessageBox.warning(self, "No output folder", "Set the Output folder in Settings first.")
            return
        self.config.save()
        if self.config.is_runpod() and model_sync.check_enabled(self.config.get_all()):
            # Hold the request until the workflow's model files are confirmed
            # on the pod (and copied there / back here if not). Requests that
            # arrive in the same event-loop turn — a multi-select queues one
            # per image — are checked together, in one pass.
            self._model_queue.append(req)
            if not self._model_check_scheduled:
                self._model_check_scheduled = True
                QTimer.singleShot(0, self._run_model_check)
            return
        self._start_checked(req)

    def _start_checked(self, req: RunRequest):
        """Queue or launch a request whose models are known to be in place."""
        if self._worker is not None and self._worker.isRunning():
            # ComfyUI only works one prompt at a time - hold this one and run
            # it automatically once whatever's running now finishes.
            self._queue.append(req)
            panel = self._panel_for(req)
            panel.append_log(f"Queued #{len(self._queue)} — {req.describe()}")
            self._update_queue_label()
            return
        self._launch(req)

    # ------------------------------------------------------------------ #
    # Model check & sync (RunPod)
    # ------------------------------------------------------------------ #

    def _sync_log(self, panel, msg: str):
        """Model check / sync lines go to the tab's log AND the run log file,
        so a transfer that misbehaves overnight leaves evidence."""
        panel.append_log(msg)
        try:
            path = Path(self.config.get("_base_dir", str(Path(__file__).resolve().parent.parent))) / "video_creator_run.log"
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} SYNC {msg}\n")
        except OSError:
            pass

    def _run_model_check(self):
        self._model_check_scheduled = False
        if self._model_check is not None or self._transfer is not None or not self._model_queue:
            return
        batch, self._model_queue = self._model_queue, []
        refs: dict[model_sync.ModelRef, None] = {}
        for req in batch:
            try:
                wf = load_workflow(req.workflow_path)
                if req.lora_edits:
                    apply_inputs(wf, req.lora_edits)
                if req.turbo_enabled is not None:
                    a = analyze(wf)
                    if a.turbo is not None:
                        apply_turbo_toggle(wf, a.turbo, req.turbo_enabled)
            except Exception as e:  # noqa: BLE001
                self._sync_log(self._panel_for(req), f"Model check: couldn't read {req.workflow_path.name} ({e}) — the run will report it")
                continue
            for r in model_sync.models_in_workflow(wf):
                refs.setdefault(r, None)
        if not refs:
            self._release_batch(batch)
            return
        self._model_batch = batch
        self._pod.cancel_idle_timer()
        panel = self._panel_for(batch[0])
        self._sync_log(panel, f"Model check: comparing {len(refs)} model file(s) between the local models folder and the pod volume…")
        self._model_check = model_sync.ModelCheckWorker(self.config.get_all(), list(refs))
        self._model_check.done.connect(self._on_model_plan)
        self._model_check.finished.connect(self._model_check_finished)
        self._model_check.start()

    def _model_check_finished(self):
        self._model_check = None
        # Anything that arrived while the check ran (and no transfer followed)
        if self._transfer is None and self._model_queue:
            QTimer.singleShot(0, self._run_model_check)

    def _release_batch(self, batch: list[RunRequest]):
        for req in batch:
            self._start_checked(req)

    def _drop_batch(self, batch: list[RunRequest], why: str):
        if batch:
            self._panel_for(batch[0]).append_log(
                f"{len(batch)} run{'s' if len(batch) != 1 else ''} not started — {why}")
        self._update_queue_label()

    def _on_model_plan(self, plan: model_sync.SyncPlan):
        batch, self._model_batch = self._model_batch, []
        panel = self._panel_for(batch[0]) if batch else self._image_panel
        if plan.error:
            ans = QMessageBox.question(
                self, "Couldn't check the pod's models",
                f"The pod volume could not be listed:\n\n{plan.error}\n\n"
                "Start the run anyway? A model the pod lacks will fail on the server.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            self._sync_log(panel, f"Model check failed: {plan.error}")
            if ans == QMessageBox.StandardButton.Yes:
                self._release_batch(batch)
            else:
                self._drop_batch(batch, "model check failed (see Settings > Models)")
            return
        for ref, actual in plan.case_mismatch.items():
            self._sync_log(panel, f"Model check: {ref.rel} is spelled {actual} on disk — the Linux pod is case-sensitive")
        for ref, (lsize, rsize) in plan.size_mismatch.items():
            self._sync_log(panel, f"Model check: {ref.rel} differs in size (local {model_sync.fmt_size(lsize)}, pod {model_sync.fmt_size(rsize)}) — not touched")

        # Models the pod has but this PC doesn't. The pod run is fine without
        # them, so say exactly that and offer the download for local use —
        # a 35 GB text encoder must never start pulling down unannounced.
        offered = [j for j in plan.optional_downloads if j.ref.rel not in self._pod_only_declined]
        if offered:
            total = sum(j.size for j in offered)
            names = "\n".join(f"    • {j.ref.kind}: {j.ref.rel}  ({model_sync.fmt_size(j.size)})" for j in offered)
            self._sync_log(panel, f"Model check: {len(offered)} model(s) are on the pod but not on this PC ({model_sync.fmt_size(total)})")
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Model missing locally")
            box.setText(f"{len(offered)} model file(s) exist on the pod but not on this PC "
                        f"({model_sync.fmt_size(total)}):")
            box.setInformativeText(
                names + "\n\n"
                "This run goes to the pod, which already has them, so it can start right away.\n"
                "You only need the download if you also want to run this workflow on local ComfyUI.\n\n"
                f"Download to {plan.local_root}? The download runs first, then the run starts.\n"
                "(Settings > Models can download these automatically without asking.)")
            dl = box.addButton("Download, then run", QMessageBox.ButtonRole.AcceptRole)
            pod = box.addButton("Run on the pod without downloading", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(pod)
            box.exec()
            if box.clickedButton() is dl:
                plan.downloads.extend(offered)
                self._sync_log(panel, f"Model check: downloading {len(offered)} pod-only model(s) to this PC first")
            elif box.clickedButton() is pod:
                for j in offered:
                    self._pod_only_declined.add(j.ref.rel)
                self._sync_log(panel, "Model check: running on the pod without the local copies (not asked again this session)")
            else:
                self._drop_batch(batch, "cancelled at the missing-locally prompt")
                return

        if plan.clean and not plan.downloads:
            self._sync_log(panel, "Model check: every model file the run needs is on the pod")
            self._release_batch(batch)
            return

        lines = []
        if plan.uploads:
            lines.append(f"Upload to the pod ({model_sync.fmt_size(sum(j.size for j in plan.uploads))}):")
            lines += [f"    ↑ {j.label}  ({model_sync.fmt_size(j.size)})" for j in plan.uploads]
        if plan.downloads:
            lines.append(f"Download to {plan.local_root} ({model_sync.fmt_size(sum(j.size for j in plan.downloads))}):")
            lines += [f"    ↓ {j.label}  ({model_sync.fmt_size(j.size)})" for j in plan.downloads]
        if plan.nowhere:
            lines.append("Not found on the pod OR locally — the run will fail on the server unless the pod has them outside the volume:")
            lines += [f"    ✗ {r.kind}: {r.rel}" for r in plan.nowhere]
        body = "\n".join(lines)
        for ln in lines:
            self._sync_log(panel, "Model check: " + ln.strip())

        if plan.jobs:
            if plan.uploads or plan.nowhere:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("Sync models with the pod?")
                box.setText(f"{len(plan.jobs)} model file(s) to copy "
                            f"({model_sync.fmt_size(plan.total_bytes)} to move).")
                box.setInformativeText(body + "\n\nCopy them now? The run starts automatically once every file is verified.")
                yes = box.addButton("Sync, then run", QMessageBox.ButtonRole.AcceptRole)
                anyway = box.addButton("Run without syncing", QMessageBox.ButtonRole.DestructiveRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.setDefaultButton(yes)
                box.exec()
                if box.clickedButton() is yes:
                    self._start_transfer(plan, batch)
                elif box.clickedButton() is anyway:
                    self._release_batch(batch)
                else:
                    self._drop_batch(batch, "model sync cancelled")
                return
            self._start_transfer(plan, batch)        # downloads the user just said yes to
            return

        ans = QMessageBox.question(
            self, "Models not found",
            body + "\n\nStart the run anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans == QMessageBox.StandardButton.Yes:
            self._release_batch(batch)
        else:
            self._drop_batch(batch, "model files missing on both sides")

    def _start_transfer(self, plan: model_sync.SyncPlan, batch: list[RunRequest]):
        self._model_batch = batch
        panel = self._panel_for(batch[0])
        ups, downs = len([j for j in plan.jobs if j.direction == "upload"]), len([j for j in plan.jobs if j.direction == "download"])
        size = model_sync.fmt_size(plan.total_bytes)
        title = (f"Downloading {downs} model file(s) to this PC — {size} total" if not ups else
                 f"Uploading {ups} model file(s) to the pod — {size} total" if not downs else
                 f"Syncing models — {ups} up, {downs} down — {size} total")
        self._xfer_mark = ("", time.time(), 0)
        self._transfer_dlg = QProgressDialog("Starting…", "Cancel", 0, 1000, self)
        self._transfer_dlg.setWindowTitle(title)
        self._transfer_dlg.setMinimumWidth(560)
        self._transfer_dlg.setMinimumDuration(0)
        self._transfer_dlg.setAutoClose(False)
        self._transfer_dlg.setAutoReset(False)
        self._transfer_dlg.canceled.connect(self._cancel_transfer)
        self._transfer = model_sync.TransferWorker(self.config.get_all(), plan.jobs)
        self._transfer.log.connect(lambda m, p=panel: self._sync_log(p, m))
        self._transfer.progress.connect(self._on_transfer_progress)
        self._transfer.finished_ok.connect(self._on_transfer_done)
        self._transfer.finished.connect(self._transfer_finished)
        self._transfer.start()

    def _cancel_transfer(self):
        if self._transfer is not None:
            self._transfer.cancel()
            if self._transfer_dlg is not None:
                self._transfer_dlg.setLabelText("Cancelling after the current file…")

    def _on_transfer_progress(self, done: int, total: int, label: str, files_done: int, files_total: int):
        if self._transfer_dlg is None:
            return
        now = time.time()
        mark_label, t0, b0 = self._xfer_mark
        if label != mark_label:                 # new file (or a retry): rate restarts
            self._xfer_mark = (label, now, done)
            t0, b0 = now, done
        elapsed = now - t0
        rate = (done - b0) / elapsed if elapsed > 0.5 else 0.0
        eta = model_sync.fmt_eta((total - done) / rate) if rate > 0 else "—"
        self._transfer_dlg.setValue(int(done * 1000 / total) if total else 0)
        self._transfer_dlg.setLabelText(
            f"{label}\n"
            f"{model_sync.fmt_size(done)} of {model_sync.fmt_size(total)}"
            + (f"   ·   {model_sync.fmt_rate(rate)}   ·   about {eta} left" if rate > 0 else "")
            + f"\nfile {min(files_done + 1, files_total)} of {files_total}   ·   Cancel stops the transfer now")

    def _on_transfer_done(self, errors: list):
        batch, self._model_batch = self._model_batch, []
        if self._transfer_dlg is not None:
            self._transfer_dlg.close()
            self._transfer_dlg = None
        panel = self._panel_for(batch[0]) if batch else self._image_panel
        if errors:
            text = "\n".join(f"• {name}: {err}" for name, err in errors[:12])
            QMessageBox.critical(self, "Model sync failed",
                                 f"{len(errors)} file(s) did not transfer:\n\n{text}\n\nThe run was not started.")
            self._drop_batch(batch, "model sync failed")
            return
        self._sync_log(panel, "Model sync: every file verified — starting the run")
        # A downloaded LoRA should show up in the dropdowns straight away.
        self._image_panel.reload_loras_from_folder(quiet=True)
        self._release_batch(batch)

    def _transfer_finished(self):
        self._transfer = None
        if self._model_queue:
            QTimer.singleShot(0, self._run_model_check)

    def _launch(self, req: RunRequest):
        panel = self._panel_for(req)
        self._active_panel = panel
        self._active_req = req
        panel.set_running(True, active=True)
        self._pod.cancel_idle_timer()
        self._batch_runs += 1

        cfg = self.config.get_all()
        self._worker = RunWorker(cfg, req)
        self._worker.log.connect(panel.append_log)
        self._worker.plan.connect(panel.on_plan)
        self._worker.step.connect(panel.on_step)
        self._worker.phase.connect(panel.on_phase)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()
        self._update_queue_label()

    def _update_queue_label(self):
        n = len(self._queue)
        tooltip = "\n".join(f"{i + 1}. {r.describe()}" for i, r in enumerate(self._queue))
        next_up = f"{self._queue[0].source_name} ({self._queue[0].workflow_label})" if self._queue else ""
        for p in self._panels.values():
            p.set_queue_status(n, tooltip, next_up)
        if self._queue_dlg is not None:
            self._queue_dlg.set_items(self._active_req, list(self._queue))

    def _panel_for(self, req: RunRequest) -> RunPanel:
        return self._panels.get(req.source_kind, self._image_panel)

    def _show_queue(self):
        """Opens (or raises) the queue view — what's running plus everything
        waiting, with enough detail to spot a run that's already lined up."""
        if self._queue_dlg is None:
            dlg = QueueDialog(self)
            dlg.remove_requested.connect(self._remove_queued)
            dlg.move_requested.connect(self._move_queued)
            dlg.next_requested.connect(self._move_queued_to_next)
            dlg.clear_requested.connect(self._clear_queue)
            self._queue_dlg = dlg
        self._queue_dlg.set_items(self._active_req, list(self._queue))
        self._queue_dlg.show()
        self._queue_dlg.raise_()
        self._queue_dlg.activateWindow()

    def _queued_duplicate(self, req: RunRequest) -> str:
        """Called by a run panel before it queues anything: names the run
        already running or waiting that this one repeats, or "" if it's new."""
        fp = req.fingerprint()
        if self._active_req is not None and self._active_req.fingerprint() == fp:
            return "the run going on right now"
        for i, queued in enumerate(self._queue):
            if queued.fingerprint() == fp:
                return f"queue position {i + 1}"
        return ""

    def _remove_queued(self, index: int):
        if not 0 <= index < len(self._queue):
            return
        req = self._queue.pop(index)
        self._panel_for(req).append_log(f"Removed from queue: {req.describe()}")
        self._update_queue_label()

    def _move_queued(self, index: int, delta: int):
        target = index + delta
        if not (0 <= index < len(self._queue) and 0 <= target < len(self._queue)):
            return
        self._queue[index], self._queue[target] = self._queue[target], self._queue[index]
        self._update_queue_label()
        if self._queue_dlg is not None:
            self._queue_dlg.select_position(target)

    def _move_queued_to_next(self, index: int):
        if not 0 < index < len(self._queue):
            return
        self._queue.insert(0, self._queue.pop(index))
        self._update_queue_label()
        if self._queue_dlg is not None:
            self._queue_dlg.select_position(0)

    def _clear_queue(self):
        for req in self._queue:
            self._panel_for(req).append_log(f"Removed from queue: {req.describe()}")
        self._queue.clear()
        self._update_queue_label()

    def _cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            if self._active_panel is not None:
                self._active_panel.append_log("Cancelling — interrupting the server…")

    def _on_done(self, paths: list, timing: dict | None = None):
        if self._active_panel is not None:
            self._active_panel.on_done(list(paths), self._active_req, timing)
        self._library.refresh()
        req = self._active_req
        if req is not None and req.source_kind == "video" and req.source_path is not None:
            self._marks.add([req.source_path])      # extended: out of the Extend list until Show all
        # The source of what just finished now has a video, so it drops out of the pickers
        self._image_browser.refresh_processed()
        self._video_browser.refresh_processed()
        # New files may have landed in the folder the Video tab is showing
        out_dir = Path((self.config.get("output_dir", "") or "").strip() or ".")
        vid_dir = Path(self._video_browser.folder) if self._video_browser.folder else None
        if vid_dir is not None and vid_dir.exists() and out_dir.exists() and vid_dir.resolve() == out_dir.resolve():
            self._video_browser.refresh()

    def _on_failed(self, message: str):
        if self._active_panel is not None:
            self._active_panel.on_failed(message)
        if message != "Cancelled":
            QMessageBox.critical(self, "Generation failed", message)

    def _on_worker_finished(self):
        if self._active_panel is not None:
            self._active_panel.set_running(False)
        self._worker = None
        self._active_panel = None
        self._active_req = None
        if self._queue and not self._pod.over_limit():
            self._launch(self._queue.pop(0))
        self._update_queue_label()
        # A deferred "stop when the spend limit is hit" lands here, once the
        # run it was waiting for has actually finished.
        self._pod.run_finished()
        if self._worker is None:        # nothing launched after it: the queue is done
            if self._batch_runs >= 2 and self.config.get("alert_sound_enabled", True):
                # Same sound as "a pod is available" — worth walking back to the desk for.
                if alerts.play(self.config.get("alert_sound_path", "")):
                    self._log_everywhere(f"Queue finished ({self._batch_runs} runs) — alert sound played")
            self._batch_runs = 0
            self._pod.start_idle_timer()

    # ------------------------------------------------------------------ #
    # Player
    # ------------------------------------------------------------------ #

    def _play(self, path: str):
        if not path or not Path(path).exists():
            return
        self._open_player(path, None)

    def _open_player(self, path: str, playlist):
        self._close_player()
        # Every player in this app closes itself once the video ends, and
        # closing destroys it, so the file it played is free again.
        dlg = VideoPlayerDialog(path, self, playlist=playlist, auto_close=True)
        dlg.closed.connect(lambda d=dlg: self._forget_player(d))
        self._player = dlg
        dlg.show()

    def _close_player(self):
        dlg, self._player = self._player, None
        if dlg is None:
            return
        try:
            dlg.close()          # runs release() via closeEvent
        except RuntimeError:     # already destroyed by WA_DeleteOnClose
            pass

    def _forget_player(self, dlg):
        if self._player is dlg:
            self._player = None

    def _on_files_deleting(self, paths: list):
        """The player holds its file open; close it before the delete runs."""
        dlg = self._player
        if dlg is None:
            return
        try:
            if dlg.holds(paths):
                self._close_player()
        except RuntimeError:
            self._player = None

    def _play_list(self, paths: list):
        """Library playback: plays the selection back-to-back and closes
        itself when the last one ends."""
        paths = [p for p in paths if p and Path(p).exists()]
        if not paths:
            return
        self._open_player(paths[0], paths)

    def _on_files_deleted(self, paths: list):
        """A file deleted in one tab is gone for the others too — the Library
        and the Extend tab often point at the same folder, and a tile for a
        file that no longer exists is worse than a slightly stale count."""
        sender = self.sender()
        for browser in (self._image_browser, self._video_browser, self._library.browser):
            if browser is not sender:
                browser.remove_paths(paths)

    def _send_to_extend(self, path: Path):
        """Library → Extend: select the video in the Extend tab (switching the
        Extend folder to the library folder if it lives elsewhere)."""
        path = Path(path)
        self._tabs.setCurrentIndex(TAB_INDEX["video"])
        folder = str(path.parent)
        if self._video_browser.folder and Path(self._video_browser.folder).resolve() == path.parent.resolve():
            if not self._video_browser.grid.select_key(str(path)):
                self._video_panel.set_source(path)
        else:
            self.config.set("video_dir", folder)
            self.config.save()
            self._video_browser.set_folder(folder)
            self._video_panel.set_source(path)
            self._pending_select = str(path)
            self._video_browser.grid.model().rowsInserted.connect(self._try_pending_select)
        self._video_panel.append_log(f"Source from Library: {path.name}")

    def _reuse_settings(self, video_path: Path, wf_path: Path, entry: dict):
        """Library → Reuse Settings: switch to the tab this run was made on,
        reload its prompt/LoRAs/seed/steps/source, and let the user tweak
        before pressing Create/Extend themselves — nothing is queued here."""
        settings = entry.get("settings") or {}
        # Only the video (Extend) panel ever writes a video_input_mode, and
        # only the Text → Video panel (or the embedded-metadata fallback, for
        # a graph with no loader node) sets text_to_video.
        if settings.get("video_input_mode"):
            kind = "video"
        elif settings.get("text_to_video"):
            kind = "text"
        else:
            kind = "image"
        panel = self._panels[kind]
        browser = self._video_browser if kind == "video" else self._image_browser
        self._tabs.setCurrentIndex(TAB_INDEX[kind])

        wf_dir = Path((self.config.get("workflow_dir", "") or "").strip())
        rel = settings.get("workflow")
        if not rel:
            try:
                rel = wf_path.relative_to(wf_dir).as_posix() if str(wf_dir) else wf_path.name
            except ValueError:
                rel = wf_path.name
        if not panel.load_reused_entry(rel, entry, output_dir=video_path.parent):
            panel.append_log(f"⚠ Workflow '{rel}' is no longer on disk — pick one manually; "
                              "the prompt/settings were applied wherever they still matched.")
        panel.append_log(f"This run will save back to {video_path.parent}")

        if kind == "image":
            self._reuse_image_source(panel, video_path)
        elif kind == "video":
            self._reuse_video_source(browser, panel, source_for_result(entry, video_path.name))
        else:
            panel.append_log("Reused settings from Library — text to video needs no source; "
                             "tweak the prompt, then Create.")

    def _reuse_image_source(self, panel: RunPanel, video_path: Path):
        """The image an I2V run started from is often a temp/staged upload
        that's long gone by the time someone reviews the result — the
        finished video is always right there, so its first frame is pulled
        as a stand-in starting image instead of hunting for the original."""
        try:
            cache_dir = Path(tempfile.gettempdir()) / "ComfyUI_Video_Creator_reuse"
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Strip whatever the run that made this video appended (its own
            # workflow label + timestamp) so the new run's own label+stamp
            # doesn't get bolted on top of a copy that's already there.
            labels = _workflow_labels(self.config.get("workflow_dir", ""))
            base = _base_stem(video_path.stem, labels)
            frame_path = cache_dir / f"{base}.png"
            ok = extract_thumbnail(self._ffmpeg(), video_path, frame_path)
        except OSError as e:
            ok = False
            panel.append_log(f"⚠ Could not extract a starting frame from {video_path.name}: {e}")
        if ok:
            panel.set_source(frame_path)
            panel.append_log(f"Reused settings — starting image is {video_path.name}'s first frame")
        else:
            panel.append_log(
                f"⚠ Couldn't extract a starting frame from {video_path.name} — pick a source image, then Create.")

    def _reuse_video_source(self, browser: MediaBrowser, panel: RunPanel, source_name: str):
        candidate = Path(browser.folder) / source_name if (browser.folder and source_name) else None
        if candidate is not None and candidate.exists():
            if not browser.grid.select_key(str(candidate)):
                panel.set_source(candidate)
            panel.append_log(f"Reused settings from Library — source: {source_name}")
        elif source_name:
            # Moved or deleted outside the app — rescan so the grid matches
            # what's actually on disk instead of leaving a stale/missing pick.
            browser.refresh()
            panel.append_log(f"⚠ Source '{source_name}' wasn't found in {browser.folder or '(no folder set)'} "
                              "— rescanned that folder. Pick a replacement video, then Extend.")
        else:
            panel.append_log("Reused settings from Library (no source recorded for this run — pick one, then Extend).")

    def _try_pending_select(self, *_):
        key = getattr(self, "_pending_select", None)
        if key and self._video_browser.grid.select_key(key):
            self._pending_select = None
            try:
                self._video_browser.grid.model().rowsInserted.disconnect(self._try_pending_select)
            except TypeError:
                pass

    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            ans = QMessageBox.question(
                self, "Generation running",
                "A generation is still running. Cancel it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(5000)
        if self._transfer is not None:
            self._transfer.cancel()
            self._transfer.wait(3000)
        # Ask about any pod this session is connected to — one adopted from the
        # launch chooser too, not only one this app started.
        if self._pod.pod_id and self.config.get("runpod_auto_stop_on_exit", True):
            ans = QMessageBox.question(
                self, "Stop the pod?",
                f"RunPod pod {self._pod.pod_id} is still running.\n\n"
                "Yes — stop the pod, then quit. GPU billing ends.\n"
                "No — quit and leave the pod running. It keeps billing until you "
                "stop it in the RunPod console. Can reconnect if still running on "
                "next app launch.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if ans == QMessageBox.StandardButton.Yes:
                self._pod.shutdown()
            else:
                self._pod.leave_running()
        self._close_player()
        if self._queue_dlg is not None:
            self._queue_dlg.close()
        self._image_browser.shutdown()
        self._video_browser.shutdown()
        self._library.shutdown()
        self.config.save()
        event.accept()
