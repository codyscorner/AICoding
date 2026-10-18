from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QFileDialog, QDialogButtonBox, QCheckBox, QWidget, QTabWidget,
    QListWidget, QListWidgetItem, QSpinBox, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt

from config import ConfigManager
from ui.styles import COLORS
from lora_sync import (
    CFG_S3_PROFILE, CFG_S3_REGION, CFG_S3_ENDPOINT, CFG_S3_BUCKET,
    CFG_S3_LORAS_PREFIX, CFG_LORA_CHECK, S3_DEFAULTS, import_s3_browser_config,
)
from remote_cleanup import CFG_DELETE_AFTER, CFG_OUTPUT_PREFIX, DEFAULT_OUTPUT_PREFIX


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

        # Tabs rather than the old two columns (v3.10.1): the RunPod pod
        # control group (GPU list + pod list) would not fit beside the S3
        # group on a 1080p screen, and tabs give every page the full width.
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
        volume_tab = page("RunPod Volume")
        other_tab = page("Prompts && Sound")

        # ── ComfyUI Server ────────────────────────────────────────────────
        server_group = QGroupBox("ComfyUI Server")
        server_layout = QVBoxLayout(server_group)
        server_layout.setSpacing(10)

        mode_row = QHBoxLayout()
        self._local_radio = QRadioButton("Local")
        self._runpod_radio = QRadioButton("RunPod")
        self._mode_btn_group = QButtonGroup(self)
        self._mode_btn_group.addButton(self._local_radio)
        self._mode_btn_group.addButton(self._runpod_radio)
        if config.get("mode", "local") == "runpod":
            self._runpod_radio.setChecked(True)
        else:
            self._local_radio.setChecked(True)
        mode_row.addWidget(self._local_radio)
        mode_row.addWidget(self._runpod_radio)
        mode_row.addStretch()
        server_layout.addLayout(mode_row)

        self._local_url_edit, _ = self._text_row(
            server_layout, "Local URL:",
            config.get("comfyui_url", "http://127.0.0.1:8000"),
            "http://127.0.0.1:8000"
        )
        self._runpod_edit, _ = self._text_row(
            server_layout, "RunPod URL:",
            config.get("runpod_url", ""),
            "https://xxxxxx-8188.proxy.runpod.net"
        )
        server_tab.addWidget(server_group)

        # ── Batch Processing ─────────────────────────────────────────────
        batch_group = QGroupBox("Batch Processing")
        batch_layout = QVBoxLayout(batch_group)
        batch_layout.setSpacing(10)
        self._batch_local_edit, _ = self._folder_row(
            batch_layout, "Local Dir:",
            config.get("batch_dir_local", ""),
            "Local path where batch images are staged (e.g. B:/Batch_Processing)..."
        )
        self._batch_runpod_edit, _ = self._text_row(
            batch_layout, "RunPod Dir:",
            config.get("batch_dir_runpod", "/workspace/runpod-slim/Batch_Processing"),
            "RunPod path to the same folder (e.g. /workspace/runpod-slim/Batch_Processing)..."
        )
        self._runpod_input_edit, _ = self._text_row(
            batch_layout, "RunPod Input:",
            config.get("runpod_input_dir", "/workspace/runpod-slim/ComfyUI/input"),
            "Absolute path to ComfyUI's input folder on RunPod..."
        )
        server_tab.addWidget(batch_group)

        # ── Folders ───────────────────────────────────────────────────────
        folders_group = QGroupBox("Folders")
        folders_layout = QVBoxLayout(folders_group)
        folders_layout.setSpacing(10)

        self._workflow_edit, _ = self._folder_row(
            folders_layout, "Workflows:",
            config.get("workflow_dir", ""),
            "Folder containing workflow_segment_XX.json files..."
        )
        self._loras_edit, _ = self._folder_row(
            folders_layout, "LoRAs:",
            config.get("loras_dir", ""),
            "ComfyUI models/loras folder of the portable install you run (segment editor dropdown + LoRA check)..."
        )
        self._final_edit, _ = self._folder_row(
            folders_layout, "Final Video:",
            config.get("final_video_dir", ""),
            "Folder for the stitched final video..."
        )
        self._zip_edit, _ = self._folder_row(
            folders_layout, "Archive (.zip):",
            config.get("zip_output_dir", ""),
            "Folder for completed zip archives..."
        )
        folders_tab.addWidget(folders_group)

        # ── FFmpeg ────────────────────────────────────────────────────────
        ffmpeg_group = QGroupBox("FFmpeg")
        ffmpeg_layout = QVBoxLayout(ffmpeg_group)
        self._ffmpeg_edit, _ = self._file_row(
            ffmpeg_layout, "FFmpeg Path:",
            config.get("ffmpeg_path", "ffmpeg"),
            "Path to ffmpeg.exe (or 'ffmpeg' if on PATH)..."
        )
        folders_tab.addWidget(ffmpeg_group)

        # ── RunPod pod control (copied from ComfyUI Video Creator) ───────
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
        # over-commits the page and makes Qt overlap the rows below it.
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
        self._spend_limit.setToolTip(
            "Compute only — storage bills separately.\n"
            "A safety net, not a hard cap: it can only act while the app is running, "
            "so a crash or reboot leaves the pod up.")
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
            "When a batch finishes (Auto Run included) and nothing else starts, stop the "
            "connected pod after this long.\n"
            "A new batch cancels the countdown. Only works while the app is running.")
        idle_row.addWidget(self._idle_stop)
        idle_row.addWidget(QLabel("after the last batch finishes — 0 = off"))
        idle_row.addStretch()
        pl.addLayout(idle_row)

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

        # ── RunPod Volume (S3) — LoRA check / sync ───────────────────────
        s3_group = QGroupBox("RunPod Volume (S3) — LoRA check && sync, result cleanup")
        s3_layout = QVBoxLayout(s3_group)
        s3_layout.setSpacing(10)
        self._lora_check_chk = QCheckBox(
            "Verify a chain's LoRAs exist locally (and on the pod in RunPod mode) before starting")
        self._lora_check_chk.setChecked(bool(config.get(CFG_LORA_CHECK, S3_DEFAULTS[CFG_LORA_CHECK])))
        s3_layout.addWidget(self._lora_check_chk)
        self._s3_profile_edit, _ = self._text_row(
            s3_layout, "AWS Profile:",
            config.get(CFG_S3_PROFILE, S3_DEFAULTS[CFG_S3_PROFILE]),
            "Profile name in %USERPROFILE%\\.aws\\credentials holding the RunPod S3 keys (e.g. runpod-s3)..."
        )
        self._s3_endpoint_edit, _ = self._text_row(
            s3_layout, "Endpoint URL:",
            config.get(CFG_S3_ENDPOINT, ""),
            "https://s3api-<datacenter>.runpod.io"
        )
        self._s3_region_edit, _ = self._text_row(
            s3_layout, "Region:",
            config.get(CFG_S3_REGION, ""),
            "RunPod datacenter id (e.g. us-ks-2)"
        )
        self._s3_bucket_edit, _ = self._text_row(
            s3_layout, "Bucket:",
            config.get(CFG_S3_BUCKET, ""),
            "Network volume id (e.g. pjez3nxwp9)"
        )
        self._s3_prefix_edit, _ = self._text_row(
            s3_layout, "LoRA Prefix:",
            config.get(CFG_S3_LORAS_PREFIX, S3_DEFAULTS[CFG_S3_LORAS_PREFIX]),
            "Path of ComfyUI's models/loras folder inside the bucket (e.g. runpod-slim/ComfyUI/models/loras/)"
        )
        self._delete_after_chk = QCheckBox(
            "Delete segment videos from the pod volume after download (size verified)")
        self._delete_after_chk.setToolTip(
            "ComfyUI keeps every finished video in its output folder on the volume, which is billed per GB. "
            "Each RunPod result is deleted through the S3 connection only if the downloaded file's size "
            "matches the one on the volume. A failed cleanup never fails the run.")
        self._delete_after_chk.setChecked(bool(config.get(CFG_DELETE_AFTER, False)))
        s3_layout.addWidget(self._delete_after_chk)
        self._s3_output_prefix_edit, _ = self._text_row(
            s3_layout, "Output Prefix:",
            config.get(CFG_OUTPUT_PREFIX, DEFAULT_OUTPUT_PREFIX),
            "Path of ComfyUI's output folder inside the bucket (e.g. runpod-slim/ComfyUI/output/)"
        )
        s3_btn_row = QHBoxLayout()
        s3_btn_row.addStretch()
        import_btn = QPushButton("Import from S3 Browser config...")
        import_btn.setToolTip("Copy profile / endpoint / region / bucket from the S3 Browser app's config.json")
        import_btn.clicked.connect(self._import_s3_browser)
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._test_s3)
        s3_btn_row.addWidget(import_btn)
        s3_btn_row.addWidget(test_btn)
        s3_layout.addLayout(s3_btn_row)
        self._s3_status = QLabel("")
        self._s3_status.setWordWrap(True)
        self._s3_status.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:9pt;")
        s3_layout.addWidget(self._s3_status)
        volume_tab.addWidget(s3_group)

        # ── AI Prompt Writer ─────────────────────────────────────────────
        prompt_ai_group = QGroupBox("AI Prompt Writer")
        prompt_ai_layout = QVBoxLayout(prompt_ai_group)
        self._anthropic_key_edit, _ = self._text_row(
            prompt_ai_layout, "API Key:",
            config.get("anthropic_api_key", ""),
            "Anthropic API key (console.anthropic.com) — used by the Prompt Writer tab..."
        )
        self._anthropic_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        other_tab.addWidget(prompt_ai_group)

        # ── Alert Sound (batch finished + pod events) ─────────────────────
        sound_group = QGroupBox("Alert Sound")
        sound_layout = QVBoxLayout(sound_group)
        sound_layout.setSpacing(10)

        sound_layout.addWidget(self._caption(
            "One sound for everything worth walking back to the desk for: a batch finishes, "
            "a RunPod pod is found after Keep Trying, or the app gives up looking."))
        self._sound_file_edit, _ = self._audio_file_row(
            sound_layout, "Sound File:",
            config.get("alert_sound_path", ""),
            "Path to a .wav (plays inline) or .mp3 (opened with the default player) audio file..."
        )
        sound_row = QHBoxLayout()
        self._sound_enabled_chk = QCheckBox("Play alert sound")
        self._sound_enabled_chk.setChecked(bool(config.get("alert_sound_enabled", True)))
        self._sound_enabled_chk.setStyleSheet(f"color: {COLORS['fg_primary']};")
        sound_row.addWidget(self._sound_enabled_chk)
        test_sound = QPushButton("Test")
        test_sound.setObjectName("small_btn")
        test_sound.setFixedWidth(60)
        test_sound.clicked.connect(self._test_sound)
        sound_row.addWidget(test_sound)
        sound_row.addStretch()
        sound_layout.addLayout(sound_row)
        self._sound_status = QLabel("")
        self._sound_status.setObjectName("status_dim")
        sound_layout.addWidget(self._sound_status)
        other_tab.addWidget(sound_group)

        for lay in (server_tab, folders_tab, runpod_tab, volume_tab, other_tab):
            lay.addStretch()

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #
    # Row builders
    # ------------------------------------------------------------------ #

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFixedWidth(110)
        lbl.setStyleSheet(f"color: {COLORS['fg_primary']};")
        return lbl

    def _caption(self, text: str) -> QLabel:
        """Full-width note above a list — unlike _label, which pins itself
        to 110px to keep the form's label column aligned."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("status_dim")
        return lbl

    def _text_row(self, parent_layout, label: str, value: str, placeholder: str):
        row = QHBoxLayout()
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        row.addWidget(self._label(label))
        row.addWidget(edit, stretch=1)
        parent_layout.addLayout(row)
        return edit, None

    def _folder_row(self, parent_layout, label: str, value: str, placeholder: str):
        row = QHBoxLayout()
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("...")
        btn.setFixedWidth(40)
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda: self._browse_folder(edit))
        row.addWidget(self._label(label))
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit, btn

    def _file_row(self, parent_layout, label: str, value: str, placeholder: str):
        row = QHBoxLayout()
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("...")
        btn.setFixedWidth(40)
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda: self._browse_file(edit))
        row.addWidget(self._label(label))
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit, btn

    def _browse_folder(self, edit: QLineEdit):
        current = edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", current or str(Path.home()))
        if folder:
            edit.setText(folder)

    def _audio_file_row(self, parent_layout, label: str, value: str, placeholder: str):
        row = QHBoxLayout()
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("...")
        btn.setFixedWidth(40)
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda: self._browse_audio(edit))
        row.addWidget(self._label(label))
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit, btn

    def _browse_file(self, edit: QLineEdit):
        current = edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FFmpeg", current or str(Path.home()),
            "Executables (*.exe);;All Files (*)"
        )
        if path:
            edit.setText(path)

    def _browse_audio(self, edit: QLineEdit):
        import alerts
        current = edit.text().strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", start_dir, alerts.WAV_FILTER)
        if path:
            edit.setText(path)

    def _test_sound(self):
        import alerts
        path = self._sound_file_edit.text().strip()
        if alerts.play(path):
            self._sound_status.setText(f"Playing {Path(path).name}")
            self._sound_status.setStyleSheet(f"color: {COLORS['success']};")
        else:
            self._sound_status.setText("Pick an existing sound file first.")
            self._sound_status.setStyleSheet(f"color: {COLORS['error']};")

    # ------------------------------------------------------------------ #
    # RunPod Volume (S3)
    # ------------------------------------------------------------------ #

    def _s3_config_from_fields(self) -> dict:
        return {
            CFG_S3_PROFILE: self._s3_profile_edit.text().strip(),
            CFG_S3_ENDPOINT: self._s3_endpoint_edit.text().strip(),
            CFG_S3_REGION: self._s3_region_edit.text().strip(),
            CFG_S3_BUCKET: self._s3_bucket_edit.text().strip(),
            CFG_S3_LORAS_PREFIX: self._s3_prefix_edit.text().strip() or S3_DEFAULTS[CFG_S3_LORAS_PREFIX],
        }

    def _import_s3_browser(self):
        start = Path(r"P:/Apps/VibeCoded/S3 Browser/config.json")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the S3 Browser config.json",
            str(start if start.exists() else Path.home()),
            "JSON (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            values = import_s3_browser_config(path)
        except Exception as e:  # noqa: BLE001
            self._s3_status.setText(f"Could not read {path}: {e}")
            return
        self._s3_profile_edit.setText(values.get(CFG_S3_PROFILE, self._s3_profile_edit.text()))
        self._s3_endpoint_edit.setText(values.get(CFG_S3_ENDPOINT, self._s3_endpoint_edit.text()))
        self._s3_region_edit.setText(values.get(CFG_S3_REGION, self._s3_region_edit.text()))
        self._s3_bucket_edit.setText(values.get(CFG_S3_BUCKET, self._s3_bucket_edit.text()))
        self._s3_status.setText(f"Imported {len(values)} value(s) from {Path(path).name}. Press Test connection to verify.")

    def _test_s3(self):
        from lora_sync import S3LoraStore
        self._s3_status.setText("Connecting...")
        self._s3_status.repaint()
        try:
            store = S3LoraStore(self._s3_config_from_fields())
            store.test_connection()
            count = len(store.list_remote())
            self._s3_status.setText(f"OK — {count} LoRA file(s) found under {store.prefix}")
        except Exception as e:  # noqa: BLE001
            self._s3_status.setText(f"Failed: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------ #
    # RunPod pod control (copied from ComfyUI Video Creator)
    # ------------------------------------------------------------------ #

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

    def _use_pod(self, item):
        """Double-click: point the connection at this pod.

        The proxy URL is derived from the pod id and is stable for the life of
        the pod, so this needs no network call — it just fills in the RunPod URL
        and switches the mode across. Whether the pod is actually running is a
        separate question.
        """
        import runpod_api
        pod_id = item.data(Qt.ItemDataRole.UserRole)
        if not pod_id:
            return
        url = runpod_api.proxy_url(pod_id)
        self._runpod_edit.setText(url)
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

    # ------------------------------------------------------------------ #

    def _save(self):
        self._config.set("mode", "local" if self._local_radio.isChecked() else "runpod")
        self._config.set(CFG_LORA_CHECK, self._lora_check_chk.isChecked())
        self._config.set(CFG_DELETE_AFTER, self._delete_after_chk.isChecked())
        self._config.set(CFG_OUTPUT_PREFIX, self._s3_output_prefix_edit.text().strip() or DEFAULT_OUTPUT_PREFIX)
        for key, value in self._s3_config_from_fields().items():
            self._config.set(key, value)
        self._config.set("comfyui_url", self._local_url_edit.text().strip())
        self._config.set("runpod_url", self._runpod_edit.text().strip())
        self._config.set("workflow_dir", self._workflow_edit.text().strip())
        self._config.set("loras_dir", self._loras_edit.text().strip())
        self._config.set("final_video_dir", self._final_edit.text().strip())
        self._config.set("zip_output_dir", self._zip_edit.text().strip())
        self._config.set("batch_dir_local", self._batch_local_edit.text().strip())
        self._config.set("batch_dir_runpod", self._batch_runpod_edit.text().strip())
        self._config.set("runpod_input_dir", self._runpod_input_edit.text().strip())
        self._config.set("ffmpeg_path", self._ffmpeg_edit.text().strip())
        self._config.set("anthropic_api_key", self._anthropic_key_edit.text().strip())
        # RunPod pod control
        self._config.set("runpod_gpu_order", self._current_gpu_order())
        self._config.set("runpod_pod_order", self._current_pod_order())
        self._config.set("runpod_spend_limit", float(self._spend_limit.value()))
        self._config.set("runpod_idle_stop_min", int(round(self._idle_stop.value() / 10) * 10))
        self._config.set("runpod_auto_prompt", bool(self._pod_prompt.isChecked()))
        self._config.set("runpod_auto_stop_on_exit", bool(self._pod_autostop.isChecked()))
        self._config.set("runpod_retry_interval_min", int(self._retry_interval.value()))
        self._config.set("runpod_retry_window_min", int(self._retry_window.value()))
        self._config.set("alert_sound_path", self._sound_file_edit.text().strip())
        self._config.set("alert_sound_enabled", bool(self._sound_enabled_chk.isChecked()))
        self._config.save()
        self.accept()
