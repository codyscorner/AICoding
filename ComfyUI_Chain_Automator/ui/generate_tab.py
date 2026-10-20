from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QTextEdit, QSpinBox,
    QComboBox, QListWidget, QMessageBox, QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QDragEnterEvent, QDropEvent

from config import ConfigManager
from image_gen_worker import ImageGenWorker
from ui.styles import COLORS
from ui.widgets import ThumbnailGrid, THUMB_SIZE
from ui.prompt_history import append_history, PromptHistoryDialog

REF_THUMB = 130  # px for reference image drop zones


# ------------------------------------------------------------------ #
# Reference image drop zone
# ------------------------------------------------------------------ #

class _RefSlot(QLabel):
    """Drop zone — click to browse, drag & drop an image, shows preview."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._path: Path | None = None
        self._label = label
        self.setFixedSize(REF_THUMB, REF_THUMB)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_empty()

    @property
    def path(self) -> Path | None:
        return self._path

    def _set_empty(self):
        self._path = None
        self.setPixmap(QPixmap())
        self.setText(f"{self._label}\n\nDrag & drop\nor click")
        self.setStyleSheet(
            f"QLabel {{ background-color:{COLORS['bg_dark']};"
            f" border:2px dashed {COLORS['border']}; border-radius:6px;"
            f" color:{COLORS['fg_dim']}; font-size:8pt; }}"
        )

    def set_image(self, path: Path):
        self._path = path
        pix = QPixmap(str(path))
        if not pix.isNull():
            pix = pix.scaled(REF_THUMB - 4, REF_THUMB - 4,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            canvas = QPixmap(REF_THUMB - 4, REF_THUMB - 4)
            canvas.fill(Qt.GlobalColor.black)
            painter = QPainter(canvas)
            painter.drawPixmap((canvas.width() - pix.width()) // 2,
                               (canvas.height() - pix.height()) // 2, pix)
            painter.end()
            self.setPixmap(canvas)
            self.setText("")
        self.setStyleSheet(
            f"QLabel {{ background-color:{COLORS['bg_medium']};"
            f" border:2px solid {COLORS['accent']}; border-radius:6px; }}"
        )
        self.setToolTip(path.name)

    def clear(self):
        self._set_empty()
        self.setToolTip("")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, f"Select {self._label}", "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
            )
            if path:
                self.set_image(Path(path))

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                self.set_image(path)


class GenerateTab(QWidget):
    send_to_chain = pyqtSignal(str)    # user clicked "Send to Chain"
    start_one_shot = pyqtSignal(str)   # generate + auto-start chain

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self._worker: ImageGenWorker | None = None
        self._pending_oneshot = False
        self._generated: list[str] = []
        self._build_ui()
        self.refresh_workflows()
        self.refresh_mode()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def set_positive_prompt(self, text: str):
        self._pos_edit.setPlainText(text)

    def _build_ui(self):
        split = QHBoxLayout(self)
        split.setContentsMargins(0, 4, 0, 0)
        split.setSpacing(12)
        split.addLayout(self._build_controls(), stretch=2)
        split.addLayout(self._build_gallery(), stretch=3)

    def _build_controls(self) -> QVBoxLayout:
        left = QVBoxLayout()
        left.setSpacing(8)

        # ── Workflow ──────────────────────────────────────────────────────
        wf_group = QGroupBox("Workflow")
        wf_layout = QHBoxLayout(wf_group)
        self._wf_combo = QComboBox()
        self._wf_combo.setMinimumHeight(30)
        self._wf_combo.currentIndexChanged.connect(self._on_workflow_changed)
        refresh_wf_btn = QPushButton("↻ Refresh")
        refresh_wf_btn.setObjectName("small_btn")
        refresh_wf_btn.setFixedHeight(30)
        refresh_wf_btn.setToolTip("Refresh workflow list")
        refresh_wf_btn.clicked.connect(self.refresh_workflows)
        wf_layout.addWidget(self._wf_combo, stretch=1)
        wf_layout.addWidget(refresh_wf_btn)
        left.addWidget(wf_group)

        # ── Prompts ───────────────────────────────────────────────────────
        prompt_group = QGroupBox("Prompts")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_layout.setSpacing(6)

        pos_lbl = QLabel("Positive")
        pos_lbl.setStyleSheet(f"color:{COLORS['success']}; font-size:9pt; font-weight:bold;")
        self._pos_edit = QTextEdit()
        self._pos_edit.setPlaceholderText("Describe what you want to generate...")
        self._pos_edit.setFixedHeight(110)
        self._pos_edit.setText(self._config.get("image_gen_positive", ""))

        neg_lbl = QLabel("Negative")
        neg_lbl.setStyleSheet(f"color:{COLORS['error']}; font-size:9pt; font-weight:bold;")
        self._neg_edit = QTextEdit()
        self._neg_edit.setPlaceholderText("What to avoid...")
        self._neg_edit.setFixedHeight(70)
        self._neg_edit.setText(self._config.get("image_gen_negative", ""))

        prompt_layout.addWidget(pos_lbl)
        prompt_layout.addWidget(self._pos_edit)
        prompt_layout.addWidget(neg_lbl)
        prompt_layout.addWidget(self._neg_edit)

        hist_row = QHBoxLayout()
        self._save_hist_btn = QPushButton("💾  Save to History")
        self._save_hist_btn.clicked.connect(self._on_save_history)
        self._view_hist_btn = QPushButton("📜  History")
        self._view_hist_btn.clicked.connect(self._on_view_history)
        self._hist_status_lbl = QLabel("")
        self._hist_status_lbl.setStyleSheet(f"color:{COLORS['fg_dim']}; font-size:8pt;")
        hist_row.addWidget(self._save_hist_btn)
        hist_row.addWidget(self._view_hist_btn)
        hist_row.addWidget(self._hist_status_lbl, stretch=1)
        prompt_layout.addLayout(hist_row)

        left.addWidget(prompt_group)

        # ── Reference Images ──────────────────────────────────────────────
        ref_group = QGroupBox("Reference Images  (optional — image edit / compose)")
        ref_layout = QHBoxLayout(ref_group)
        ref_layout.setSpacing(10)
        ref_layout.setContentsMargins(8, 10, 8, 10)
        self._ref_slot1 = _RefSlot("Person / Image 1")
        self._ref_slot2 = _RefSlot("Person / Image 2")
        clear_both_btn = QPushButton("Clear Both")
        clear_both_btn.setFixedWidth(200)
        clear_both_btn.setFixedHeight(36)
        clear_both_btn.setObjectName("cancel_btn")
        clear_both_btn.clicked.connect(lambda: (self._ref_slot1.clear(), self._ref_slot2.clear()))
        ref_layout.addWidget(self._ref_slot1)
        ref_layout.addWidget(self._ref_slot2)
        ref_layout.addStretch()
        ref_layout.addWidget(clear_both_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        left.addWidget(ref_group)

        # ── Seed + mode ───────────────────────────────────────────────────
        seed_row = QHBoxLayout()
        seed_lbl = QLabel("Seed:")
        seed_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(-1, 2_147_483_647)
        self._seed_spin.setValue(-1)
        self._seed_spin.setSpecialValueText("Random")
        self._seed_spin.setFixedHeight(30)
        self._seed_spin.setToolTip("-1 = randomize each run")
        rand_btn = QPushButton("🎲 Random")
        rand_btn.setObjectName("small_btn")
        rand_btn.setFixedHeight(30)
        rand_btn.setToolTip("Set to random")
        rand_btn.clicked.connect(lambda: self._seed_spin.setValue(-1))
        self._mode_lbl = QLabel()
        self._mode_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seed_row.addWidget(seed_lbl)
        seed_row.addWidget(self._seed_spin)
        seed_row.addWidget(rand_btn)
        seed_row.addStretch()
        seed_row.addWidget(self._mode_lbl)
        left.addLayout(seed_row)

        # ── Log ───────────────────────────────────────────────────────────
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 4, 4, 4)
        self._log_list = QListWidget()
        self._log_list.setFixedHeight(100)
        self._log_list.setSpacing(-1)
        self._log_list.setUniformItemSizes(True)
        log_layout.addWidget(self._log_list)
        left.addWidget(log_group)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._gen_btn = QPushButton("✨  Generate")
        self._gen_btn.setMinimumHeight(40)
        self._gen_btn.clicked.connect(self._on_generate)

        self._oneshot_btn = QPushButton("⚡  Generate + Run Chain")
        self._oneshot_btn.setMinimumHeight(40)
        self._oneshot_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent']}; color: white;"
            f" border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #7060eb; }}"
            f"QPushButton:disabled {{ background-color: {COLORS['bg_light']};"
            f" color: {COLORS['fg_dim']}; }}"
        )
        self._oneshot_btn.clicked.connect(self._on_generate_oneshot)

        self._cancel_gen_btn = QPushButton("✕  Cancel")
        self._cancel_gen_btn.setObjectName("cancel_btn")
        self._cancel_gen_btn.setMinimumHeight(40)
        self._cancel_gen_btn.setEnabled(False)
        self._cancel_gen_btn.clicked.connect(self._on_cancel)

        btn_row.addWidget(self._gen_btn)
        btn_row.addWidget(self._oneshot_btn)
        btn_row.addWidget(self._cancel_gen_btn)
        left.addLayout(btn_row)
        left.addStretch()

        return left

    def _build_gallery(self) -> QVBoxLayout:
        right = QVBoxLayout()
        right.setSpacing(6)

        gallery_group = QGroupBox("Generated Images — click to select")
        gallery_layout = QVBoxLayout(gallery_group)
        gallery_layout.setContentsMargins(6, 6, 6, 6)
        self._gallery = ThumbnailGrid()
        self._gallery.itemSelectionChanged.connect(self._update_action_buttons)
        gallery_layout.addWidget(self._gallery)
        right.addWidget(gallery_group, stretch=1)

        # Action buttons below gallery
        action_row = QHBoxLayout()
        self._send_btn = QPushButton("▶  Send to Chain")
        self._send_btn.setMinimumHeight(38)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_send_to_chain)

        self._del_btn = QPushButton("🗑  Delete")
        self._del_btn.setObjectName("cancel_btn")
        self._del_btn.setMinimumHeight(38)
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._on_delete_selected)

        self._clear_btn = QPushButton("✕  Clear Gallery")
        self._clear_btn.setMinimumHeight(38)
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self._on_clear_gallery)

        action_row.addWidget(self._send_btn)
        action_row.addSpacing(8)
        action_row.addWidget(self._del_btn)
        action_row.addStretch()
        action_row.addWidget(self._clear_btn)
        right.addLayout(action_row)

        return right

    # ------------------------------------------------------------------ #
    # Public refresh methods (called by MainWindow after settings change)
    # ------------------------------------------------------------------ #

    def refresh_workflows(self):
        self._wf_combo.blockSignals(True)
        self._wf_combo.clear()
        wf_dir = Path(self._config.get("workflow_dir", ""))
        if wf_dir.exists():
            for j in sorted(wf_dir.glob("IMG_*.json")):
                self._wf_combo.addItem(j.name, str(j))
        last = self._config.get("image_gen_workflow", "")
        if last:
            idx = self._wf_combo.findText(last)
            if idx >= 0:
                self._wf_combo.setCurrentIndex(idx)
        self._wf_combo.blockSignals(False)

    def refresh_mode(self):
        mode = self._config.get("mode", "local")
        if mode == "runpod":
            self._mode_lbl.setText("☁ RunPod")
            self._mode_lbl.setStyleSheet(f"color:{COLORS['accent']}; font-size:9pt; font-weight:bold;")
        else:
            self._mode_lbl.setText("🖥 Local")
            self._mode_lbl.setStyleSheet(f"color:{COLORS['success']}; font-size:9pt; font-weight:bold;")

    # ------------------------------------------------------------------ #
    # Worker launch
    # ------------------------------------------------------------------ #

    def _on_generate(self):
        self._pending_oneshot = False
        self._start_worker()

    def _on_generate_oneshot(self):
        self._pending_oneshot = True
        self._start_worker()

    def _start_worker(self):
        if self._worker and self._worker.isRunning():
            return

        wf_path = Path(self._wf_combo.currentData() or "")
        if not wf_path.exists():
            QMessageBox.critical(self, "Error", "Please select a valid workflow JSON.")
            return

        positive = self._pos_edit.toPlainText().strip()
        negative = self._neg_edit.toPlainText().strip()
        seed = self._seed_spin.value()

        # Persist prompts for next session
        self._config.set("image_gen_positive", positive)
        self._config.set("image_gen_negative", negative)
        self._config.save()

        self._log_list.clear()
        self._set_busy(True)

        refs = [s.path for s in (self._ref_slot1, self._ref_slot2) if s.path]
        self._worker = ImageGenWorker(
            self._config.get_all(), wf_path, positive, negative, seed, refs
        )
        self._worker.log.connect(self._on_log)
        self._worker.image_ready.connect(self._on_image_ready)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
        self._pending_oneshot = False
        self._cancel_gen_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Worker signal handlers
    # ------------------------------------------------------------------ #

    def _on_log(self, msg: str):
        self._log_list.addItem(msg)
        self._log_list.scrollToBottom()

    def _on_image_ready(self, path: str):
        self._generated.append(path)
        img = QImage(path)
        if not img.isNull():
            img = img.scaled(
                THUMB_SIZE, THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._gallery.add_item(img, path, Path(path).name)
            self._gallery.select_key(path)

        if self._pending_oneshot:
            self._pending_oneshot = False
            self.start_one_shot.emit(path)

    def _on_error(self, msg: str):
        self._pending_oneshot = False
        QMessageBox.critical(self, "Generation Error", msg)

    def _on_worker_finished(self):
        self._set_busy(False)
        self._update_action_buttons()

    # ------------------------------------------------------------------ #
    # Gallery actions
    # ------------------------------------------------------------------ #

    def _on_send_to_chain(self):
        key = self._gallery.selected_key()
        if key:
            self.send_to_chain.emit(key)

    def _on_delete_selected(self):
        key = self._gallery.selected_key()
        if not key:
            return
        path = Path(key)
        reply = QMessageBox.question(
            self, "Delete Image",
            f"Permanently delete:\n{path.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        items = self._gallery.selectedItems()
        if items:
            self._gallery.takeItem(self._gallery.row(items[0]))
        if key in self._generated:
            self._generated.remove(key)
        self._update_action_buttons()

    def _on_clear_gallery(self):
        self._gallery.clear_grid()
        self._generated.clear()
        self._update_action_buttons()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _current_workflow_path(self) -> Path | None:
        wf_path = Path(self._wf_combo.currentData() or "")
        return wf_path if wf_path.name else None

    def _on_save_history(self):
        wf_path = self._current_workflow_path()
        if wf_path is None:
            self._hist_status_lbl.setText("Select a workflow first.")
            return
        positive = self._pos_edit.toPlainText()
        negative = self._neg_edit.toPlainText()
        append_history(wf_path, positive, negative)
        self._hist_status_lbl.setText("Saved.")

    def _on_view_history(self):
        wf_path = self._current_workflow_path()
        if wf_path is None:
            self._hist_status_lbl.setText("Select a workflow first.")
            return
        dlg = PromptHistoryDialog(wf_path, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            entry = dlg.selected_entry()
            if entry:
                self._pos_edit.setPlainText(entry.get("positive", ""))
                self._neg_edit.setPlainText(entry.get("negative", ""))
                self._hist_status_lbl.setText("Loaded from history.")

    def _on_workflow_changed(self, _idx: int):
        name = self._wf_combo.currentText()
        if name:
            self._config.set("image_gen_workflow", name)
            self._config.save()

    def _set_busy(self, busy: bool):
        self._gen_btn.setEnabled(not busy)
        self._oneshot_btn.setEnabled(not busy)
        self._cancel_gen_btn.setEnabled(busy)

    def _update_action_buttons(self):
        has_sel = self._gallery.selected_key() is not None
        self._send_btn.setEnabled(has_sel)
        self._del_btn.setEnabled(has_sel)
        self._clear_btn.setEnabled(self._gallery.count() > 0)
