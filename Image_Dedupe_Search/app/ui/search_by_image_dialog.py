"""Search by Image dialog - find similar images to a reference image"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QProgressBar,
    QApplication, QListWidget, QListWidgetItem, QAbstractItemView,
    QSplitter, QFrame, QScrollArea, QSizePolicy, QSlider
)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QMimeData
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QKeyEvent
from typing import Optional, List, Dict, Tuple
from pathlib import Path
import numpy as np
import os

from app.core.image_utils import ImageUtils, SUPPORTED_EXTENSIONS
from app.core.embeddings import EmbeddingEngine
from app.core.cache import EmbeddingCache
from app.workers.scan_worker import ScanWorker
from app.workers.embed_worker import EmbedWorker


class DropZone(QLabel):
    """A label that accepts drag-and-drop of image files"""

    file_dropped = Signal(str)  # Emits the file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 150)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #585b70;
                border-radius: 8px;
                background-color: #313244;
                color: #89b4fa;
                font-size: 12pt;
            }
            QLabel:hover {
                border-color: #89b4fa;
                background-color: #45475a;
            }
        """)
        self._reset_text()

    def _reset_text(self):
        self.setText("Drop an image here\nor click Browse")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and self._is_valid_image(urls[0].toLocalFile()):
                event.acceptProposedAction()
                self.setStyleSheet(self.styleSheet().replace("#585b70", "#89b4fa"))

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.styleSheet().replace("#89b4fa", "#585b70"))

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self.styleSheet().replace("#89b4fa", "#585b70"))
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if self._is_valid_image(file_path):
                self.file_dropped.emit(file_path)

    def _is_valid_image(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in SUPPORTED_EXTENSIONS

    def set_image(self, path: str):
        """Display the dropped image as thumbnail"""
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.size() - QSize(20, 20),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.setPixmap(scaled)
        else:
            self._reset_text()

    def clear_image(self):
        self.setPixmap(QPixmap())
        self._reset_text()


class SearchByImageDialog(QDialog):
    """Dialog for searching similar images to a reference image"""

    def __init__(self, config, cache: EmbeddingCache, parent=None, theme=None):
        super().__init__(parent)
        self.config = config
        self.cache = cache
        self.theme = theme

        # State
        self.search_image_path: Optional[str] = None
        # Load last search folder from config, fallback to last_scan_folder
        self.search_folder: Optional[str] = self.config.get(
            "last_search_folder",
            self.config.get("last_scan_folder", None)
        )
        self.embeddings: Dict[str, np.ndarray] = {}
        self.search_embedding: Optional[np.ndarray] = None
        self.results: List[Tuple[str, float]] = []

        # Workers
        self._scan_worker: Optional[ScanWorker] = None
        self._embed_worker: Optional[EmbedWorker] = None

        self.setWindowTitle("Search by Image")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)

        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Top section - reference image and folder selection
        top_layout = QHBoxLayout()

        # Left side - drop zone for reference image
        left_frame = QFrame()
        left_frame.setProperty("cssClass", "card")
        left_layout = QVBoxLayout(left_frame)

        ref_label = QLabel("Reference Image")
        ref_label.setProperty("cssClass", "section-title")
        ref_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(ref_label)

        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._on_image_dropped)
        left_layout.addWidget(self.drop_zone)

        # Browse button for reference image
        browse_ref_layout = QHBoxLayout()
        self.ref_path_label = QLabel("No image selected")
        self.ref_path_label.setWordWrap(True)
        self.ref_path_label.setProperty("cssClass", "status")
        browse_ref_layout.addWidget(self.ref_path_label, 1)

        self.browse_ref_btn = QPushButton("Browse...")
        self.browse_ref_btn.clicked.connect(self._browse_reference_image)
        browse_ref_layout.addWidget(self.browse_ref_btn)

        left_layout.addLayout(browse_ref_layout)
        top_layout.addWidget(left_frame)

        # Right side - folder selection
        right_frame = QFrame()
        right_frame.setProperty("cssClass", "card")
        right_layout = QVBoxLayout(right_frame)

        folder_label = QLabel("Search In Folder")
        folder_label.setProperty("cssClass", "section-title")
        folder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(folder_label)

        folder_input_layout = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Select folder to search in...")
        self.folder_input.setReadOnly(True)
        folder_input_layout.addWidget(self.folder_input)

        self.browse_folder_btn = QPushButton("Browse")
        self.browse_folder_btn.setProperty("cssClass", "browse")
        self.browse_folder_btn.clicked.connect(self._browse_folder)
        folder_input_layout.addWidget(self.browse_folder_btn)

        right_layout.addLayout(folder_input_layout)

        # Threshold slider
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Threshold:"))

        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setMinimum(50)
        self.threshold_slider.setMaximum(100)
        self.threshold_slider.setValue(85)
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        threshold_layout.addWidget(self.threshold_slider)

        self.threshold_label = QLabel("0.85")
        self.threshold_label.setFixedWidth(40)
        threshold_layout.addWidget(self.threshold_label)

        right_layout.addLayout(threshold_layout)

        # Search button
        self.search_btn = QPushButton("Search")
        self.search_btn.setEnabled(False)
        self.search_btn.clicked.connect(self._start_search)
        right_layout.addWidget(self.search_btn)

        right_layout.addStretch()
        top_layout.addWidget(right_frame)

        layout.addLayout(top_layout)

        # Progress section
        progress_layout = QHBoxLayout()
        self.status_label = QLabel("Select a reference image and folder to search")
        self.status_label.setProperty("cssClass", "status")
        progress_layout.addWidget(self.status_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        progress_layout.addWidget(self.progress_bar)

        layout.addLayout(progress_layout)

        # Results section
        results_label = QLabel("Similar Images Found")
        results_label.setProperty("cssClass", "section-title")
        layout.addWidget(results_label)

        self.results_list = QListWidget()
        self.results_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.results_list.setIconSize(QSize(150, 150))
        self.results_list.setSpacing(10)
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results_list.setWrapping(True)
        self.results_list.itemDoubleClicked.connect(self._on_result_double_clicked)
        self.results_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.results_list, 1)

        # Bottom buttons
        bottom_layout = QHBoxLayout()

        self.delete_btn = QPushButton("Delete Selected (0)")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)
        bottom_layout.addWidget(self.delete_btn)

        bottom_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(self.close_btn)

        layout.addLayout(bottom_layout)

    def _update_search_button(self):
        """Enable search button if both image and folder are selected"""
        enabled = bool(self.search_image_path and self.search_folder)
        self.search_btn.setEnabled(enabled)

    def _load_from_config(self):
        """Load settings from config"""
        # Set folder if available
        if self.search_folder:
            self.folder_input.setText(self.search_folder)

    @Slot(str)
    def _on_image_dropped(self, path: str):
        """Handle image dropped on drop zone"""
        self._set_reference_image(path)

    @Slot()
    def _browse_reference_image(self):
        """Browse for reference image"""
        extensions = ' '.join(f'*{ext}' for ext in SUPPORTED_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Reference Image",
            "",
            f"Images ({extensions})"
        )
        if path:
            self._set_reference_image(path)

    def _set_reference_image(self, path: str):
        """Set the reference image"""
        self.search_image_path = path
        self.drop_zone.set_image(path)
        filename = Path(path).name
        if len(filename) > 40:
            filename = filename[:37] + "..."
        self.ref_path_label.setText(filename)
        self._update_search_button()

    @Slot()
    def _browse_folder(self):
        """Browse for search folder"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Search",
            self.search_folder or ""
        )
        if folder:
            self.search_folder = folder
            self.folder_input.setText(folder)
            # Save to config
            self.config["last_search_folder"] = folder
            self._update_search_button()

    @Slot(int)
    def _on_threshold_changed(self, value: int):
        """Handle threshold slider change"""
        self.threshold_label.setText(f"{value / 100:.2f}")

    @Slot()
    def _start_search(self):
        """Start the search process"""
        if not self.search_image_path or not self.search_folder:
            return

        self.results_list.clear()
        self.results.clear()
        self._set_controls_enabled(False)

        self.status_label.setText("Scanning folder for images...")
        self.progress_bar.setValue(0)

        # Start scan worker
        min_res = self.config.get("min_resolution", [256, 256])
        min_resolution = tuple(min_res) if min_res else None

        self._scan_worker = ScanWorker(
            directory=self.search_folder,
            recursive=self.config.get("recursive_scan", True),
            excluded_dirs=self.config.get("excluded_dirs", []),
            min_resolution=min_resolution
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_error)
        self._scan_worker.start()

    @Slot(int, int, str)
    def _on_scan_progress(self, current: int, total: int, filename: str):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)

    @Slot(list)
    def _on_scan_finished(self, images: list):
        self._scan_worker = None

        if not images:
            self.status_label.setText("No images found in folder")
            self._set_controls_enabled(True)
            return

        # Add reference image to list if not already there
        image_paths = [img.path for img in images]
        if self.search_image_path not in image_paths:
            image_paths.insert(0, self.search_image_path)

        self.status_label.setText(f"Found {len(images)} images. Computing embeddings...")

        # Start embedding worker
        self._embed_worker = EmbedWorker(
            image_paths=image_paths,
            model_name=self.config.get("model_name", "clip-ViT-B-32"),
            cache=self.cache,
            batch_size=self.config.get("batch_size", 512),
            use_gpu=self.config.get("use_gpu", True),
            io_workers=self.config.get("io_workers", 12)
        )
        self._embed_worker.progress.connect(self._on_embed_progress)
        self._embed_worker.status.connect(self._on_embed_status)
        self._embed_worker.finished.connect(self._on_embed_finished)
        self._embed_worker.error.connect(self._on_error)
        self._embed_worker.start()

    @Slot(int, int, str)
    def _on_embed_progress(self, current: int, total: int, message: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @Slot(str)
    def _on_embed_status(self, message: str):
        self.status_label.setText(message)

    @Slot(dict)
    def _on_embed_finished(self, embeddings: dict):
        self._embed_worker = None
        self.embeddings = embeddings

        # Get reference embedding
        self.search_embedding = embeddings.get(self.search_image_path)
        if self.search_embedding is None:
            self.status_label.setText("Failed to compute embedding for reference image")
            self._set_controls_enabled(True)
            return

        # Compute similarities
        self.status_label.setText("Computing similarities...")
        QApplication.processEvents()

        threshold = self.threshold_slider.value() / 100.0
        self.results = []

        from sklearn.metrics.pairwise import cosine_similarity

        ref_emb = self.search_embedding.reshape(1, -1)

        ref_resolved = os.path.normpath(os.path.abspath(self.search_image_path))

        for path, emb in embeddings.items():
            if emb is None:
                continue
            if os.path.normpath(os.path.abspath(path)) == ref_resolved:
                continue

            score = cosine_similarity(ref_emb, emb.reshape(1, -1))[0, 0]
            if score >= threshold:
                self.results.append((path, float(score)))

        # Sort by score descending
        self.results.sort(key=lambda x: x[1], reverse=True)

        # Display results
        self._display_results()
        self._set_controls_enabled(True)

        if self.results:
            self.status_label.setText(f"Found {len(self.results)} similar images")
        else:
            self.status_label.setText("No similar images found at current threshold")

    def _display_results(self):
        """Display search results in the list"""
        self.results_list.clear()

        for path, score in self.results:
            # Create thumbnail
            thumb = ImageUtils.create_thumbnail(path, (150, 150))
            if thumb:
                # Convert PIL to QPixmap
                import io
                buffer = io.BytesIO()
                thumb.save(buffer, format='PNG')
                buffer.seek(0)

                from PySide6.QtGui import QIcon
                pixmap = QPixmap()
                pixmap.loadFromData(buffer.getvalue())

                item = QListWidgetItem()
                item.setIcon(QIcon(pixmap))

                filename = Path(path).name
                if len(filename) > 20:
                    filename = filename[:17] + "..."
                item.setText(f"{filename}\n{score:.1%}")
                item.setData(Qt.ItemDataRole.UserRole, path)

                self.results_list.addItem(item)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle Delete key to delete selected images"""
        if event.key() == Qt.Key.Key_Delete:
            if self.results_list.selectedItems():
                self._delete_selected()
                return
        super().keyPressEvent(event)

    @Slot()
    def _on_selection_changed(self):
        """Update delete button text with selection count"""
        count = len(self.results_list.selectedItems())
        self.delete_btn.setText(f"Delete Selected ({count})")
        self.delete_btn.setEnabled(count > 0)

    @Slot()
    def _delete_selected(self):
        """Delete selected images from disk and remove from results"""
        selected = self.results_list.selectedItems()
        if not selected:
            return

        paths = [item.data(Qt.ItemDataRole.UserRole) for item in selected]

        # Confirmation dialog
        if len(paths) == 1:
            filename = Path(paths[0]).name
            msg = f"Are you sure you want to permanently delete:\n{filename}?"
        else:
            filenames = [Path(p).name for p in paths[:5]]
            msg = f"Are you sure you want to permanently delete {len(paths)} files?\n\n"
            msg += "\n".join(filenames)
            if len(paths) > 5:
                msg += f"\n...and {len(paths) - 5} more"

        reply = QMessageBox.question(
            self, "Confirm Delete", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted_paths = set()
        errors = []
        for path in paths:
            try:
                os.remove(path)
                deleted_paths.add(path)
            except OSError as e:
                errors.append(f"{Path(path).name}: {e}")

        # Remove deleted items from the list widget (iterate in reverse to keep indices valid)
        for item in reversed(selected):
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in deleted_paths:
                self.results_list.takeItem(self.results_list.row(item))

        # Update internal results list
        self.results = [(p, s) for p, s in self.results if p not in deleted_paths]

        # Update status
        remaining = self.results_list.count()
        self.status_label.setText(f"Deleted {len(deleted_paths)} file(s). {remaining} similar images remaining.")

        if errors:
            QMessageBox.warning(
                self, "Delete Errors",
                f"Successfully deleted {len(deleted_paths)} file(s).\n\nErrors:\n" + "\n".join(errors)
            )

        self._on_selection_changed()

    @Slot(QListWidgetItem)
    def _on_result_double_clicked(self, item: QListWidgetItem):
        """Open the image location in explorer"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            import subprocess
            subprocess.run(['explorer', '/select,', path])

    @Slot(str)
    def _on_error(self, message: str):
        self._set_controls_enabled(True)
        self.status_label.setText(f"Error: {message}")
        QMessageBox.critical(self, "Error", message)

    def _set_controls_enabled(self, enabled: bool):
        self.search_btn.setEnabled(enabled and bool(self.search_image_path and self.search_folder))
        self.browse_ref_btn.setEnabled(enabled)
        self.browse_folder_btn.setEnabled(enabled)
        self.threshold_slider.setEnabled(enabled)
        self.drop_zone.setEnabled(enabled)

    def closeEvent(self, event):
        if self._scan_worker:
            self._scan_worker.cancel()
            self._scan_worker.wait()
        if self._embed_worker:
            self._embed_worker.cancel()
            self._embed_worker.wait()
        event.accept()
