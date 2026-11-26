"""
ui/main_window.py — Main application window (PySide6).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QTextEdit, QFileDialog, QLineEdit,
    QGroupBox, QRadioButton, QButtonGroup, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon

from core.worker import FlipWorker

_MODEL_PATH = str(Path(__file__).parent.parent / "models" / "yolov8n.pt")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Picture Flipper v1.3.0 — Auto Orientation Fixer")
        self.setMinimumSize(700, 560)
        icon_path = Path(__file__).parent.parent / "app_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self._worker: FlipWorker | None = None
        self._reference_face: str | None = None
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(500)
        self._loading_timer.timeout.connect(self._tick_loading)
        self._loading_dots = 0
        self._loading_base = ""
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Folder picker row ---
        layout.addWidget(QLabel("Source Folder:"))
        folder_row = QHBoxLayout()
        self.source_entry = QLineEdit()
        self.source_entry.setPlaceholderText("Paste or type a folder path here…")
        self.source_entry.textChanged.connect(self._on_folder_text_changed)
        self.btn_pick_folder = QPushButton("Browse")
        folder_row.addWidget(self.source_entry, stretch=1)
        folder_row.addWidget(self.btn_pick_folder)
        layout.addLayout(folder_row)

        # --- Reference face group ---
        face_group = QGroupBox("Reference Face (optional — leave blank to detect any person)")
        face_vlayout = QVBoxLayout(face_group)
        face_vlayout.setSpacing(6)

        # Row 1: path entry + browse + paste image + clear
        face_row = QHBoxLayout()
        self.face_entry = QLineEdit()
        self.face_entry.setPlaceholderText("Paste a file path or use Browse…")
        self.face_entry.textChanged.connect(self._on_face_path_changed)
        self.btn_pick_face = QPushButton("Browse")
        self.btn_paste_face = QPushButton("Paste Image")
        self.btn_clear_face = QPushButton("Clear")
        self.btn_clear_face.setEnabled(False)
        face_row.addWidget(self.face_entry, stretch=1)
        face_row.addWidget(self.btn_pick_face)
        face_row.addWidget(self.btn_paste_face)
        face_row.addWidget(self.btn_clear_face)
        face_vlayout.addLayout(face_row)

        # Row 2: thumbnail + name label
        face_info_row = QHBoxLayout()
        self.lbl_face_thumb = QLabel()
        self.lbl_face_thumb.setFixedSize(48, 48)
        self.lbl_face_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_face_thumb.setStyleSheet("border: 1px solid #888; background: #222;")
        self.lbl_face_name = QLabel("None — will detect any person")
        self.lbl_face_name.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        face_info_row.addWidget(self.lbl_face_thumb)
        face_info_row.addWidget(self.lbl_face_name, stretch=1)
        face_vlayout.addLayout(face_info_row)

        layout.addWidget(face_group)

        # --- Target side group ---
        side_group = QGroupBox("Target Side — person should end up on:")
        side_layout = QHBoxLayout(side_group)
        self.radio_right = QRadioButton("Right  →")
        self.radio_left  = QRadioButton("←  Left")
        self.radio_right.setChecked(True)
        self._side_group = QButtonGroup()
        self._side_group.addButton(self.radio_right)
        self._side_group.addButton(self.radio_left)
        side_layout.addWidget(self.radio_right)
        side_layout.addWidget(self.radio_left)
        side_layout.addStretch()
        layout.addWidget(side_group)

        # --- Action buttons row ---
        btn_row = QHBoxLayout()
        self.btn_process = QPushButton("Scan & Process")
        self.btn_process.setEnabled(False)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_process)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

        # --- Progress bar + status label ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready — select a folder to begin.")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.lbl_status)

        # --- Log output ---
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Processing log will appear here…")
        layout.addWidget(self.log_output, stretch=1)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.btn_pick_folder.clicked.connect(self._on_pick_folder)
        self.btn_process.clicked.connect(self._on_process)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_pick_face.clicked.connect(self._on_pick_face)
        self.btn_paste_face.clicked.connect(self._on_paste_face)
        self.btn_clear_face.clicked.connect(self._on_clear_face)

    # ------------------------------------------------------------------
    # Slots — UI actions
    # ------------------------------------------------------------------

    def _on_folder_text_changed(self, text: str) -> None:
        has_folder = bool(text.strip())
        self.btn_process.setEnabled(has_folder)
        if has_folder:
            self.lbl_status.setText("Ready — press Scan & Process to start.")
            self.append_log(f"Source folder set: {text.strip()}")

    def _on_pick_folder(self) -> None:
        initial = self.source_entry.text().strip() or ""
        folder = QFileDialog.getExistingDirectory(self, "Select image folder", initial)
        if folder:
            self.source_entry.setText(folder)

    def _on_face_path_changed(self, text: str) -> None:
        path = text.strip().strip('"')
        if path and Path(path).is_file():
            self._load_face(path)

    def _on_pick_face(self) -> None:
        initial = self.face_entry.text().strip() or ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select reference face image",
            initial,
            "Images (*.jpg *.jpeg *.png *.webp)",
        )
        if path:
            self.face_entry.setText(path)

    def _on_paste_face(self) -> None:
        clipboard = QApplication.clipboard()
        # Try image data first (e.g. screenshot or copied image)
        img = clipboard.image()
        if not img.isNull():
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            img.save(tmp.name)
            self.face_entry.setText(tmp.name)
            return
        # Fall back to text (file path on clipboard)
        text = clipboard.text().strip().strip('"')
        if text:
            self.face_entry.setText(text)

    def _load_face(self, path: str) -> None:
        self._reference_face = path
        self.lbl_face_name.setText(Path(path).name)
        self.btn_clear_face.setEnabled(True)
        self.append_log(f"Reference face set: {path}")
        pix = QPixmap(path).scaled(
            48, 48,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.lbl_face_thumb.setPixmap(pix)

    def _on_clear_face(self) -> None:
        self._reference_face = None
        self.face_entry.clear()
        self.lbl_face_name.setText("None — will detect any person")
        self.lbl_face_thumb.clear()
        self.btn_clear_face.setEnabled(False)
        self.append_log("Reference face cleared — will detect any person.")

    def _on_process(self) -> None:
        folder = self.source_entry.text().strip()
        if not folder:
            return

        self.log_output.clear()
        self.progress_bar.setRange(0, 0)   # indeterminate "busy" animation
        self._start_loading("Loading model")
        self._set_running(True)

        target_side = "right" if self.radio_right.isChecked() else "left"
        self.append_log(f"Starting — source: {folder}")
        self.append_log(f"Output: {str(Path(folder) / 'Flipped')}")
        self.append_log(f"Target side: {target_side}")

        self._worker = FlipWorker(
            folder=folder,
            output_dir=str(Path(folder) / "Flipped"),
            model_path=_MODEL_PATH,
            reference_face=self._reference_face,
            target_side=target_side,
        )
        self._worker.log_message.connect(self.append_log)
        self._worker.status_message.connect(self._on_status_message)
        self._worker.progress.connect(self.set_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self.btn_stop.setEnabled(False)

    # ------------------------------------------------------------------
    # Slots — Worker signals
    # ------------------------------------------------------------------

    def _on_status_message(self, msg: str) -> None:
        self._stop_loading()
        self.lbl_status.setText(msg)

    def _on_finished(self, flipped: int, skipped: int) -> None:
        self._stop_loading()
        self.progress_bar.setRange(0, 100)
        self.set_progress(100)
        self._set_running(False)
        self.lbl_status.setText(f"Done — {flipped} flipped, {skipped} unchanged/skipped.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_running(self, running: bool) -> None:
        has_folder = bool(self.source_entry.text().strip())
        self.btn_process.setEnabled(not running and has_folder)
        self.btn_pick_folder.setEnabled(not running)
        self.btn_pick_face.setEnabled(not running)
        self.btn_paste_face.setEnabled(not running)
        self.btn_clear_face.setEnabled(not running and self._reference_face is not None)
        self.btn_stop.setEnabled(running)

    def _start_loading(self, base_text: str) -> None:
        self._loading_base = base_text
        self._loading_dots = 0
        self.lbl_status.setText(base_text + "…")
        self._loading_timer.start()

    def _stop_loading(self) -> None:
        self._loading_timer.stop()

    def _tick_loading(self) -> None:
        self._loading_dots = (self._loading_dots + 1) % 4
        self.lbl_status.setText(self._loading_base + "." * self._loading_dots)

    def append_log(self, message: str) -> None:
        self.log_output.append(message)

    def set_progress(self, value: int) -> None:
        # Switch from indeterminate to determinate on first real progress tick
        if self.progress_bar.maximum() == 0:
            self._stop_loading()
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)
