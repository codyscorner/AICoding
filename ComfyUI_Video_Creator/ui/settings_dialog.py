from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from config import ConfigManager
from ui.styles import COLORS
from ui.widgets import NoScrollComboBox
from workflow_tools import list_workflows


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(1120)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(parent.styleSheet() if parent else "")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Tabs rather than columns: the dialog is only ever as tall as its
        # tallest page, so a group can grow (the pod lists did) without
        # pushing the whole thing off a 1080p screen, and each page gets the
        # full width instead of half of it.
        tabs = QTabWidget()
        layout.addWidget(tabs)

        def page(title: str) -> QVBoxLayout:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setSpacing(12)
            lay.setContentsMargins(16, 16, 16, 16)
            tabs.addTab(w, title)
            return lay

        server_tab = page("Server")
        folders_tab = page("Folders")
        runpod_tab = page("RunPod")
        prompt_tab = page("Prompts")
        models_tab = page("Models")

        # ── ComfyUI Server ───────────────────────────────────────────────
        server_group = QGroupBox("ComfyUI Server")
        sl = QVBoxLayout(server_group)
        sl.setSpacing(10)
        mode_row = QHBoxLayout()
        self._local_radio = QRadioButton("Local")
        self._runpod_radio = QRadioButton("RunPod")
        grp = QButtonGroup(self)
        grp.addButton(self._local_radio)
        grp.addButton(self._runpod_radio)
        (self._runpod_radio if config.get("mode", "local") == "runpod" else self._local_radio).setChecked(True)
        mode_row.addWidget(self._local_radio)
        mode_row.addWidget(self._runpod_radio)
        mode_row.addStretch()
        sl.addLayout(mode_row)
        self._local_url = self._text_row(sl, "Local URL:", config.get("comfyui_url", ""), "http://127.0.0.1:8000")
        self._runpod_url = self._text_row(sl, "RunPod URL:", config.get("runpod_url", ""),
                                          "https://xxxxxx-8188.proxy.runpod.net")
        test_row = QHBoxLayout()
        test_row.addStretch()
        test_btn = QPushButton("Test connection")
        test_btn.setObjectName("secondary_btn")
        test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(test_btn)
        sl.addLayout(test_row)
        self._test_status = QLabel("")
        self._test_status.setWordWrap(True)
        self._test_status.setObjectName("status_dim")
        sl.addWidget(self._test_status)
        server_tab.addWidget(server_group)

        # ── Folders ──────────────────────────────────────────────────────
        folders_group = QGroupBox("Folders")
        fl = QVBoxLayout(folders_group)
        fl.setSpacing(10)
        self._image_dir = self._folder_row(fl, "Images:", config.get("image_dir", ""),
                                           "Folder of starting images (Image → Video tab)…")
        self._video_dir = self._folder_row(fl, "Videos:", config.get("video_dir", ""),
                                           "Folder of videos to extend (Video → Extend tab)…")
        self._workflow_dir = self._folder_row(fl, "Workflows:", config.get("workflow_dir", ""),
                                              "Folder of API-format workflow .json files (subfolders included)…")
        self._output_dir = self._folder_row(fl, "Output:", config.get("output_dir", ""),
                                            "Where finished videos are downloaded to…")
        self._loras_dir = self._folder_row(fl, "LoRAs:", config.get("loras_dir", ""),
                                           "ComfyUI models/loras folder — fills the LoRA dropdowns…")
        self._library_dir = self._folder_row(fl, "Library:", config.get("library_dir", ""),
                                             "Folder shown on the Library tab (blank = the Output folder)…")
        self._archive_dir = self._folder_row(fl, "Archive:", config.get("archive_dir", ""),
                                             "Where archived videos are moved to (watch later in Desktop Video Browser)…")
        self._per_workflow = QCheckBox("Save each workflow's videos in its own folder inside Output")
        self._per_workflow.setToolTip(
            "On: a run of Series 1/MiniMax_Foo.json saves to <Output>/Series 1/MiniMax_Foo/.\n"
            "An image then only counts as done for the workflow that made its video, so the same "
            "image stays available for other workflows.\nOff: every video goes straight into Output.")
        self._per_workflow.setChecked(bool(config.get("output_per_workflow", True)))
        fl.addWidget(self._per_workflow)
        folders_tab.addWidget(folders_group)

        # ── Staging ──────────────────────────────────────────────────────
        stage_group = QGroupBox("Folder-loader workflows (Load Image List From Dir)")
        stl = QVBoxLayout(stage_group)
        stl.setSpacing(10)
        note = QLabel("Batch-style workflows read a whole folder instead of one LoadImage node. "
                      "The selected image is staged alone into a run folder here and the loader is pointed at it.")
        note.setWordWrap(True)
        note.setObjectName("status_dim")
        stl.addWidget(note)
        self._staging_dir = self._folder_row(stl, "Local staging:", config.get("staging_dir_local", ""),
                                             "Local folder for staged images (blank = app's temp folder)…")
        self._runpod_input = self._text_row(stl, "RunPod input:", config.get("runpod_input_dir", ""),
                                            "Absolute path of ComfyUI's input folder on the pod…")
        server_tab.addWidget(stage_group)

        # ── FFmpeg ───────────────────────────────────────────────────────
        ff_group = QGroupBox("FFmpeg")
        ffl = QVBoxLayout(ff_group)
        ffl.setSpacing(10)
        self._ffmpeg = self._file_row(ffl, "FFmpeg path:", config.get("ffmpeg_path", ""),
                                      "Blank = ffmpeg.exe next to the app, then PATH…")
        ff_note = QLabel("Used for video thumbnails, last-frame extraction and appending the new clip to the source video.")
        ff_note.setWordWrap(True)
        ff_note.setObjectName("status_dim")
        ffl.addWidget(ff_note)
        folders_tab.addWidget(ff_group)

        # ── Editor ───────────────────────────────────────────────────────
        ed_group = QGroupBox("Prompt editor")
        edl = QHBoxLayout(ed_group)
        edl.addWidget(QLabel("Text size:"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(7, 20)
        self._font_spin.setValue(int(config.get("prompt_font_size", 10) or 10))
        edl.addWidget(self._font_spin)
        edl.addStretch()
        prompt_tab.addWidget(ed_group)

        # ── Blank workflow templates ─────────────────────────────────────
        blank_group = QGroupBox("New blank workflow")
        bl = QVBoxLayout(blank_group)
        bl.setSpacing(10)
        blank_note = QLabel("The ✚ New button on the Image → Video and Text → Video tabs copies the "
                            "workflow picked here under a new name, with every prompt emptied and every "
                            "LoRA switched off. The template itself is never changed.")
        blank_note.setWordWrap(True)
        blank_note.setObjectName("status_dim")
        bl.addWidget(blank_note)
        wf_rels = list_workflows(Path(config.get("workflow_dir", "") or "")) \
            if (config.get("workflow_dir", "") or "").strip() else []
        self._blank_image = self._template_row(bl, "Image → Video:", wf_rels,
                                               config.get("image_blank_template", ""))
        self._blank_text = self._template_row(bl, "Text → Video:", wf_rels,
                                              config.get("text_blank_template", ""))
        prompt_tab.addWidget(blank_group)

        # ── AI Prompt Rewriter ──────────────────────────────────────────
        rw_group = QGroupBox("AI Prompt Rewriter (local LM Studio)")
        rwl = QVBoxLayout(rw_group)
        rwl.setSpacing(10)
        rw_note = QLabel("Turns a rough scene idea into a correctly-formatted MiniMax H3 prompt "
                          "using any model already loaded in LM Studio - nothing is uploaded anywhere.")
        rw_note.setWordWrap(True)
        rw_note.setObjectName("status_dim")
        rwl.addWidget(rw_note)
        self._rewriter_url = self._text_row(rwl, "LM Studio URL:", config.get("rewriter_base_url", ""),
                                            "http://127.0.0.1:1234/v1")
        model_row = QHBoxLayout()
        model_row.addWidget(self._label("Model:"))
        self._rewriter_model = NoScrollComboBox()
        self._rewriter_model.setEditable(True)
        saved_model = config.get("rewriter_model", "")
        if saved_model:
            self._rewriter_model.addItem(saved_model)
        model_row.addWidget(self._rewriter_model, stretch=1)
        fetch_btn = QPushButton("Fetch models")
        fetch_btn.setObjectName("secondary_btn")
        fetch_btn.clicked.connect(self._fetch_rewriter_models)
        model_row.addWidget(fetch_btn)
        rwl.addLayout(model_row)
        self._rewriter_status = QLabel("")
        self._rewriter_status.setWordWrap(True)
        self._rewriter_status.setObjectName("status_dim")
        rwl.addWidget(self._rewriter_status)
        prompt_tab.addWidget(rw_group)

        # ── RunPod pod control ───────────────────────────────────────────
        pod_group = QGroupBox("RunPod pod control")
        pl = QVBoxLayout(pod_group)
        pl.setSpacing(10)

        # Account balance, fetched with the pod list. Account-wide: the
        # rate is every pod and volume on the account, not just ours.
        self._balance_lbl = QLabel("")
        self._balance_lbl.setObjectName("subtitle")
        self._balance_lbl.setToolTip(
            "Your RunPod account balance and what the whole account is spending right now\n"
            "(every running pod plus storage). Hours left = balance / that rate.\n"
            "Refreshes with the pod list.")
        pl.addWidget(self._balance_lbl)

        # GPU model outranks the per-pod order, so "all the RTX 6000s, then
        # the A100s" keeps holding when a pod is rebuilt and its id changes.
        pl.addWidget(self._caption("GPU priority — every pod on the first card is tried "
                                   "before any pod on the second:"))
        gpu_row = QHBoxLayout()
        self._gpu_list = QListWidget()
        self._gpu_list.setFixedHeight(72)
        self._gpu_list.setToolTip("Card models on your account, best first.\n"
                                  "A model that is not listed sorts last — a preference "
                                  "never excludes hardware.")
        self._gpu_list.model().rowsMoved.connect(lambda *_: self._rebuild_pod_list())
        gpu_row.addWidget(self._gpu_list, stretch=1)
        gpu_btns = QVBoxLayout()
        gpu_btns.setSpacing(2)
        for text, slot in (("▲", lambda: self._move_gpu(-1)), ("▼", lambda: self._move_gpu(1))):
            b = QPushButton(text)
            b.setObjectName("small_btn")
            b.setFixedWidth(40)
            b.clicked.connect(slot)
            gpu_btns.addWidget(b)
        gpu_btns.addStretch()
        gpu_row.addLayout(gpu_btns)
        pl.addLayout(gpu_row)

        pl.addWidget(self._caption("Pod order — the chain works down this list:"))
        list_row = QHBoxLayout()
        self._pod_list = QListWidget()
        # Fixed, not minimum: QListWidget asks for 256px by default, which
        # over-commits the column and makes Qt overlap the rows below it.
        self._pod_list.setFixedHeight(196)
        self._pod_list.setToolTip("The real chain order, GPU priority already applied.\n"
                                  "▲▼ moves a pod within its own card group.\n"
                                  "A running pod is used first — nothing to start or wait for.\n"
                                  "Existing pods only — never created or terminated.\n"
                                  "Double-click a pod to point the RunPod URL at it.")
        self._pod_list.itemDoubleClicked.connect(self._use_pod)
        list_row.addWidget(self._pod_list, stretch=1)
        btn_col = QVBoxLayout()
        btn_col.setSpacing(2)
        for text, slot in (("▲", lambda: self._move_pod(-1)), ("▼", lambda: self._move_pod(1))):
            b = QPushButton(text)
            b.setObjectName("small_btn")
            b.setFixedWidth(40)
            b.clicked.connect(slot)
            btn_col.addWidget(b)
        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("small_btn")
        refresh_btn.setFixedWidth(40)
        refresh_btn.setToolTip("Fetch the pod list from RunPod")
        refresh_btn.clicked.connect(self._refresh_pods)
        btn_col.addWidget(refresh_btn)
        btn_col.addStretch()
        list_row.addLayout(btn_col)
        pl.addLayout(list_row)

        limit_row = QHBoxLayout()
        limit_row.addWidget(self._label("Spend limit:"))
        self._spend_limit = QDoubleSpinBox()
        self._spend_limit.setRange(0.0, 10000.0)
        self._spend_limit.setDecimals(2)
        self._spend_limit.setPrefix("$ ")
        self._spend_limit.setSpecialValueText("off")
        self._spend_limit.setValue(float(config.get("runpod_spend_limit", 0) or 0))
        limit_row.addWidget(self._spend_limit)
        limit_row.addWidget(QLabel("per pod run — 0 = off"))
        limit_row.addStretch()
        pl.addLayout(limit_row)

        idle_row = QHBoxLayout()
        idle_row.addWidget(self._label("Idle stop:"))
        self._idle_stop = QSpinBox()
        self._idle_stop.setRange(0, 600)
        self._idle_stop.setSingleStep(10)
        self._idle_stop.setSuffix(" min")
        self._idle_stop.setSpecialValueText("off")
        self._idle_stop.setValue(int(config.get("runpod_idle_stop_min", 0) or 0))
        self._idle_stop.setToolTip(
            "When the last run finishes (DONE) and nothing is queued, stop the connected pod "
            "after this long.\n"
            "A new run cancels the countdown. Only works while the app is running.")
        idle_row.addWidget(self._idle_stop)
        idle_row.addWidget(QLabel("after the queue finishes — 0 = off"))
        idle_row.addStretch()
        pl.addLayout(idle_row)

        # As a tooltip rather than a label: the right column is full at 1080p,
        # and a wrapped note here pushes the group past its allocation.
        self._spend_limit.setToolTip(
            "Compute only — storage bills separately.\n"
            "A safety net, not a hard cap: it can only act while the app is running, "
            "so a crash or reboot leaves the pod up.")

        retry_row = QHBoxLayout()
        retry_row.addWidget(self._label("Keep trying:"))
        self._retry_interval = QSpinBox()
        self._retry_interval.setRange(1, 120)
        self._retry_interval.setSuffix(" min")
        self._retry_interval.setValue(int(config.get("runpod_retry_interval_min", 10) or 10))
        self._retry_interval.setToolTip("How often to sweep the pod list when every pod is busy")
        retry_row.addWidget(self._retry_interval)
        retry_row.addWidget(QLabel("for"))
        self._retry_window = QSpinBox()
        self._retry_window.setRange(5, 1440)
        self._retry_window.setSuffix(" min")
        self._retry_window.setSingleStep(15)
        self._retry_window.setValue(int(config.get("runpod_retry_window_min", 120) or 120))
        self._retry_window.setToolTip("Give up after this long and stop looking")
        retry_row.addWidget(self._retry_window)
        retry_row.addStretch()
        pl.addLayout(retry_row)

        import alerts
        self._alert_sound = self._file_row(
            pl, "Alert sound:", config.get("alert_sound_path", ""),
            "Played when a pod is found, when giving up, and when a queue of 2+ runs finishes (.wav plays inline)…",
            caption="Select an alert sound", filt=alerts.WAV_FILTER)
        sound_row = QHBoxLayout()
        self._alert_enabled = QCheckBox("Play alert sound")
        self._alert_enabled.setChecked(bool(config.get("alert_sound_enabled", True)))
        sound_row.addWidget(self._alert_enabled)
        test_sound = QPushButton("Test")
        test_sound.setObjectName("small_btn")
        test_sound.setFixedWidth(60)
        test_sound.clicked.connect(self._test_sound)
        sound_row.addWidget(test_sound)
        sound_row.addStretch()
        pl.addLayout(sound_row)

        self._pod_prompt = QCheckBox("Ask on launch")
        self._pod_prompt.setToolTip("Offer to start a pod each time the app opens")
        self._pod_prompt.setChecked(bool(config.get("runpod_auto_prompt", True)))
        self._pod_autostop = QCheckBox("Stop pod on exit")
        self._pod_autostop.setToolTip("When quitting with a pod connected, ask whether to stop it or leave it running")
        self._pod_autostop.setChecked(bool(config.get("runpod_auto_stop_on_exit", True)))
        checks = QHBoxLayout()
        checks.addWidget(self._pod_prompt)
        checks.addWidget(self._pod_autostop)
        checks.addStretch()
        pl.addLayout(checks)

        pod_test_row = QHBoxLayout()
        pod_test_row.addStretch()
        pod_test_btn = QPushButton("Test API key")
        pod_test_btn.setObjectName("secondary_btn")
        pod_test_btn.clicked.connect(self._test_runpod_api)
        pod_test_row.addWidget(pod_test_btn)
        pl.addLayout(pod_test_row)
        self._pod_status = QLabel("")
        self._pod_status.setWordWrap(True)
        self._pod_status.setObjectName("status_dim")
        pl.addWidget(self._pod_status)
        runpod_tab.addWidget(pod_group)
        self._load_pod_order()

        # ── Model check & sync (RunPod volume via S3) ─────────────────────
        import model_sync as ms
        sync_group = QGroupBox("Model check && sync — RunPod volume via S3")
        syl = QVBoxLayout(sync_group)
        syl.setSpacing(10)
        syl.addWidget(self._caption(
            "Before a RunPod run, every model file the workflow names (checkpoints, diffusion models, "
            "VAEs, text encoders, CLIP vision, upscalers, LoRAs) is looked for in the local models folder "
            "and on the pod's volume. Files the pod lacks are uploaded from here before the run starts "
            "(and, if the box below is ticked, files only on the pod are downloaded to this PC). "
            "Same S3 access as the S3 Browser app and the Chain Automator."))
        self._sync_enabled = QCheckBox("Check and sync models before each RunPod run")
        self._sync_enabled.setChecked(bool(config.get(ms.CFG_MODEL_CHECK, True)))
        syl.addWidget(self._sync_enabled)
        self._sync_download = QCheckBox("Always download pod-only models to this PC without asking "
                                        "(off: you are asked each time — the pod run works either way)")
        self._sync_download.setChecked(bool(config.get(ms.CFG_DOWNLOAD, False)))
        syl.addWidget(self._sync_download)
        self._models_dir = self._folder_row(syl, "Models folder:", config.get(ms.CFG_MODELS_DIR, ""),
                                            "ComfyUI/models root — blank = the parent of the LoRAs folder…")
        self._s3_profile = self._text_row(syl, "AWS profile:", config.get(ms.CFG_S3_PROFILE, "runpod-s3"),
                                          "Profile in %USERPROFILE%\\.aws\\credentials holding the RunPod S3 keys (e.g. runpod-s3)…")
        self._s3_endpoint = self._text_row(syl, "Endpoint URL:", config.get(ms.CFG_S3_ENDPOINT, ""),
                                           "https://s3api-<datacenter>.runpod.io")
        self._s3_region = self._text_row(syl, "Region:", config.get(ms.CFG_S3_REGION, ""),
                                         "RunPod datacenter id (e.g. us-ks-2)")
        self._s3_bucket = self._text_row(syl, "Bucket:", config.get(ms.CFG_S3_BUCKET, ""),
                                         "Network volume id (e.g. pjez3nxwp9)")
        self._s3_prefix = self._text_row(syl, "Models prefix:", config.get(ms.CFG_S3_MODELS_PREFIX, ""),
                                         "Path of ComfyUI's models folder inside the bucket (e.g. runpod-slim/ComfyUI/models/)")
        s3_btn_row = QHBoxLayout()
        s3_btn_row.addStretch()
        s3_import = QPushButton("Import from S3 Browser config…")
        s3_import.setObjectName("secondary_btn")
        s3_import.setToolTip("Copy profile / endpoint / region / bucket from the S3 Browser app's config.json")
        s3_import.clicked.connect(self._import_s3_browser)
        s3_btn_row.addWidget(s3_import)
        s3_test = QPushButton("Test connection")
        s3_test.setObjectName("secondary_btn")
        s3_test.clicked.connect(self._test_s3)
        s3_btn_row.addWidget(s3_test)
        syl.addLayout(s3_btn_row)
        self._s3_status = QLabel("")
        self._s3_status.setWordWrap(True)
        self._s3_status.setObjectName("status_dim")
        syl.addWidget(self._s3_status)
        models_tab.addWidget(sync_group)

        # ── Pod volume cleanup (delete results after download) ────────────
        import remote_cleanup as rc
        clean_group = QGroupBox("Pod volume cleanup — results")
        cll = QVBoxLayout(clean_group)
        cll.setSpacing(10)
        cll.addWidget(self._caption(
            "ComfyUI keeps every finished video in its output folder on the pod's volume, which is billed "
            "per GB. With this ticked, each RunPod result is deleted from the volume (through the S3 "
            "connection above) right after it has been downloaded — and only if the downloaded file's "
            "size matches the one on the volume. A failed cleanup never fails the run."))
        self._delete_after = QCheckBox("Delete results from the pod volume after they are downloaded")
        self._delete_after.setChecked(bool(config.get(rc.CFG_DELETE_AFTER, False)))
        cll.addWidget(self._delete_after)
        self._output_prefix = self._text_row(
            cll, "Output prefix:", config.get(rc.CFG_OUTPUT_PREFIX, rc.DEFAULT_OUTPUT_PREFIX),
            "Path of ComfyUI's output folder inside the bucket (e.g. runpod-slim/ComfyUI/output/)")
        models_tab.addWidget(clean_group)

        for lay in (server_tab, folders_tab, runpod_tab, prompt_tab, models_tab):
            lay.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFixedWidth(110)
        return lbl

    def _caption(self, text: str) -> QLabel:
        """Full-width heading above a list — unlike _label, which pins itself
        to 110px to keep the form's label column aligned."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("status_dim")
        return lbl

    def _text_row(self, parent, label, value, placeholder) -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(self._label(label))
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        row.addWidget(edit, stretch=1)
        parent.addLayout(row)
        return edit

    def _template_row(self, parent, label, rels: list[str], current: str) -> NoScrollComboBox:
        row = QHBoxLayout()
        row.addWidget(self._label(label))
        combo = NoScrollComboBox()
        combo.addItem("No template selected — please select a workflow (JSON) file for ✚ New", "")
        for rel in rels:
            combo.addItem(rel, rel)
        if current and combo.findData(current) < 0:
            combo.addItem(f"{current}  (missing)", current)
        combo.setCurrentIndex(max(combo.findData(current or ""), 0))
        row.addWidget(combo, stretch=1)
        parent.addLayout(row)
        return combo

    def _folder_row(self, parent, label, value, placeholder) -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(self._label(label))
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("…")
        btn.setObjectName("small_btn")
        btn.setFixedWidth(40)
        btn.clicked.connect(lambda: self._browse_folder(edit))
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent.addLayout(row)
        return edit

    def _file_row(self, parent, label, value, placeholder,
                  caption: str = "Select ffmpeg.exe",
                  filt: str = "Executables (*.exe);;All Files (*)") -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(self._label(label))
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("…")
        btn.setObjectName("small_btn")
        btn.setFixedWidth(40)
        btn.clicked.connect(lambda: self._browse_file(edit, caption, filt))
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent.addLayout(row)
        return edit

    def _browse_folder(self, edit: QLineEdit):
        current = edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", current or str(Path.home()))
        if folder:
            edit.setText(folder)

    def _browse_file(self, edit: QLineEdit, caption: str = "Select ffmpeg.exe",
                     filt: str = "Executables (*.exe);;All Files (*)"):
        current = edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(self, caption, current or str(Path.home()), filt)
        if path:
            edit.setText(path)

    def _fetch_rewriter_models(self):
        import prompt_rewriter as pr
        url = self._rewriter_url.text().strip()
        if not url:
            self._rewriter_status.setText("Enter the LM Studio URL first.")
            return
        self._rewriter_status.setText(f"Fetching models from {url} …")
        self._rewriter_status.repaint()
        try:
            models = pr.list_models(url)
        except pr.RewriterError as e:
            self._rewriter_status.setText(str(e))
            self._rewriter_status.setStyleSheet(f"color: {COLORS['error']};")
            return
        current = self._rewriter_model.currentText().strip()
        self._rewriter_model.clear()
        self._rewriter_model.addItems(models)
        if current:
            idx = self._rewriter_model.findText(current)
            if idx >= 0:
                self._rewriter_model.setCurrentIndex(idx)
            else:
                self._rewriter_model.setEditText(current)
        self._rewriter_status.setText(f"Found {len(models)} model(s).")
        self._rewriter_status.setStyleSheet(f"color: {COLORS['success']};")

    # ── Model check & sync ──────────────────────────────────────────────

    def _s3_config_from_fields(self) -> dict:
        import model_sync as ms
        return {
            ms.CFG_S3_PROFILE: self._s3_profile.text().strip(),
            ms.CFG_S3_ENDPOINT: self._s3_endpoint.text().strip(),
            ms.CFG_S3_REGION: self._s3_region.text().strip(),
            ms.CFG_S3_BUCKET: self._s3_bucket.text().strip(),
            ms.CFG_S3_MODELS_PREFIX: self._s3_prefix.text().strip() or ms.S3_DEFAULTS[ms.CFG_S3_MODELS_PREFIX],
        }

    def _import_s3_browser(self):
        import model_sync as ms
        start = Path(r"P:/Apps/VibeCoded/S3 Browser/config.json")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the S3 Browser config.json",
            str(start if start.exists() else Path.home()), "JSON (*.json);;All Files (*)")
        if not path:
            return
        try:
            values = ms.import_s3_browser_config(path)
        except Exception as e:  # noqa: BLE001
            self._s3_status.setText(f"Could not read {path}: {e}")
            self._s3_status.setStyleSheet(f"color: {COLORS['error']};")
            return
        self._s3_profile.setText(values.get(ms.CFG_S3_PROFILE, self._s3_profile.text()))
        self._s3_endpoint.setText(values.get(ms.CFG_S3_ENDPOINT, self._s3_endpoint.text()))
        self._s3_region.setText(values.get(ms.CFG_S3_REGION, self._s3_region.text()))
        self._s3_bucket.setText(values.get(ms.CFG_S3_BUCKET, self._s3_bucket.text()))
        self._s3_status.setText(f"Imported {len(values)} value(s) from {Path(path).name}. Press Test connection to verify.")
        self._s3_status.setStyleSheet(f"color: {COLORS['fg_dim']};")

    def _test_s3(self):
        import model_sync as ms
        self._s3_status.setText("Connecting…")
        self._s3_status.setStyleSheet(f"color: {COLORS['fg_dim']};")
        self._s3_status.repaint()
        try:
            store = ms.S3ModelStore(self._s3_config_from_fields())
            store.test_connection()
            folders = store.list_folders()
            local = ms.local_models_dir({**self._config.get_all(), ms.CFG_MODELS_DIR: self._models_dir.text().strip()})
            self._s3_status.setText(
                f"OK — {len(folders)} model folder(s) under {store.prefix}: {', '.join(folders[:12])}"
                f"{'…' if len(folders) > 12 else ''}\nLocal models folder: {local or '(not set — set the LoRAs or Models folder)'}")
            self._s3_status.setStyleSheet(f"color: {COLORS['success']};")
        except ImportError:
            self._s3_status.setText("boto3 is not installed in the Python running this app — use the built EXE or the repo .venv")
            self._s3_status.setStyleSheet(f"color: {COLORS['error']};")
        except Exception as e:  # noqa: BLE001
            self._s3_status.setText(f"Failed: {type(e).__name__}: {e}")
            self._s3_status.setStyleSheet(f"color: {COLORS['error']};")

    # ── RunPod pod control ───────────────────────────────────────────────

    # The two saved preferences, read back out of the widgets.
    def _current_gpu_order(self) -> list[str]:
        return [self._gpu_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._gpu_list.count())]

    def _current_pod_order(self) -> list[str]:
        return [self._pod_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._pod_list.count())]

    def _load_pod_order(self):
        """Seed both lists from the config, then fetch the real pods.

        Until the fetch lands the pod list can only show bare ids, which say
        nothing about which card a row is — so the fetch is fired immediately
        rather than waiting for someone to press Refresh. It runs on a thread:
        opening Settings must not block on RunPod being reachable.
        """
        self._pods = {}
        self._list_worker = None

        self._gpu_list.clear()
        for gid in (self._config.get("runpod_gpu_order", []) or []):
            item = QListWidgetItem(gid)
            item.setData(Qt.ItemDataRole.UserRole, gid)
            self._gpu_list.addItem(item)

        self._pod_list.clear()
        for pod_id in (self._config.get("runpod_pod_order", []) or []):
            item = QListWidgetItem(pod_id)
            item.setData(Qt.ItemDataRole.UserRole, pod_id)
            self._pod_list.addItem(item)

        import runpod_api
        if runpod_api.have_key():
            self._refresh_pods()
        else:
            self._pod_status.setText(
                f"No API key — add one to {runpod_api.KEY_FILE_NAME} next to the app "
                f"to see pod names and GPUs.")
            self._pod_status.setStyleSheet(f"color: {COLORS['fg_dim']};")

    def _set_pods(self, pods: list[dict]):
        """Adopt a freshly fetched pod list into both widgets."""
        import runpod_api
        self._pods = {p.get("id"): p for p in pods if p.get("id")}

        # GPU models: saved ranking first, then anything new in account order.
        ranked = [g for g in self._current_gpu_order()
                  if any(runpod_api.gpu_id(p) == g for p in pods)]
        counts = dict(runpod_api.gpu_types(pods))
        for gid, _n in runpod_api.gpu_types(pods):
            if gid not in ranked:
                ranked.append(gid)

        self._gpu_list.clear()
        for gid in ranked:
            n = counts.get(gid, 0)
            item = QListWidgetItem(f"{gid}  —  {n} pod{'s' if n != 1 else ''}")
            item.setData(Qt.ItemDataRole.UserRole, gid)
            self._gpu_list.addItem(item)

        self._rebuild_pod_list()

    def _rebuild_pod_list(self, select_id: str | None = None):
        """Redraw the pod list as the order the chain will actually use.

        The list is the preview: GPU priority is applied here exactly as
        wake_first_available applies it, so what you see is what runs.
        """
        if not self._pods:
            return
        import runpod_api
        order = runpod_api.resolve_order(list(self._pods.values()),
                                         self._current_pod_order(),
                                         self._current_gpu_order())
        self._pod_list.clear()
        for n, pid in enumerate(order, 1):
            pod = self._pods[pid]
            item = QListWidgetItem(f"{n}.  {runpod_api.describe(pod)}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setData(Qt.ItemDataRole.UserRole + 1, runpod_api.gpu_id(pod))
            self._pod_list.addItem(item)
        if select_id in order:
            self._pod_list.setCurrentRow(order.index(select_id))

    def _move_gpu(self, delta: int):
        row = self._gpu_list.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < self._gpu_list.count()):
            return
        self._gpu_list.insertItem(new, self._gpu_list.takeItem(row))
        self._gpu_list.setCurrentRow(new)
        self._rebuild_pod_list()

    def _test_sound(self):
        import alerts
        path = self._alert_sound.text().strip()
        if alerts.play(path):
            self._pod_status.setText(f"Playing {Path(path).name}")
            self._pod_status.setStyleSheet(f"color: {COLORS['success']};")
        else:
            self._pod_status.setText("Pick an existing sound file first.")
            self._pod_status.setStyleSheet(f"color: {COLORS['error']};")

    def _use_pod(self, item):
        """Double-click: point the connection at this pod.

        The proxy URL is derived from the pod id and is stable for the life of
        the pod, so this needs no network call — it just fills in the RunPod URL
        and switches the mode across. Whether the pod is actually running is a
        separate question; Test connection answers that.
        """
        import runpod_api
        pod_id = item.data(Qt.ItemDataRole.UserRole)
        if not pod_id:
            return
        url = runpod_api.proxy_url(pod_id)
        self._runpod_url.setText(url)
        self._runpod_radio.setChecked(True)
        self._pod_status.setText(f"RunPod URL set to {pod_id}. Save to apply.")
        self._pod_status.setStyleSheet(f"color: {COLORS['success']};")

    def _move_pod(self, delta: int):
        """Move a pod within its own GPU group.

        Crossing a group boundary is not allowed: GPU priority is the outer
        key, so a pod dragged across one would simply snap back on the next
        redraw, which reads as a broken button.
        """
        row = self._pod_list.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < self._pod_list.count()):
            return
        if self._pods:
            gpu = self._pod_list.item(row).data(Qt.ItemDataRole.UserRole + 1)
            if self._pod_list.item(new).data(Qt.ItemDataRole.UserRole + 1) != gpu:
                self._pod_status.setText(
                    f"{gpu} is a different card — reorder the GPU priority list "
                    f"above to move a whole group.")
                self._pod_status.setStyleSheet(f"color: {COLORS['fg_dim']};")
                return

        pod_id = self._pod_list.item(row).data(Qt.ItemDataRole.UserRole)
        self._pod_list.insertItem(new, self._pod_list.takeItem(row))
        self._pod_list.setCurrentRow(new)
        if not self._pods:
            return
        self._rebuild_pod_list(select_id=pod_id)
        if self._pod_list.currentRow() != new:
            # resolve_order put it back: a RUNNING pod leads its group, because
            # using it costs nothing to start and nothing to wait for.
            self._pod_status.setText("A running pod is always tried first within its group.")
            self._pod_status.setStyleSheet(f"color: {COLORS['fg_dim']};")

    def _refresh_pods(self):
        """Fetch the account's pods on a thread, keeping both saved orders."""
        from ui.pod_worker import PodListWorker
        if self._list_worker is not None:
            return
        self._pod_status.setText("Fetching pods…")
        self._pod_status.setStyleSheet(f"color: {COLORS['fg_dim']};")
        self._list_worker = PodListWorker()
        self._list_worker.done.connect(self._pods_fetched)
        self._list_worker.balance.connect(self._balance_fetched)
        self._list_worker.finished.connect(self._list_worker_finished)
        self._list_worker.start()

    def _list_worker_finished(self):
        self._list_worker = None

    def _balance_fetched(self, info: dict, error: str):
        import runpod_api
        if error or not info:
            self._balance_lbl.setText(
                f"<span style='color:{COLORS['fg_dim']}'>Balance unavailable — {error or 'no data'}</span>")
            return
        # Solid light text; the dot carries the status (green, red when the
        # balance is nearly gone) — same scheme as the header readout.
        dot = COLORS["success"] if info["balance"] >= 20 else COLORS["error"]
        self._balance_lbl.setText(
            f"<span style='color:{dot}'>●</span> <span style='color:{COLORS['fg_primary']}'>"
            f"Account {runpod_api.balance_summary(info)}</span>")

    def _pods_fetched(self, pods: list, error: str):
        if error:
            self._pod_status.setText(error)
            self._pod_status.setStyleSheet(f"color: {COLORS['error']};")
            return
        self._set_pods(pods)
        groups = len({self._gpu_list.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(self._gpu_list.count())})
        self._pod_status.setText(
            f"{len(pods)} pod(s) across {groups} card model(s). "
            f"Order the cards first, then the pods within each.")
        self._pod_status.setStyleSheet(f"color: {COLORS['success']};")

    def _test_runpod_api(self):
        import runpod_api
        self._pod_status.setText("Checking RunPod…")
        self._pod_status.setStyleSheet(f"color: {COLORS['fg_dim']};")
        self._pod_status.repaint()
        ok, msg = runpod_api.test_connection()
        self._pod_status.setText(msg)
        self._pod_status.setStyleSheet(f"color: {COLORS['success' if ok else 'error']};")

    def _test_connection(self):
        from comfy_client import ComfyClient
        url = (self._runpod_url if self._runpod_radio.isChecked() else self._local_url).text().strip()
        if not url:
            self._test_status.setText("Enter a URL for the selected mode first.")
            return
        self._test_status.setText(f"Connecting to {url} …")
        self._test_status.repaint()
        try:
            stats = ComfyClient(url).test()
            sysinfo = stats.get("system", {}) or {}
            devs = stats.get("devices", []) or []
            gpu = devs[0].get("name", "") if devs else "no GPU reported"
            vram = devs[0].get("vram_total", 0) // (1024 ** 3) if devs else 0
            self._test_status.setText(
                f"OK — ComfyUI {sysinfo.get('comfyui_version', '')} · {gpu}"
                + (f" ({vram} GB)" if vram else ""))
            self._test_status.setStyleSheet(f"color: {COLORS['success']};")
        except Exception as e:  # noqa: BLE001
            self._test_status.setText(f"Failed: {type(e).__name__}: {e}")
            self._test_status.setStyleSheet(f"color: {COLORS['error']};")

    def _save(self):
        c = self._config
        c.set("mode", "runpod" if self._runpod_radio.isChecked() else "local")
        c.set("comfyui_url", self._local_url.text().strip())
        c.set("runpod_url", self._runpod_url.text().strip())
        c.set("image_dir", self._image_dir.text().strip())
        c.set("video_dir", self._video_dir.text().strip())
        c.set("workflow_dir", self._workflow_dir.text().strip())
        c.set("output_dir", self._output_dir.text().strip())
        c.set("loras_dir", self._loras_dir.text().strip())
        c.set("library_dir", self._library_dir.text().strip())
        c.set("output_per_workflow", bool(self._per_workflow.isChecked()))
        c.set("archive_dir", self._archive_dir.text().strip())
        c.set("staging_dir_local", self._staging_dir.text().strip())
        c.set("runpod_input_dir", self._runpod_input.text().strip())
        c.set("ffmpeg_path", self._ffmpeg.text().strip())
        c.set("prompt_font_size", int(self._font_spin.value()))
        c.set("image_blank_template", self._blank_image.currentData() or "")
        c.set("text_blank_template", self._blank_text.currentData() or "")
        c.set("rewriter_base_url", self._rewriter_url.text().strip())
        c.set("rewriter_model", self._rewriter_model.currentText().strip())
        c.set("runpod_gpu_order", self._current_gpu_order())
        c.set("runpod_pod_order", self._current_pod_order())
        c.set("runpod_spend_limit", float(self._spend_limit.value()))
        c.set("runpod_idle_stop_min", int(round(self._idle_stop.value() / 10) * 10))
        c.set("runpod_auto_prompt", bool(self._pod_prompt.isChecked()))
        c.set("runpod_auto_stop_on_exit", bool(self._pod_autostop.isChecked()))
        c.set("runpod_retry_interval_min", int(self._retry_interval.value()))
        c.set("runpod_retry_window_min", int(self._retry_window.value()))
        c.set("alert_sound_path", self._alert_sound.text().strip())
        c.set("alert_sound_enabled", bool(self._alert_enabled.isChecked()))
        import model_sync as ms
        c.set(ms.CFG_MODEL_CHECK, bool(self._sync_enabled.isChecked()))
        c.set(ms.CFG_DOWNLOAD, bool(self._sync_download.isChecked()))
        c.set(ms.CFG_MODELS_DIR, self._models_dir.text().strip())
        import remote_cleanup as rc
        c.set(rc.CFG_DELETE_AFTER, bool(self._delete_after.isChecked()))
        c.set(rc.CFG_OUTPUT_PREFIX, self._output_prefix.text().strip() or rc.DEFAULT_OUTPUT_PREFIX)
        for key, value in self._s3_config_from_fields().items():
            c.set(key, value)
        c.save()
        self.accept()
