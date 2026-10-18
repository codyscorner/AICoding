from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QFileDialog, QDialogButtonBox, QCheckBox, QTabWidget, QWidget,
    QListWidget, QListWidgetItem, QSpinBox, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt

from config import ConfigManager
from ui.styles import COLORS


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(820)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(parent.styleSheet() if parent else "")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Tabs rather than one long column: the pod lists would push a single
        # page past a 1080p screen, and each page is only as tall as itself.
        tabs = QTabWidget()
        layout.addWidget(tabs)

        def page(title: str) -> QVBoxLayout:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setSpacing(12)
            lay.setContentsMargins(16, 16, 16, 16)
            tabs.addTab(w, title)
            return lay

        general_tab = page("Server")
        runpod_tab = page("RunPod")
        models_tab = page("Models")

        # ── ComfyUI Server ────────────────────────────────────────────────
        server_group = QGroupBox("ComfyUI Server")
        server_layout = QVBoxLayout(server_group)
        server_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        self._local_radio  = QRadioButton("Local")
        self._runpod_radio = QRadioButton("RunPod")
        self._mode_btn_group = QButtonGroup()
        self._mode_btn_group.addButton(self._local_radio)
        self._mode_btn_group.addButton(self._runpod_radio)
        (self._runpod_radio if config.get("mode", "local") == "runpod"
         else self._local_radio).setChecked(True)
        mode_row.addWidget(self._local_radio)
        mode_row.addWidget(self._runpod_radio)
        mode_row.addStretch()
        server_layout.addLayout(mode_row)

        self._local_url_edit = self._text_row(
            server_layout, "Local URL:",
            config.get("comfyui_url", "http://127.0.0.1:8188"),
            "http://127.0.0.1:8188",
        )
        self._runpod_edit = self._text_row(
            server_layout, "RunPod URL:",
            config.get("runpod_url", ""),
            "https://YOUR-POD-ID-8188.proxy.runpod.net/  (Start Pod fills this in)",
        )
        general_tab.addWidget(server_group)

        general_tab.addStretch()

        self._build_runpod_tab(runpod_tab)
        self._build_models_tab(models_tab)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #
    # RunPod tab (copied from ComfyUI Video Creator's Settings > RunPod)
    # ------------------------------------------------------------------ #

    def _build_runpod_tab(self, runpod_tab: QVBoxLayout):
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
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setObjectName("small_btn")
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
        self._spend_limit.setValue(float(self._config.get("runpod_spend_limit", 0) or 0))
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
        self._idle_stop.setValue(int(self._config.get("runpod_idle_stop_min", 0) or 0))
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
        self._retry_interval.setValue(int(self._config.get("runpod_retry_interval_min", 10) or 10))
        self._retry_interval.setToolTip("How often to sweep the pod list when every pod is busy")
        retry_row.addWidget(self._retry_interval)
        retry_row.addWidget(QLabel("for"))
        self._retry_window = QSpinBox()
        self._retry_window.setRange(5, 1440)
        self._retry_window.setSuffix(" min")
        self._retry_window.setSingleStep(15)
        self._retry_window.setValue(int(self._config.get("runpod_retry_window_min", 120) or 120))
        self._retry_window.setToolTip("Give up after this long and stop looking")
        retry_row.addWidget(self._retry_window)
        retry_row.addStretch()
        pl.addLayout(retry_row)

        self._alert_sound = self._audio_row(
            pl, "Alert sound:", self._config.get("alert_sound_path", ""),
            "Played when a pod is found, when giving up, and when a run finishes (.wav plays inline)…")
        sound_row = QHBoxLayout()
        self._alert_enabled = QCheckBox("Play alert sound")
        self._alert_enabled.setChecked(bool(self._config.get("alert_sound_enabled", True)))
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
        self._pod_prompt.setChecked(bool(self._config.get("runpod_auto_prompt", True)))
        self._pod_autostop = QCheckBox("Stop pod on exit")
        self._pod_autostop.setToolTip("When quitting with a pod connected, ask whether to stop it or leave it running")
        self._pod_autostop.setChecked(bool(self._config.get("runpod_auto_stop_on_exit", True)))
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
        runpod_tab.addStretch()
        self._load_pod_order()

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
    # Models tab (copied from ComfyUI Video Creator's Settings > Models)
    # ------------------------------------------------------------------ #

    def _build_models_tab(self, models_tab: QVBoxLayout):
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
        self._sync_enabled.setChecked(bool(self._config.get(ms.CFG_MODEL_CHECK, True)))
        syl.addWidget(self._sync_enabled)
        self._sync_download = QCheckBox("Always download pod-only models to this PC without asking "
                                        "(off: you are asked each time — the pod run works either way)")
        self._sync_download.setChecked(bool(self._config.get(ms.CFG_DOWNLOAD, False)))
        syl.addWidget(self._sync_download)
        self._models_dir = self._folder_row(syl, "Models folder:", self._config.get(ms.CFG_MODELS_DIR, ""),
                                            "ComfyUI/models root — blank = the parent of the LoRAs folder…")
        self._s3_profile = self._text_row(syl, "AWS profile:", self._config.get(ms.CFG_S3_PROFILE, "runpod-s3"),
                                          "Profile in %USERPROFILE%\\.aws\\credentials holding the RunPod S3 keys (e.g. runpod-s3)…")
        self._s3_endpoint = self._text_row(syl, "Endpoint URL:", self._config.get(ms.CFG_S3_ENDPOINT, ""),
                                           "https://s3api-<datacenter>.runpod.io")
        self._s3_region = self._text_row(syl, "Region:", self._config.get(ms.CFG_S3_REGION, ""),
                                         "RunPod datacenter id (e.g. us-ks-2)")
        self._s3_bucket = self._text_row(syl, "Bucket:", self._config.get(ms.CFG_S3_BUCKET, ""),
                                         "Network volume id (e.g. pjez3nxwp9)")
        self._s3_prefix = self._text_row(syl, "Models prefix:", self._config.get(ms.CFG_S3_MODELS_PREFIX, ""),
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
        models_tab.addStretch()

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
                f"{'…' if len(folders) > 12 else ''}\nLocal models folder: {local or '(not set — set the Models folder)'}")
            self._s3_status.setStyleSheet(f"color: {COLORS['success']};")
        except ImportError:
            self._s3_status.setText("boto3 is not installed in the Python running this app — use the built EXE or the repo .venv")
            self._s3_status.setStyleSheet(f"color: {COLORS['error']};")
        except Exception as e:  # noqa: BLE001
            self._s3_status.setText(f"Failed: {type(e).__name__}: {e}")
            self._s3_status.setStyleSheet(f"color: {COLORS['error']};")

    # ------------------------------------------------------------------ #
    # Row builders
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

    def _audio_row(self, parent_layout, label: str, value: str, placeholder: str) -> QLineEdit:
        import alerts
        row = QHBoxLayout()
        row.addWidget(self._label(label))
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("Browse")
        btn.setObjectName("small_btn")
        btn.clicked.connect(lambda: self._browse_audio(edit, alerts.WAV_FILTER))
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit

    def _browse_audio(self, edit: QLineEdit, filt: str):
        current = edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select an alert sound", current or str(Path.home()), filt)
        if path:
            edit.setText(path)

    def _text_row(self, parent_layout, label: str, value: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(120)
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        parent_layout.addLayout(row)
        return edit

    def _folder_row(self, parent_layout, label: str, value: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(120)
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("Browse")
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda: self._browse_folder(edit))
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit

    def _file_row(self, parent_layout, label: str, value: str,
                  placeholder: str, file_filter: str = "") -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(120)
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        btn = QPushButton("Browse")
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda: self._browse_file(edit, file_filter))
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit

    def _file_row_with_extra(self, parent_layout, label: str, value: str,
                              placeholder: str, file_filter: str = "",
                              extra_label: str = "") -> tuple[QLineEdit, QPushButton]:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(120)
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(30)
        browse_btn.clicked.connect(lambda: self._browse_file(edit, file_filter))
        extra_btn = QPushButton(extra_label)
        extra_btn.setFixedWidth(52)
        extra_btn.setFixedHeight(30)
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        row.addWidget(browse_btn)
        row.addWidget(extra_btn)
        parent_layout.addLayout(row)
        return edit, extra_btn

    def _key_row(self, parent_layout, label: str, value: str, hint: str, url: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(150)
        edit = QLineEdit(value)
        edit.setPlaceholderText(hint)
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        parent_layout.addLayout(row)

        hint_lbl = QLabel(f'<a href="{url}" style="color:{COLORS["accent_hover"]};">{hint}</a>')
        hint_lbl.setObjectName("subtitle")
        hint_lbl.setOpenExternalLinks(True)
        hint_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        hint_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        hint_row = QHBoxLayout()
        hint_row.addSpacing(150)
        hint_row.addWidget(hint_lbl)
        parent_layout.addLayout(hint_row)
        return edit

    # ------------------------------------------------------------------ #
    # Browse helpers
    # ------------------------------------------------------------------ #

    def _browse_folder(self, edit: QLineEdit):
        current = edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", current or str(Path.home()))
        if folder:
            edit.setText(folder)

    def _browse_file(self, edit: QLineEdit, file_filter: str = ""):
        current = edit.text().strip()
        start = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Select File", start, file_filter or "All Files (*)")
        if path:
            edit.setText(path)

    # ------------------------------------------------------------------ #
    # Save
    # ------------------------------------------------------------------ #

    def _save(self):
        self._config.set("mode", "local" if self._local_radio.isChecked() else "runpod")
        self._config.set("comfyui_url",    self._local_url_edit.text().strip())
        self._config.set("runpod_url",     self._runpod_edit.text().strip())
        c = self._config
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
        for key, value in self._s3_config_from_fields().items():
            c.set(key, value)
        self._config.save()
        self.accept()
