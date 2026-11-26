"""Multi-Source tab — run the same copy/move template across N source folders in parallel."""

import os
import logging
import threading
import queue
import time
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QProgressBar, QListWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QTimer

from config import ConfigManager
from copy_plan import PlanCancelled
from file_operations import FileCopier, format_file_size, summarize_results
from folder_organization import FolderStructure, FolderOrganizer
from ui.styles import COLORS
from ui.verbs import mode_verbs


_SHOW_PREFIXES = (
    "Error", "Copied (large):", "Moved (large):", "Path too long", "Found ", "Scanning",
    "Reading", "Gathering", "Checking", "Starting", "Sorting",
    "Duplicate found:", "Operation cancelled", "Start:",
    "Retry ", "CHECKSUM", "Warning: source not deleted",
    "Comparing", "Plan:", "Nothing to", "Note:",
)

# Copy-order dropdown labels → internal sort_order value passed to the scanner.
# Defined here (not in main_window) so both tabs share one source of truth
# without a circular import — main_window imports these from this module.
SORT_ORDER_LABELS = [
    "Largest first",
    "Smallest first",
    "Oldest first (modified date)",
    "Directory order (as found)",
]
SORT_ORDER_VALUES = {
    "Largest first": "largest",
    "Smallest first": "smallest",
    "Oldest first (modified date)": "oldest",
    "Directory order (as found)": "directory",
}


class MultiSourceTab(QWidget):
    def __init__(self, config_manager: ConfigManager, logger, log_path=None):
        super().__init__()
        self._config = config_manager
        self._logger = logger
        self._log_path = log_path
        self._cancel_requested = False
        self._is_running = False
        self._progress_queue: queue.Queue = queue.Queue()
        self._completed_copied = 0
        self._completed_skipped = 0
        self._completed_errors = 0
        self._completed_sources = 0
        self._sources_started = 0
        self._live_counts: dict = {}  # src_idx -> (copied, skipped, errors)
        self._watchdog_fired = False
        self.mode = 'copy'

        self._build_ui()
        self._load_config()

        self._poll_timer = QTimer()
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll_queue)

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        # ── Source List ──────────────────────────────────────────────────────
        src_hdr = QHBoxLayout()
        src_lbl = QLabel("Source Folders")
        src_lbl.setObjectName("section_label")
        src_hdr.addWidget(src_lbl)
        src_hdr.addStretch()
        btn_add = QPushButton("+ Add Folder")
        btn_add.setObjectName("preview_btn")
        btn_add.clicked.connect(self._add_source)
        btn_remove = QPushButton("Remove")
        btn_remove.setObjectName("preview_btn")
        btn_remove.clicked.connect(self._remove_source)
        btn_clear = QPushButton("Clear All")
        btn_clear.setObjectName("preview_btn")
        btn_clear.clicked.connect(self._clear_sources)
        src_hdr.addWidget(btn_add)
        src_hdr.addWidget(btn_remove)
        src_hdr.addWidget(btn_clear)
        layout.addLayout(src_hdr)

        self.source_list = QListWidget()
        self.source_list.setMinimumHeight(68)
        self.source_list.setMaximumHeight(90)
        layout.addWidget(self.source_list)

        hint_src = QLabel("Add each drive or folder you want to scan. Sources are processed one at a time — each uses its own dedicated workers.")
        hint_src.setObjectName("dim_label")
        layout.addWidget(hint_src)

        # ── Destination ──────────────────────────────────────────────────────
        layout.addWidget(QLabel("Destination Folder:"))
        dst_row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        dst_browse = QPushButton("Browse...")
        dst_browse.setMinimumWidth(100)
        dst_browse.clicked.connect(self._browse_dest)
        dst_row.addWidget(self.dest_edit)
        dst_row.addWidget(dst_browse)
        layout.addLayout(dst_row)

        # ── File Mask ────────────────────────────────────────────────────────
        self._presets = {
            "-- Select Preset --": "",
            "All Files": "*.*",
            "Archives":  "*.zip, *.rar, *.7z, *.tar, *.gz, *.bz2, *.xz, *.iso, *.cab",
            "Audio":     "*.mp3, *.wav, *.flac, *.aac, *.ogg, *.wma, *.m4a, *.opus, *.aiff, *.alac",
            "Code":      "*.py, *.js, *.ts, *.html, *.css, *.java, *.cpp, *.c, *.h, *.cs, *.php, *.rb, *.go, *.rs, *.swift",
            "Data":      "*.json, *.xml, *.csv, *.yaml, *.yml, *.sql, *.db, *.sqlite, *.mdb",
            "Documents": "*.pdf, *.doc, *.docx, *.xls, *.xlsx, *.ppt, *.pptx, *.txt, *.rtf, *.odt, *.ods, *.odp",
            "Images":    "*.jpg, *.jpeg, *.png, *.gif, *.bmp, *.tiff, *.tif, *.webp, *.svg, *.ico, *.raw, *.heic, *.heif",
            "Videos":    "*.mp4, *.avi, *.mkv, *.mov, *.wmv, *.flv, *.webm, *.m4v, *.mpeg, *.mpg, *.3gp, *.ts",
        }

        mask_row = QHBoxLayout()
        mask_row.addWidget(QLabel("File Mask:"))
        mask_row.addSpacing(20)
        mask_row.addWidget(QLabel("Presets:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self._presets.keys()))
        self.preset_combo.setFixedWidth(160)
        self.preset_combo.currentTextChanged.connect(self._on_preset_selected)
        mask_row.addWidget(self.preset_combo)
        mask_row.addStretch()
        layout.addLayout(mask_row)

        self.ext_edit = QLineEdit()
        layout.addWidget(self.ext_edit)
        hint_mask = QLabel("Example: *.*  or  *.jpg, *.png  or  oct*.*  or  .pdf")
        hint_mask.setObjectName("dim_label")
        layout.addWidget(hint_mask)

        # ── Copy Options + File Filters (2-column grid) ──────────────────────
        self.options_section_label = QLabel("Copy Options")
        self.options_section_label.setObjectName("section_label")
        layout.addWidget(self.options_section_label)

        self.recursive_check    = QCheckBox("Search subfolders recursively")
        self.preserve_check     = QCheckBox("Preserve original folder structure")
        self.number_check       = QCheckBox("Number duplicate files  (file_001.jpg, file_002.jpg)")
        self.incremental_check  = QCheckBox("Incremental — skip files already at destination (size + date match)")
        self.verify_check       = QCheckBox("Verify copies with MD5 checksum  (slower)")
        self.size_check         = QCheckBox("Filter by file size")
        self.date_check         = QCheckBox("Filter by file age")
        self.preserve_check.stateChanged.connect(self._on_preserve_changed)
        self.size_check.stateChanged.connect(self._on_size_filter_changed)
        self.date_check.stateChanged.connect(self._on_date_filter_changed)

        opts_grid = QGridLayout()
        opts_grid.setHorizontalSpacing(30)
        opts_grid.setVerticalSpacing(4)
        opts_grid.addWidget(self.recursive_check,   0, 0)
        opts_grid.addWidget(self.incremental_check, 0, 1)
        opts_grid.addWidget(self.preserve_check,    1, 0)
        opts_grid.addWidget(self.verify_check,      1, 1)
        opts_grid.addWidget(self.number_check,      2, 0)
        opts_grid.addWidget(self.size_check,        2, 1)
        opts_grid.addWidget(self.date_check,        3, 1)
        opts_grid.setColumnStretch(0, 1)
        opts_grid.setColumnStretch(1, 1)
        layout.addLayout(opts_grid)

        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("Workers per source:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(self._config.get("multi_workers", 2))
        self.workers_spin.setFixedWidth(60)
        workers_row.addWidget(self.workers_spin)
        workers_hint = QLabel("(1 = sequential  |  2–4 USB/HDD  |  4–8 NVMe)")
        workers_hint.setObjectName("dim_label")
        workers_row.addWidget(workers_hint)
        workers_row.addStretch()
        layout.addLayout(workers_row)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Copy order:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(SORT_ORDER_LABELS)
        self.sort_combo.setCurrentText(self._config.get("sort_order_label", "Largest first"))
        self.sort_combo.setFixedWidth(220)
        sort_row.addWidget(self.sort_combo)
        sort_hint = QLabel("(Largest first balances parallel workers best)")
        sort_hint.setObjectName("dim_label")
        sort_row.addWidget(sort_hint)
        sort_row.addStretch()
        layout.addLayout(sort_row)

        # ── Size / Date filter sub-rows (hidden until checked) ───────────────
        self.size_widget = QWidget()
        size_row = QHBoxLayout(self.size_widget)
        size_row.setContentsMargins(20, 0, 0, 0)
        size_row.addWidget(QLabel("Min:"))
        self.min_size_edit = QLineEdit("0")
        self.min_size_edit.setFixedWidth(80)
        size_row.addWidget(self.min_size_edit)
        size_row.addWidget(QLabel("Max:"))
        self.max_size_edit = QLineEdit()
        self.max_size_edit.setFixedWidth(80)
        size_row.addWidget(self.max_size_edit)
        size_row.addWidget(QLabel("Unit:"))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["B", "KB", "MB", "GB"])
        self.unit_combo.setFixedWidth(60)
        size_row.addWidget(self.unit_combo)
        size_row.addStretch()
        layout.addWidget(self.size_widget)
        self.size_widget.setVisible(False)

        self.date_widget = QWidget()
        date_row = QHBoxLayout(self.date_widget)
        date_row.setContentsMargins(20, 0, 0, 0)
        date_row.addWidget(QLabel("Modified within last:"))
        self.days_edit = QLineEdit("30")
        self.days_edit.setFixedWidth(80)
        date_row.addWidget(self.days_edit)
        date_row.addWidget(QLabel("days"))
        date_row.addStretch()
        layout.addWidget(self.date_widget)
        self.date_widget.setVisible(False)

        # ── Folder Organization ──────────────────────────────────────────────
        self.folder_org_widget = QWidget()
        fo_layout = QVBoxLayout(self.folder_org_widget)
        fo_layout.setContentsMargins(0, 0, 0, 0)
        fo_lbl = QLabel("Folder Organization (when not preserving structure)")
        fo_lbl.setObjectName("section_label")
        fo_layout.addWidget(fo_lbl)
        fo_layout.addWidget(QLabel("Organize into:"))
        self.folder_combo = QComboBox()
        self.folder_combo.addItems(["flat", "year", "year_month", "year_month_day", "date", "month"])
        self.folder_combo.setFixedWidth(200)
        self.folder_combo.currentTextChanged.connect(self._update_folder_example)
        fo_layout.addWidget(self.folder_combo)
        self.folder_example_label = QLabel("")
        self.folder_example_label.setObjectName("dim_label")
        fo_layout.addWidget(self.folder_example_label)
        layout.addWidget(self.folder_org_widget)
        self._update_folder_example()
        self._on_preserve_changed()

        # ── Action Buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Copy All Sources")
        self.run_btn.clicked.connect(self._start_run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_run)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Live Transfers Panel ─────────────────────────────────────────────
        self.live_transfers_frame = QFrame()
        self.live_transfers_frame.setFrameShape(QFrame.Shape.StyledPanel)
        lt_outer = QVBoxLayout(self.live_transfers_frame)
        lt_outer.setContentsMargins(8, 6, 8, 6)
        lt_outer.setSpacing(4)
        lt_hdr = QLabel("Active Large-File Transfers:")
        lt_hdr.setObjectName("dim_label")
        lt_outer.addWidget(lt_hdr)
        self._transfers_layout = QVBoxLayout()
        self._transfers_layout.setSpacing(3)
        lt_outer.addLayout(self._transfers_layout)
        layout.addWidget(self.live_transfers_frame)
        self.live_transfers_frame.setVisible(False)
        self._transfer_rows: dict = {}  # transfer_id -> (QWidget, QProgressBar)

        # ── Progress ─────────────────────────────────────────────────────────
        self.source_progress_label = QLabel("Ready — add source folders and click Run All Sources")
        self.source_progress_label.setObjectName("dim_label")
        layout.addWidget(self.source_progress_label)

        self.source_progress = QProgressBar()
        self.source_progress.setRange(0, 100)
        layout.addWidget(self.source_progress)

        counters_row = QHBoxLayout()
        self.copied_title_label = QLabel("Total Copied:")
        counters_row.addWidget(self.copied_title_label)
        self.copied_label = QLabel("0")
        self.copied_label.setObjectName("section_label")
        counters_row.addWidget(self.copied_label)
        counters_row.addSpacing(20)
        counters_row.addWidget(QLabel("Skipped:"))
        self.skipped_label = QLabel("0")
        self.skipped_label.setObjectName("section_label")
        counters_row.addWidget(self.skipped_label)
        counters_row.addSpacing(20)
        counters_row.addWidget(QLabel("Errors:"))
        self.errors_label = QLabel("0")
        self.errors_label.setObjectName("section_label")
        counters_row.addWidget(self.errors_label)
        counters_row.addStretch()
        layout.addLayout(counters_row)

        # ── Status Log ───────────────────────────────────────────────────────
        status_hdr = QHBoxLayout()
        status_hdr.addWidget(QLabel("Status (per-source results & errors):"))
        status_hdr.addStretch()
        clear_lbl = QLabel("[Clear]")
        clear_lbl.setObjectName("clear_label")
        clear_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_lbl.mousePressEvent = lambda e: self.status_list.clear()
        status_hdr.addWidget(clear_lbl)
        layout.addLayout(status_hdr)

        self.status_list = QListWidget()
        self.status_list.setMinimumHeight(130)
        self.status_list.setMaximumHeight(200)
        layout.addWidget(self.status_list)

    # ── Config ───────────────────────────────────────────────────────────────

    def _load_config(self):
        for path in self._config.get("multi_source_list", []):
            self.source_list.addItem(path)
        self.dest_edit.setText(self._config.get("multi_dest_folder", ""))
        self.ext_edit.setText(self._config.get("multi_extension", ""))
        self.recursive_check.setChecked(self._config.get("multi_recursive", True))
        self.preserve_check.setChecked(self._config.get("multi_preserve_structure", True))
        self.number_check.setChecked(self._config.get("multi_number_duplicates", True))
        self.incremental_check.setChecked(self._config.get("multi_incremental", False))
        self.verify_check.setChecked(self._config.get("multi_verify_checksum", False))
        self.folder_combo.setCurrentText(self._config.get("multi_folder_structure", "flat"))
        self.size_check.setChecked(self._config.get("multi_enable_size_filter", False))
        self.date_check.setChecked(self._config.get("multi_enable_date_filter", False))
        self.min_size_edit.setText(str(self._config.get("multi_min_size", "0")))
        self.max_size_edit.setText(str(self._config.get("multi_max_size", "")))
        self.unit_combo.setCurrentText(self._config.get("multi_size_unit", "MB"))
        self.days_edit.setText(str(self._config.get("multi_days_old", "30")))
        self._on_preserve_changed()

    def set_mode(self, mode: str):
        self.mode = mode
        verb, past = mode_verbs(mode)
        self.copied_title_label.setText(f"Total {past}:")
        self.options_section_label.setText(f"{verb} Options")
        self.run_btn.setText(f"{verb} All Sources")

    def _save_config(self):
        sources = [self.source_list.item(i).text() for i in range(self.source_list.count())]
        self._config.set("multi_source_list", sources)
        self._config.set("multi_dest_folder", self.dest_edit.text().strip())
        self._config.set("multi_extension", self.ext_edit.text().strip())
        self._config.set("multi_recursive", self.recursive_check.isChecked())
        self._config.set("multi_preserve_structure", self.preserve_check.isChecked())
        self._config.set("multi_number_duplicates", self.number_check.isChecked())
        self._config.set("multi_incremental", self.incremental_check.isChecked())
        self._config.set("multi_verify_checksum", self.verify_check.isChecked())
        self._config.set("multi_folder_structure", self.folder_combo.currentText())
        self._config.set("multi_enable_size_filter", self.size_check.isChecked())
        self._config.set("multi_enable_date_filter", self.date_check.isChecked())
        self._config.set("multi_min_size", self.min_size_edit.text())
        self._config.set("multi_max_size", self.max_size_edit.text())
        self._config.set("multi_size_unit", self.unit_combo.currentText())
        self._config.set("multi_days_old", self.days_edit.text())
        self._config.set("multi_workers", self.workers_spin.value())
        self._config.set("sort_order_label", self.sort_combo.currentText())
        self._config.save()

    # ── Source List Management ───────────────────────────────────────────────

    def _add_source(self):
        last = self.source_list.item(self.source_list.count() - 1)
        start = last.text() if last and os.path.isdir(last.text()) else ""
        folder = QFileDialog.getExistingDirectory(self, "Add Source Folder", start)
        if not folder:
            return
        existing = [self.source_list.item(i).text() for i in range(self.source_list.count())]
        if folder in existing:
            QMessageBox.information(self, "Duplicate", "That folder is already in the list.")
            return
        self.source_list.addItem(folder)
        self._save_config()

    def _remove_source(self):
        row = self.source_list.currentRow()
        if row >= 0:
            self.source_list.takeItem(row)
            self._save_config()

    def _clear_sources(self):
        if self.source_list.count() == 0:
            return
        reply = QMessageBox.question(
            self, "Clear Sources", "Remove all source folders from the list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.source_list.clear()
            self._save_config()

    # ── Slot Handlers ────────────────────────────────────────────────────────

    def _browse_dest(self):
        existing = self.dest_edit.text().strip()
        start = existing if existing and os.path.isdir(existing) else ""
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder", start)
        if folder:
            self.dest_edit.setText(folder)

    def _on_preset_selected(self, text: str):
        value = self._presets.get(text, "")
        if value:
            self.ext_edit.setText(value)

    def _on_preserve_changed(self):
        self.folder_org_widget.setVisible(not self.preserve_check.isChecked())

    def _on_size_filter_changed(self):
        self.size_widget.setVisible(self.size_check.isChecked())

    def _on_date_filter_changed(self):
        self.date_widget.setVisible(self.date_check.isChecked())

    def _update_folder_example(self):
        try:
            structure = FolderStructure(self.folder_combo.currentText())
            example = FolderOrganizer.get_folder_structure_example(structure)
            self.folder_example_label.setText(f"Example: {example}")
        except Exception:
            self.folder_example_label.setText("")

    def _add_status(self, message: str):
        if self.status_list.count() >= 1000:
            self.status_list.takeItem(0)
        self.status_list.addItem(message)
        self.status_list.scrollToBottom()

    # ── Validation ───────────────────────────────────────────────────────────

    def _build_run_options(self) -> dict | None:
        sources = [self.source_list.item(i).text() for i in range(self.source_list.count())]
        dest = self.dest_edit.text().strip()
        extension = self.ext_edit.text().strip()

        if not sources:
            QMessageBox.critical(self, "Error", "Please add at least one source folder.")
            return None
        if not dest:
            QMessageBox.critical(self, "Error", "Please select a destination folder.")
            return None
        if not extension:
            QMessageBox.critical(self, "Error", "Please enter a file mask (e.g. *.jpg or *.*).")
            return None

        missing = [s for s in sources if not os.path.isdir(s)]
        if missing:
            QMessageBox.critical(self, "Error",
                "The following source folders do not exist:\n" + "\n".join(missing))
            return None

        if not os.path.isdir(dest):
            try:
                os.makedirs(dest)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot create destination folder:\n{e}")
                return None

        min_size_bytes = max_size_bytes = max_days_old = None

        if self.size_check.isChecked():
            try:
                unit_mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
                mult = unit_mult.get(self.unit_combo.currentText(), 1024**2)
                min_val = self.min_size_edit.text().strip()
                if min_val:
                    min_size_bytes = float(min_val) * mult
                max_val = self.max_size_edit.text().strip()
                if max_val:
                    max_size_bytes = float(max_val) * mult
            except ValueError:
                QMessageBox.critical(self, "Error", "Invalid size filter values.")
                return None

        if self.date_check.isChecked():
            try:
                days_val = self.days_edit.text().strip()
                if days_val:
                    max_days_old = int(days_val)
            except ValueError:
                QMessageBox.critical(self, "Error", "Invalid date filter value.")
                return None

        preserve = self.preserve_check.isChecked()
        number_duplicates = self.number_check.isChecked()

        # Warn when using a custom folder structure (not preserve) and duplicate renaming is off.
        # Files from different source folders with the same name land in the same destination
        # subfolder; with numbering off only the first one is copied and the others are skipped.
        if not preserve and not number_duplicates:
            msg = (
                "You are using a custom folder structure (not preserving the original paths).\n\n"
                "Different files from different source folders that share the same filename "
                "will want the same destination name. With numbering off, only the first one is "
                "copied and the others are skipped (nothing is overwritten).\n\n"
                "Would you like to automatically rename duplicates "
                "(e.g. photo_001.jpg, photo_002.jpg) so that every file is kept?"
            )
            reply = QMessageBox.question(
                self,
                "Potential Filename Conflicts",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                number_duplicates = True
                self.number_check.setChecked(True)

        return {
            'sources': sources,
            'dest_folder': dest,
            'extension': extension,
            'preserve_structure': preserve,
            'number_duplicates': number_duplicates,
            'recursive_search': self.recursive_check.isChecked(),
            'folder_structure': self.folder_combo.currentText(),
            'min_size_bytes': min_size_bytes,
            'max_size_bytes': max_size_bytes,
            'max_days_old': max_days_old,
            'verify_checksum': self.verify_check.isChecked(),
            'incremental': self.incremental_check.isChecked(),
            'operation_mode': self.mode,
            'workers_per_source': self.workers_spin.value(),
            'sort_order': SORT_ORDER_VALUES.get(self.sort_combo.currentText(), "largest"),
            'sort_order_label': self.sort_combo.currentText(),
        }

    # ── Run / Cancel ─────────────────────────────────────────────────────────

    def _start_run(self):
        options = self._build_run_options()
        if options is None:
            return

        self._save_config()
        self.status_list.clear()
        self._is_running = True
        self._cancel_requested = False
        self._watchdog_fired = False
        self._completed_copied = 0
        self._completed_skipped = 0
        self._completed_errors = 0
        self._completed_sources = 0
        self._sources_started = 0
        self._live_counts = {}
        self._clear_transfer_panel()
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.source_progress.setValue(0)
        self.copied_label.setText("0")
        self.skipped_label.setText("0")
        self.errors_label.setText("0")

        n = len(options['sources'])
        wps = options['workers_per_source']
        self.source_progress_label.setText(
            f"Starting {n} source{'s' if n != 1 else ''}  ({wps} worker{'s' if wps != 1 else ''} each, one source at a time)…"
        )

        threading.Thread(target=self._worker, args=(options,), daemon=True).start()
        self._poll_timer.start()

    def _cancel_run(self):
        if self._is_running:
            self._cancel_requested = True
            self.cancel_btn.setEnabled(False)
            self.source_progress_label.setText("Cancelling — waiting for in-progress files to finish…")
            self._add_status("Cancellation requested — stopping after current files")

    # ── Worker Thread ────────────────────────────────────────────────────────

    def _log_run_settings(self, options: dict):
        """Write the full set of settings used for this run to the top of the log file."""
        def _sz(b):
            return "—" if b is None else f"{int(b):,} bytes"
        days = options.get('max_days_old')
        sources = options.get('sources', [])
        lines = [
            "================ RUN SETTINGS — Multi-Source ================",
            f"  Operation mode:      {str(options.get('operation_mode', 'copy')).upper()}",
            f"  Sources ({len(sources)}):",
        ]
        lines += [f"      [{i}] {s}" for i, s in enumerate(sources, 1)]
        lines += [
            f"  Destination:         {options['dest_folder']}",
            f"  File mask:           {options['extension']}",
            f"  Recursive search:    {options['recursive_search']}",
            f"  Preserve structure:  {options['preserve_structure']}",
            f"  Folder structure:    {options['folder_structure']}",
            f"  Number duplicates:   {options['number_duplicates']}",
            f"  Incremental:         {options['incremental']}",
            f"  Verify checksum:     {options['verify_checksum']}",
            f"  Workers per source:  {options['workers_per_source']}",
            f"  Copy order:          {options.get('sort_order_label', options.get('sort_order', 'largest'))}",
            f"  Min size filter:     {_sz(options.get('min_size_bytes'))}",
            f"  Max size filter:     {_sz(options.get('max_size_bytes'))}",
            f"  Max days old:        {'—' if days is None else days}",
            "=============================================================",
        ]
        self._logger.info("Run settings:\n" + "\n".join(lines))

    def _worker(self, options: dict):
        sources = options['sources']
        total_sources = len(sources)
        workers_per_src = options.get('workers_per_source', 1)
        start_time = time.time()
        self._log_run_settings(options)

        try:
            folder_structure = FolderStructure(options['folder_structure'])
        except ValueError:
            folder_structure = FolderStructure.FLAT

        grand_copied = grand_skipped = grand_errors = 0
        grand_bytes = 0

        # ── Watchdog + copier registry ────────────────────────────────────────
        _copier_lock = threading.Lock()
        _active_copiers: list = []
        _watchdog_stop = threading.Event()

        WATCHDOG_STALL = 45   # seconds of no I/O before auto-cancel
        WATCHDOG_TICK  = 10   # check interval

        def _watchdog_fn():
            while not _watchdog_stop.wait(timeout=WATCHDOG_TICK):
                if self._cancel_requested:
                    break
                with _copier_lock:
                    if not _active_copiers:
                        continue
                    most_recent = max(c.last_activity_time for c in _active_copiers)
                if time.time() - most_recent > WATCHDOG_STALL:
                    self._watchdog_fired = True
                    self._cancel_requested = True
                    self._queue_msg('status',
                        f"⚠ WATCHDOG: No disk I/O for {WATCHDOG_STALL}s — "
                        "auto-cancelled (drive may be unresponsive)")
                    break

        threading.Thread(target=_watchdog_fn, daemon=True).start()
        # ─────────────────────────────────────────────────────────────────────

        def _run_source(src_idx: int, source: str):
            if self._cancel_requested:
                return 0, 0, 0, 0

            self._queue_msg('source_start', {
                'index': src_idx, 'total': total_sources, 'path': source,
            })

            try:
                def _status_cb(msg):
                    # Full event stream (incl. per-file skip reasons) → .log file.
                    self._logger.info(f"[{src_idx}/{total_sources}] {msg}")
                    if any(msg.startswith(p) for p in _SHOW_PREFIXES):
                        self._queue_msg('status', f"[{src_idx}/{total_sources}] {msg}")

                def _fatal_cb(msg, _idx=src_idx, _total=total_sources):
                    self._cancel_requested = True
                    self._queue_msg('fatal_error', {
                        'source_idx': _idx, 'total': _total, 'message': msg,
                    })

                copier = FileCopier(
                    status_callback=_status_cb,
                    folder_structure=folder_structure,
                    number_duplicates=options['number_duplicates'],
                    progress_callback=None,
                    cancel_check=lambda: self._cancel_requested,
                    # Counters already include the files the plan skipped.
                    counters_callback=lambda c, s, e: self._queue_msg(
                        'source_counters', {'source_idx': src_idx, 'copied': c, 'skipped': s, 'errors': e}
                    ),
                    verify_checksum=options.get('verify_checksum', False),
                    incremental=options.get('incremental', False),
                    move_mode=options.get('operation_mode') == 'move',
                    workers=workers_per_src,
                    sort_order=options.get('sort_order', 'largest'),
                    transfer_callback=lambda tid, fname, pct: self._queue_msg(
                        'transfer_update', {'transfer_id': tid, 'filename': fname, 'pct': pct}
                    ),
                    fatal_error_callback=_fatal_cb,
                    plan_progress_callback=lambda stage, done, total: self._queue_msg('plan_progress', {
                        'index': src_idx, 'total_sources': total_sources,
                        'stage': stage, 'done': done, 'total': total,
                    }),
                )

                # Decide what happens to every file BEFORE any copying starts: the same planner
                # the single-source Preview uses. Each destination path then has exactly one
                # writer, so parallel workers can no longer overwrite or falsely skip each other.
                # (Planned before the copier joins the watchdog's list: a long comparison
                # is not "no disk I/O".)
                plan = copier.build_plan(
                    source, options['dest_folder'], options['extension'],
                    options['preserve_structure'], options['recursive_search'],
                    min_size_bytes=options.get('min_size_bytes'),
                    max_size_bytes=options.get('max_size_bytes'),
                    max_days_old=options.get('max_days_old'),
                )

                with _copier_lock:
                    _active_copiers.append(copier)
                try:
                    results = copier.copy_files(
                        source, options['dest_folder'], options['extension'],
                        options['preserve_structure'], options['recursive_search'],
                        plan=plan,
                    )
                finally:
                    with _copier_lock:
                        _active_copiers.remove(copier)

                summary = summarize_results(results, copier.planned_skips)
                return summary.copied, summary.skipped, summary.errors, summary.bytes_copied

            except PlanCancelled:
                return 0, 0, 0, 0          # Cancel pressed while comparing — the loop below stops

            except Exception as e:
                self._logger.error(f"Multi-source error on {source}: {e}")
                self._queue_msg('status', f"[{src_idx}/{total_sources}] ERROR: {e}")
                return 0, 0, 1, 0

        # Sources processed one at a time — no simultaneous USB/disk streams
        for src_idx, source in enumerate(sources, 1):
            if self._cancel_requested:
                break
            try:
                copied, skipped, errors, copied_bytes = _run_source(src_idx, source)
            except Exception as e:
                copied, skipped, errors, copied_bytes = 0, 0, 1, 0
                self._queue_msg('status', f"[{src_idx}/{total_sources}] FATAL: {e}")

            grand_copied  += copied
            grand_skipped += skipped
            grand_errors  += errors
            grand_bytes   += copied_bytes

            self._queue_msg('source_complete', {
                'index': src_idx, 'total': total_sources, 'path': source,
                'copied': copied, 'skipped': skipped, 'errors': errors,
                'copied_bytes': copied_bytes,
                'grand_copied': grand_copied,
                'grand_skipped': grand_skipped,
                'grand_errors': grand_errors,
                'grand_bytes': grand_bytes,
            })

        _watchdog_stop.set()

        end_time = time.time()

        if self._cancel_requested:
            self._queue_msg('all_cancelled', {
                'copied': grand_copied, 'skipped': grand_skipped, 'errors': grand_errors,
                'total_bytes': grand_bytes,
            })
        else:
            self._queue_msg('all_complete', {
                'copied': grand_copied, 'skipped': grand_skipped, 'errors': grand_errors,
                'total_bytes': grand_bytes,
                'start_time': start_time, 'end_time': end_time,
            })

    # ── Queue / Progress Polling ─────────────────────────────────────────────

    def _queue_msg(self, msg_type: str, data):
        self._progress_queue.put((msg_type, data))

    def _poll_queue(self):
        try:
            while True:
                try:
                    msg_type, data = self._progress_queue.get_nowait()

                    if msg_type == 'status':
                        self._add_status(data)

                    elif msg_type == 'plan_progress':
                        self.source_progress_label.setText(
                            f"Source {data['index']} / {data['total_sources']}:  "
                            f"{data['stage']}…  {data['done']:,} of {data['total']:,}"
                        )

                    elif msg_type == 'source_start':
                        self._sources_started += 1
                        path = data['path']
                        total = data['total']
                        self.source_progress_label.setText(
                            f"Processing source {data['index']} / {total}…"
                        )
                        self._add_status(f"── [{data['index']}/{total}] started  —  {path}")

                    elif msg_type == 'source_counters':
                        src_idx = data['source_idx']
                        self._live_counts[src_idx] = (data['copied'], data['skipped'], data['errors'])
                        total_c = self._completed_copied + sum(c for c, s, e in self._live_counts.values())
                        total_s = self._completed_skipped + sum(s for c, s, e in self._live_counts.values())
                        total_e = self._completed_errors + sum(e for c, s, e in self._live_counts.values())
                        self.copied_label.setText(str(total_c))
                        self.skipped_label.setText(str(total_s))
                        self.errors_label.setText(str(total_e))

                    elif msg_type == 'source_complete':
                        idx, total = data['index'], data['total']
                        path = data['path']
                        c, s, e = data['copied'], data['skipped'], data['errors']

                        # Promote this source's live counts into completed totals
                        self._live_counts.pop(idx, None)
                        self._completed_copied  = data['grand_copied']
                        self._completed_skipped = data['grand_skipped']
                        self._completed_errors  = data['grand_errors']
                        self.copied_label.setText(str(self._completed_copied))
                        self.skipped_label.setText(str(self._completed_skipped))
                        self.errors_label.setText(str(self._completed_errors))

                        self._completed_sources += 1
                        pct = int(self._completed_sources / total * 100)
                        self.source_progress.setValue(pct)
                        self.source_progress_label.setText(
                            f"Completed {self._completed_sources} / {total} sources"
                        )
                        verb = "moved" if self.mode == 'move' else "copied"
                        size_str = format_file_size(data.get('copied_bytes', 0))
                        self._add_status(
                            f"  ✓ [{idx}/{total}]  {verb}={c} ({size_str})  skipped={s}  errors={e}  —  {path}"
                        )

                    elif msg_type == 'fatal_error':
                        idx, total = data['source_idx'], data['total']
                        QMessageBox.critical(
                            self,
                            "Operation Stopped — Fatal Error",
                            f"A critical error occurred on source [{idx}/{total}] and the "
                            f"operation was automatically stopped:\n\n{data['message']}\n\n"
                            "Files copied up to this point are intact."
                        )

                    elif msg_type == 'transfer_update':
                        self._update_transfer_panel(
                            data['transfer_id'], data['filename'], data['pct']
                        )

                    elif msg_type == 'all_complete':
                        self._poll_timer.stop()
                        self._on_all_complete(data)
                        return

                    elif msg_type == 'all_cancelled':
                        self._poll_timer.stop()
                        self._on_all_cancelled(data)
                        return

                except queue.Empty:
                    break
        except Exception as exc:
            print(f"Multi-source queue poll error: {exc}")

    # ── Live Transfer Panel ──────────────────────────────────────────────────

    def _update_transfer_panel(self, transfer_id: str, filename: str, pct: int):
        """Add, update, or remove a live transfer row (called from Qt main thread via poll)."""
        if pct == -1:
            if transfer_id in self._transfer_rows:
                row_widget, _ = self._transfer_rows.pop(transfer_id)
                self._transfers_layout.removeWidget(row_widget)
                row_widget.deleteLater()
            if not self._transfer_rows:
                self.live_transfers_frame.setVisible(False)
        else:
            if transfer_id not in self._transfer_rows:
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(8)
                short_name = os.path.basename(filename)
                if len(short_name) > 42:
                    short_name = short_name[:39] + "…"
                name_lbl = QLabel(short_name)
                name_lbl.setFixedWidth(270)
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(pct)
                bar.setFixedHeight(16)
                row_layout.addWidget(name_lbl)
                row_layout.addWidget(bar, 1)
                self._transfers_layout.addWidget(row_widget)
                self._transfer_rows[transfer_id] = (row_widget, bar)
                self.live_transfers_frame.setVisible(True)
            else:
                _, bar = self._transfer_rows[transfer_id]
                bar.setValue(pct)

    def _clear_transfer_panel(self):
        for row_widget, _ in list(self._transfer_rows.values()):
            self._transfers_layout.removeWidget(row_widget)
            row_widget.deleteLater()
        self._transfer_rows.clear()
        self.live_transfers_frame.setVisible(False)

    # ── Completion Handlers ──────────────────────────────────────────────────

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        ms = int((seconds % 1) * 100)
        total_s = int(seconds)
        hh = total_s // 3600
        mm = (total_s % 3600) // 60
        ss = total_s % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:02d}"

    def _on_all_complete(self, data: dict):
        self._clear_transfer_panel()
        self._is_running = False
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.source_progress.setValue(100)

        copied  = data['copied']
        skipped = data['skipped']
        errors  = data['errors']
        total_bytes = data.get('total_bytes', 0)
        size_str = format_file_size(total_bytes)
        elapsed = data['end_time'] - data['start_time']
        elapsed_str = self._format_elapsed(elapsed)

        self.copied_label.setText(str(copied))
        self.skipped_label.setText(str(skipped))
        self.errors_label.setText(str(errors))
        verb = "Moved" if self.mode == 'move' else "Copied"
        self.source_progress_label.setText(f"All sources complete  —  Elapsed: {elapsed_str}")
        self._add_status(
            f"═══ All sources complete  —  Elapsed: {elapsed_str}  —  {verb}: {copied} ({size_str})  Skipped: {skipped}  Errors: {errors} ═══"
        )
        if self._log_path:
            self._add_status(f"Log file (per-file skip reasons): {self._log_path}")

        summary = f"Total {verb}: {copied} ({size_str})\nTotal Skipped: {skipped}\nTotal Errors: {errors}\nElapsed: {elapsed_str}"
        action = "move" if self.mode == 'move' else "copy"
        if errors == 0 and copied > 0:
            QMessageBox.information(self, "Complete", summary)
        elif copied > 0:
            QMessageBox.warning(self, "Completed with errors",
                f"{summary}\n\nCheck the status log for details.")
        else:
            QMessageBox.information(self, "Complete",
                f"No files were found to {action} across all sources.\n\nCheck file mask and source folders.")

    def _on_all_cancelled(self, data: dict):
        self._clear_transfer_panel()
        self._is_running = False
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        copied, skipped, errors = data['copied'], data['skipped'], data['errors']
        size_str = format_file_size(data.get('total_bytes', 0))
        self.copied_label.setText(str(copied))
        self.skipped_label.setText(str(skipped))
        self.errors_label.setText(str(errors))
        verb = "Moved" if self.mode == 'move' else "Copied"
        if self._watchdog_fired:
            self.source_progress_label.setText("Auto-cancelled — drive unresponsive")
            reason = "Auto-cancelled: drive appeared unresponsive (no disk I/O for 45 seconds).\nCheck the drive and try again."
            self._add_status(f"Auto-cancelled (watchdog)  —  {verb}: {copied} ({size_str})  Skipped: {skipped}  Errors: {errors}")
            QMessageBox.warning(self, "Auto-Cancelled (Watchdog)",
                f"{reason}\n\n{verb} so far: {copied} ({size_str})\nSkipped: {skipped}")
        else:
            self.source_progress_label.setText("Cancelled")
            self._add_status(f"Operation cancelled  —  {verb}: {copied} ({size_str})  Skipped: {skipped}  Errors: {errors}")
            QMessageBox.information(self, "Cancelled",
                f"Operation cancelled.\n\n{verb} so far: {copied} ({size_str})\nSkipped: {skipped}")
