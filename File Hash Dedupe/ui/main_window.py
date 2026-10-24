"""Main window UI for File Hash Dedupe"""

import os
import atexit
import threading
import queue
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QCheckBox, QSpinBox, QProgressBar, QListWidget, QComboBox,
    QRadioButton, QButtonGroup,
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from config import ConfigManager
from hasher import FileDeduplicator, ScanResult, ALGORITHMS, KEEP_RULES, write_csv_report
from ui.styles import STYLESHEET, COLORS
from ui.preview_dialog import PreviewDialog
from filetypes import PRESETS

# Order of the File Types tick boxes ("All Files" = nothing ticked)
TYPE_PRESETS = ["Images", "Videos", "Audio", "Documents", "Data", "Archives", "Code"]


def _cleanup_all_children():
    try:
        import psutil
        current = psutil.Process(os.getpid())
        for child in current.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
    except Exception:
        pass

atexit.register(_cleanup_all_children)


class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager, version: str):
        super().__init__()
        self.config = config_manager
        self.version = version

        self._is_processing = False
        self._cancel_requested = False
        self._message_queue = queue.Queue()
        self._deduplicator: FileDeduplicator = None
        self._pending_source_folder = None
        self._pending_target_folder = None
        self._pending_permanent_delete = False
        self._pending_compare_mode = False

        self.setWindowTitle(f"File Hash Dedupe v{self.version}")
        # Width only: the minimum height comes from the layout, so the window can never be
        # shrunk below what the controls need (a hard-coded height let rows overlap at 125-150% scaling)
        self.setMinimumWidth(750)
        self.setStyleSheet(STYLESHEET)

        geom = self.config.window_geometry
        if geom:
            try:
                from PyQt6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromHex(geom.encode()))
            except Exception:
                self.resize(800, 650)
        else:
            self.resize(800, 650)

        # SQLite hash cache lives next to the config file (next to the EXE when frozen)
        self.db_path = Path(self.config.config_file).parent / "FileHashDedupe_hashes.db"

        self._build_ui()
        self._load_config()
        self._refresh_cache_label()

        self._poll_timer = QTimer()
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._process_messages)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        header = QLabel("File Hash Dedupe")
        header.setObjectName("header")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        subtitle = QLabel("Find and move duplicate files based on content hash — "
                          "hashes are cached, so a rescan only hashes new or changed files")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Mode
        mode_group = QGroupBox("Mode")
        mode_layout = QHBoxLayout(mode_group)
        self.single_radio = QRadioButton("Dedupe one folder")
        self.single_radio.setChecked(True)
        self.compare_radio = QRadioButton("Compare two folders (dedupe B against A)")
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.addButton(self.single_radio)
        self.mode_button_group.addButton(self.compare_radio)
        self.single_radio.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self.single_radio)
        mode_layout.addWidget(self.compare_radio)
        layout.addWidget(mode_group)

        # Source folder (Folder A)
        src_group = QGroupBox("Source Folder")
        self.src_group = src_group
        src_layout = QVBoxLayout(src_group)
        src_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.setMinimumWidth(100)
        browse_btn.clicked.connect(self._browse_source)
        src_row.addWidget(self.source_edit, stretch=1)
        src_row.addWidget(browse_btn)
        src_layout.addLayout(src_row)
        self.source_info_label = QLabel("Duplicates will be moved to a 'Dupes' subfolder in the source folder")
        self.source_info_label.setObjectName("subtitle")
        src_layout.addWidget(self.source_info_label)
        layout.addWidget(src_group)

        # Target folder (Folder B) — only shown in compare mode
        target_group = QGroupBox("Target Folder (B) — duplicates removed here")
        self.target_group = target_group
        target_layout = QVBoxLayout(target_group)
        target_row = QHBoxLayout()
        self.target_edit = QLineEdit()
        target_browse_btn = QPushButton("Browse...")
        target_browse_btn.setMinimumWidth(100)
        target_browse_btn.clicked.connect(self._browse_target)
        target_row.addWidget(self.target_edit, stretch=1)
        target_row.addWidget(target_browse_btn)
        target_layout.addLayout(target_row)
        layout.addWidget(target_group)
        target_group.setVisible(False)

        # File types: presets shared with Burn List Creator / FolderSync / File Copy Move Manager
        types_group = QGroupBox("File Types  (nothing ticked = all types)")
        types_group.setToolTip("Only the ticked types are hashed and deduped. Hover a box to see its extensions.")
        types_grid = QGridLayout(types_group)
        types_grid.setContentsMargins(14, 18, 14, 14)
        types_grid.setHorizontalSpacing(24)
        types_grid.setVerticalSpacing(12)
        self.type_checks = {}
        for i, name in enumerate(TYPE_PRESETS):
            check = QCheckBox(name)
            check.setToolTip(PRESETS[name])
            types_grid.addWidget(check, i // 4, i % 4)
            self.type_checks[name] = check
        # Extra masks fill the empty 4th slot of the second row
        self.extra_mask_edit = QLineEdit()
        self.extra_mask_edit.setPlaceholderText("also: *.psd, blend")
        self.extra_mask_edit.setToolTip("Extra masks, comma separated: *.psd, blend, IMG_*.jpg")
        types_grid.addWidget(self.extra_mask_edit, 1, 3)
        types_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(types_group)

        # Options
        opt_group = QGroupBox("Options")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setContentsMargins(14, 18, 14, 14)
        opt_layout.setSpacing(16)
        # Never let the stretchy Status box squeeze these rows together
        opt_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.recursive_check = QCheckBox("Search subfolders recursively")
        self.recursive_check.setChecked(True)
        opt_layout.addWidget(self.recursive_check)

        self.permanent_delete_check = QCheckBox("⚠  Permanently delete duplicates (no Dupes folder)")
        self.permanent_delete_check.setChecked(False)
        self.permanent_delete_check.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        self.permanent_delete_check.toggled.connect(self._on_permanent_delete_toggled)
        opt_layout.addWidget(self.permanent_delete_check)

        self.csv_report_check = QCheckBox("Write CSV report of duplicate groups")
        opt_layout.addWidget(self.csv_report_check)

        algo_row = QHBoxLayout()
        algo_row.addWidget(QLabel("Hash algorithm:"))
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItems(list(ALGORITHMS.keys()))
        algo_row.addWidget(self.algorithm_combo)
        algo_row.addSpacing(20)
        algo_row.addWidget(QLabel("Keep:"))
        self.keep_rule_combo = QComboBox()
        self.keep_rule_combo.addItems(KEEP_RULES)
        algo_row.addWidget(self.keep_rule_combo)
        algo_row.addStretch()
        opt_layout.addLayout(algo_row)

        cpu_count = os.cpu_count() or 4
        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("Hashing workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, cpu_count)
        self.workers_spin.setValue(max(2, min(16, cpu_count // 2)))
        self.workers_spin.setFixedWidth(70)
        workers_row.addWidget(self.workers_spin)
        cpu_lbl = QLabel(f"(1 – {cpu_count} logical CPUs on this machine)")
        cpu_lbl.setObjectName("subtitle")
        workers_row.addWidget(cpu_lbl)
        workers_row.addStretch()
        opt_layout.addLayout(workers_row)

        size_row = QHBoxLayout()
        self.max_size_check = QCheckBox("Skip files larger than")
        self.max_size_check.setChecked(True)
        self.max_size_check.setToolTip("Big files (models, .safetensors, disk images) are ignored: "
                                       "not hashed, never moved or deleted")
        size_row.addWidget(self.max_size_check)
        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(1, 10_000_000)
        self.max_size_spin.setValue(100)
        self.max_size_spin.setSuffix(" MB")
        self.max_size_spin.setFixedWidth(130)
        self.max_size_check.toggled.connect(self.max_size_spin.setEnabled)
        size_row.addWidget(self.max_size_spin)
        size_lbl = QLabel("(recycle bins and System Volume Information are always skipped)")
        size_lbl.setObjectName("subtitle")
        size_row.addWidget(size_lbl)
        size_row.addStretch()
        opt_layout.addLayout(size_row)

        cache_row = QHBoxLayout()
        cache_row.addWidget(QLabel("Hash cache:"))
        self.cache_label = QLabel()
        self.cache_label.setObjectName("subtitle")
        self.cache_label.setToolTip(str(self.db_path))
        self.cache_label.setMinimumWidth(1)          # long text may clip, never widen the window
        cache_row.addWidget(self.cache_label, stretch=1)
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setObjectName("small_btn")
        self.clear_cache_btn.setToolTip("Forget every cached hash; the next scan hashes everything again")
        self.clear_cache_btn.clicked.connect(self._clear_cache)
        cache_row.addWidget(self.clear_cache_btn)
        opt_layout.addLayout(cache_row)
        layout.addWidget(opt_group)

        # Buttons
        btn_row = QHBoxLayout()
        self.dedupe_btn = QPushButton("Find Duplicates")
        self.dedupe_btn.clicked.connect(self._start_dedupe)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_dedupe)
        btn_row.addWidget(self.dedupe_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Progress
        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("subtitle")
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # Status log
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        self.status_list = QListWidget()
        status_layout.addWidget(self.status_list)
        status_group.setMinimumHeight(90)
        layout.addWidget(status_group, stretch=1)

    def _refresh_cache_label(self):
        try:
            stats = FileDeduplicator(self.db_path).cache_stats()
            self.cache_label.setText(f"{stats['hashes']:,} hash(es) for {stats['files']:,} file(s) "
                                     f"— {self.db_path.name}")
        except Exception as e:
            self.cache_label.setText(f"unavailable ({e})")

    def _clear_cache(self):
        reply = QMessageBox.question(
            self, "Clear Hash Cache",
            "Forget every cached hash?\n\nNo files are touched; the next scan just hashes everything again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            FileDeduplicator(self.db_path).clear_cache()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not clear the cache:\n{e}")
        self._refresh_cache_label()

    def _finish_processing(self):
        """Back to idle: buttons re-enabled, cache count refreshed"""
        self._is_processing = False
        self.dedupe_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.clear_cache_btn.setEnabled(True)
        self._refresh_cache_label()

    def _on_mode_changed(self, single_checked: bool):
        compare_mode = not single_checked
        self.target_group.setVisible(compare_mode)
        self.keep_rule_combo.setEnabled(not compare_mode)
        if compare_mode:
            self.src_group.setTitle("Reference Folder (A) — never modified")
            self.source_info_label.setText("Files here are the reference set and will never be moved or deleted")
        else:
            self.src_group.setTitle("Source Folder")
            self._on_permanent_delete_toggled(self.permanent_delete_check.isChecked())

    def _on_permanent_delete_toggled(self, checked: bool):
        if self.compare_radio.isChecked():
            return
        if checked:
            self.source_info_label.setText("⚠  Duplicates will be permanently deleted — cannot be undone")
        else:
            self.source_info_label.setText("Duplicates will be moved to a 'Dupes' subfolder in the source folder")

    def _browse_source(self):
        existing = self.source_edit.text().strip()
        start = existing if existing and os.path.isdir(existing) else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder", start)
        if folder:
            self.source_edit.setText(folder)

    def _browse_target(self):
        existing = self.target_edit.text().strip()
        start = existing if existing and os.path.isdir(existing) else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder", start)
        if folder:
            self.target_edit.setText(folder)

    def _load_config(self):
        if self.config.source_folder:
            self.source_edit.setText(self.config.source_folder)
        self.recursive_check.setChecked(self.config.recursive)
        self.workers_spin.setValue(self.config.get('io_workers', self.workers_spin.value()))
        self.target_edit.setText(self.config.get('target_folder', ''))
        self.algorithm_combo.setCurrentText(self.config.get('algorithm', 'MD5'))
        self.keep_rule_combo.setCurrentText(self.config.get('keep_rule', KEEP_RULES[0]))
        self.csv_report_check.setChecked(self.config.get('csv_report', False))
        self.max_size_check.setChecked(self.config.get('max_size_enabled', True))
        self.max_size_spin.setValue(self.config.get('max_size_mb', 100))
        self.max_size_spin.setEnabled(self.max_size_check.isChecked())
        for name in self.config.get('file_types', []):
            if name in self.type_checks:
                self.type_checks[name].setChecked(True)
        self.extra_mask_edit.setText(self.config.get('extra_mask', ''))
        if self.config.get('compare_mode', False):
            self.compare_radio.setChecked(True)
            self._on_mode_changed(False)

    def _save_config(self):
        self.config.source_folder = self.source_edit.text()
        self.config.recursive = self.recursive_check.isChecked()
        self.config.window_geometry = self.saveGeometry().toHex().data().decode()
        self.config.set('io_workers', self.workers_spin.value())
        self.config.set('target_folder', self.target_edit.text())
        self.config.set('algorithm', self.algorithm_combo.currentText())
        self.config.set('keep_rule', self.keep_rule_combo.currentText())
        self.config.set('csv_report', self.csv_report_check.isChecked())
        self.config.set('max_size_enabled', self.max_size_check.isChecked())
        self.config.set('max_size_mb', self.max_size_spin.value())
        self.config.set('file_types', [n for n, c in self.type_checks.items() if c.isChecked()])
        self.config.set('extra_mask', self.extra_mask_edit.text().strip())
        self.config.set('compare_mode', self.compare_radio.isChecked())
        self.config.save()

    def _start_dedupe(self):
        source = self.source_edit.text().strip()
        if not source:
            QMessageBox.critical(self, "Validation Error", "Please select a source folder")
            return
        if not os.path.exists(source):
            QMessageBox.critical(self, "Validation Error", "Source folder does not exist")
            return

        compare_mode = self.compare_radio.isChecked()
        target = self.target_edit.text().strip()

        if compare_mode:
            if not target:
                QMessageBox.critical(self, "Validation Error", "Please select a target folder")
                return
            if not os.path.exists(target):
                QMessageBox.critical(self, "Validation Error", "Target folder does not exist")
                return
            if os.path.abspath(target) == os.path.abspath(source):
                QMessageBox.critical(self, "Validation Error", "Reference and target folders must be different")
                return

        permanent_delete = self.permanent_delete_check.isChecked()

        if permanent_delete:
            reply = QMessageBox.warning(
                self, "Permanent Delete",
                "Duplicates will be permanently deleted and cannot be recovered.\n\nAre you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._save_config()
        self._is_processing = True
        self._cancel_requested = False
        self.dedupe_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_list.clear()

        self._pending_source_folder = source
        self._pending_target_folder = target
        self._pending_permanent_delete = permanent_delete
        self._pending_compare_mode = compare_mode

        self.clear_cache_btn.setEnabled(False)
        self._deduplicator = FileDeduplicator(
            self.db_path,
            status_callback=lambda msg: self._message_queue.put(('status', msg)),
            progress_callback=lambda cur, total, fname: self._message_queue.put(
                ('progress', {'current': cur, 'total': total, 'filename': fname})
            ),
            cancel_check=lambda: self._cancel_requested,
            max_workers=self.workers_spin.value()
        )

        thread = threading.Thread(
            target=self._scan_worker,
            args=(source, target, self.recursive_check.isChecked(),
                  ALGORITHMS[self.algorithm_combo.currentText()],
                  self.keep_rule_combo.currentText(), compare_mode,
                  self.max_size_spin.value() * 1024 * 1024 if self.max_size_check.isChecked() else 0,
                  self._file_type_selection()),
            daemon=True
        )
        thread.start()
        self._poll_timer.start()

    def _file_type_selection(self) -> tuple:
        """Ticked presets plus the extra mask; empty = all file types"""
        selection = [n for n, c in self.type_checks.items() if c.isChecked()]
        mask = self.extra_mask_edit.text().strip()
        if mask:
            selection.append(mask)
        return tuple(selection)

    def _scan_worker(self, source: str, target: str, recursive: bool, algorithm: str, keep_rule: str,
                     compare_mode: bool, max_size: int, file_types: tuple):
        try:
            if compare_mode:
                scan_result = self._deduplicator.scan_compare(source, target, recursive=recursive,
                                                              algorithm=algorithm, max_size=max_size,
                                                              file_types=file_types)
            else:
                scan_result = self._deduplicator.scan(source, recursive=recursive, algorithm=algorithm,
                                                      keep_rule=keep_rule, max_size=max_size,
                                                      file_types=file_types)

            if self._cancel_requested:
                self._message_queue.put(('cancelled', None))
            else:
                self._message_queue.put(('scan_complete', scan_result))
        except ValueError as e:
            self._message_queue.put(('error', {'type': 'validation', 'message': str(e)}))
        except Exception as e:
            self._message_queue.put(('error', {'type': 'unexpected', 'message': str(e)}))

    def _execute_worker(self, scan_result: ScanResult, source: str, target: str,
                         permanent_delete: bool, compare_mode: bool, write_csv: bool):
        try:
            if compare_mode:
                results, total, unique, moved = self._deduplicator.execute_compare(
                    scan_result, target, permanent_delete=permanent_delete
                )
                report_folder = target
            else:
                results, total, unique, moved = self._deduplicator.execute(
                    scan_result, source, permanent_delete=permanent_delete
                )
                report_folder = source

            if write_csv and scan_result.groups:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path = os.path.join(report_folder, f"dedupe_report_{timestamp}.csv")
                try:
                    write_csv_report(csv_path, scan_result.groups, scan_result.primary_map, results)
                    self._message_queue.put(('status', f"CSV report written: {csv_path}"))
                except OSError as e:
                    self._message_queue.put(('status', f"Failed to write CSV report: {e}"))

            if self._cancel_requested:
                self._message_queue.put(('cancelled', None))
            else:
                self._message_queue.put(('complete', {
                    'total': total, 'unique': unique, 'moved': moved,
                    'permanent_delete': permanent_delete, 'compare_mode': compare_mode
                }))
        except Exception as e:
            self._message_queue.put(('error', {'type': 'unexpected', 'message': str(e)}))

    def _process_messages(self):
        try:
            for _ in range(50):  # max messages per tick — keeps UI responsive
                msg_type, data = self._message_queue.get_nowait()

                if msg_type == 'status':
                    self.status_list.addItem(data)
                    self.status_list.scrollToBottom()

                elif msg_type == 'progress':
                    self.progress_bar.setValue(data['current'])
                    self.progress_label.setText(f"{data['current']}%: {data['filename']}")

                elif msg_type == 'scan_complete':
                    self._poll_timer.stop()
                    self._on_scan_complete(data)
                    return

                elif msg_type == 'complete':
                    self._poll_timer.stop()
                    self._on_complete(data)
                    return

                elif msg_type == 'cancelled':
                    self._poll_timer.stop()
                    self._on_cancelled()
                    return

                elif msg_type == 'error':
                    self._poll_timer.stop()
                    self._on_error(data)
                    return

        except queue.Empty:
            pass

    def _on_scan_complete(self, scan_result: ScanResult):
        if not scan_result.groups:
            self._finish_processing()
            self.progress_label.setText("No duplicates found")
            noun = "matches" if self._pending_compare_mode else "duplicates"
            QMessageBox.information(self, "No Duplicates", f"No {noun} were found.")
            return

        self.cancel_btn.setEnabled(False)
        dialog = PreviewDialog(
            self._deduplicator, scan_result,
            compare_mode=self._pending_compare_mode,
            permanent_delete=self._pending_permanent_delete,
            parent=self
        )
        if dialog.exec():
            final_scan_result = dialog.get_scan_result()
            self.status_list.addItem("Review confirmed, applying changes...")
            self.status_list.scrollToBottom()
            self.cancel_btn.setEnabled(True)
            thread = threading.Thread(
                target=self._execute_worker,
                args=(final_scan_result, self._pending_source_folder, self._pending_target_folder,
                      self._pending_permanent_delete, self._pending_compare_mode,
                      self.csv_report_check.isChecked()),
                daemon=True
            )
            thread.start()
            self._poll_timer.start()
        else:
            self._finish_processing()
            self.progress_label.setText("Cancelled")
            self.status_list.addItem("Review cancelled, no files were changed")
            self.status_list.scrollToBottom()

    def _on_complete(self, data: dict):
        self._finish_processing()
        self.progress_bar.setValue(100)
        self.progress_label.setText("Complete!")
        action_word = "deleted" if data.get('permanent_delete') else "moved"
        if data.get('compare_mode'):
            QMessageBox.information(
                self, "Success",
                f"Compare complete!\n\n"
                f"Files scanned in target folder: {data['total']}\n"
                f"Matches {action_word}: {data['moved']}"
            )
        else:
            dest = "" if data.get('permanent_delete') else " to Dupes"
            QMessageBox.information(
                self, "Success",
                f"Deduplication complete!\n\n"
                f"Total files scanned: {data['total']}\n"
                f"Unique files: {data['unique']}\n"
                f"Duplicates {action_word}{dest}: {data['moved']}"
            )

    def _on_cancelled(self):
        self._finish_processing()
        self.progress_label.setText("Cancelled")
        self.status_list.addItem("Operation cancelled by user")
        self.status_list.scrollToBottom()

    def _on_error(self, data: dict):
        self._finish_processing()
        self.progress_label.setText("Error")
        msg = data['message']
        if data['type'] == 'validation':
            QMessageBox.critical(self, "Validation Error", msg)
        else:
            QMessageBox.critical(self, "Error", f"An unexpected error occurred:\n{msg}")

    def _cancel_dedupe(self):
        if self._is_processing:
            self._cancel_requested = True
            self.cancel_btn.setEnabled(False)
            self.progress_label.setText("Cancelling...")
            self.status_list.addItem("Cancellation requested...")
            self.status_list.scrollToBottom()

    def closeEvent(self, event):
        if self._is_processing:
            self._cancel_requested = True
        self._save_config()
        event.accept()
