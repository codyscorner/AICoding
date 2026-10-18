"""Enhanced main window UI with advanced features for File Rename Mover application (PySide6 version)"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QListWidget,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QSizePolicy,
    QProgressBar, QApplication
)
from PySide6.QtCore import Qt, Slot, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QCloseEvent
import os
from pathlib import Path
from typing import Optional, Callable

from config import ConfigManager
from file_operations import FileRenamer, FileScanner
from ui.styles_qt import ThemeManager
from sorting import SortBy, SortOrder
from rename_patterns import PatternType, DateTimeFormat, PatternFactory
from folder_organization import FolderStructure, FolderOrganizer
from templates import TemplateManager


class FolderDropLineEdit(QLineEdit):
    """QLineEdit that accepts folder drag-and-drop from Windows Explorer."""

    folder_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _accepts(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        urls = event.mimeData().urls()
        return len(urls) == 1 and Path(urls[0].toLocalFile()).is_dir()

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self._accepts(event):
            path = str(Path(event.mimeData().urls()[0].toLocalFile()))
            self.setText(path)
            self.folder_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()


class ExtensionCombo(QComboBox):
    """
    Editable extension picker.

    Behaves like the QLineEdit it replaces (``text()``, ``setText()``,
    ``textChanged``) so the rest of the window doesn't care, but its dropdown is
    filled with the extensions actually present in the source folder.
    """

    textChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lineEdit().setPlaceholderText("e.g. .mp4  (pick a source folder to list what's in it)")
        self.editTextChanged.connect(self.textChanged.emit)

    def text(self) -> str:
        return self.currentText()

    def setText(self, value: str) -> None:
        self.setEditText(value or "")

    def set_extensions(self, counts: list) -> None:
        """
        Replace the dropdown items with ``[(ext, count), ...]``, keeping whatever
        is typed in the edit box. If the box is empty, the most common extension
        is selected.
        """
        current = self.currentText().strip()
        self.blockSignals(True)
        try:
            self.clear()
            for ext, count in counts:
                self.addItem(ext)
                idx = self.count() - 1
                plural = "file" if count == 1 else "files"
                self.setItemData(idx, f"{count} {plural}", Qt.ToolTipRole)
            self.setEditText(current)
        finally:
            self.blockSignals(False)

        if not current and counts:
            self.setCurrentIndex(0)  # emits editTextChanged -> textChanged
        elif current:
            # Snap to the matching item so the dropdown highlights it
            for i in range(self.count()):
                if self.itemText(i).lower() == current.lower() or self.itemText(i).lower() == '.' + current.lower():
                    self.setCurrentIndex(i)
                    break


class RenameWorker(QThread):
    """Worker thread for file rename/move operations."""

    status_updated = Signal(str)
    progress_updated = Signal(int, int, str)
    operation_finished = Signal(list)

    def __init__(
        self,
        source_folder: str,
        dest_folder: str,
        extension: str,
        base_name: str,
        rename_pattern,
        sort_by,
        sort_order,
        folder_structure,
        verify_hash: bool,
        base_name_folder: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._source_folder = source_folder
        self._dest_folder = dest_folder
        self._extension = extension
        self._base_name = base_name
        self._rename_pattern = rename_pattern
        self._sort_by = sort_by
        self._sort_order = sort_order
        self._folder_structure = folder_structure
        self._verify_hash = verify_hash
        self._base_name_folder = base_name_folder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        file_renamer = FileRenamer(
            status_callback=lambda msg: self.status_updated.emit(msg),
            progress_callback=lambda c, t, f: self.progress_updated.emit(c, t, f),
            cancel_check=lambda: self._cancelled,
            rename_pattern=self._rename_pattern,
            sort_by=self._sort_by,
            sort_order=self._sort_order,
            folder_structure=self._folder_structure,
            verify_hash=self._verify_hash,
            base_name_folder=self._base_name_folder,
        )
        try:
            results = file_renamer.move_and_rename(
                self._source_folder,
                self._dest_folder,
                self._extension,
                self._base_name,
            )
            self.operation_finished.emit(results or [])
        except Exception as e:
            self.status_updated.emit(f"Error: {e}")
            self.operation_finished.emit([])


class MainWindowQt(QMainWindow):
    """Enhanced main application window with advanced features (PySide6 version)"""

    def __init__(self, config_manager: ConfigManager, version: str, template_manager: TemplateManager):
        """
        Initialize enhanced main window

        Args:
            config_manager: Configuration manager instance
            version: Application version string
            template_manager: Template manager instance
        """
        super().__init__()

        self.config = config_manager
        self.version = version
        self.template_manager = template_manager

        # Initialize theme
        self.theme = ThemeManager('dark_red')
        self.colors = self.theme.get_all_colors()
        self.fonts = self.theme.get_all_fonts()

        self._worker: Optional[RenameWorker] = None
        self._pending_config: dict = {}

        # Set up window
        self.setWindowTitle(f"File Rename Mover (V-{self.version})")
        self.setMinimumSize(1000, 870)
        self.resize(1000, 870)

        # Apply stylesheet
        self.setStyleSheet(self.theme.get_stylesheet())

        # Build UI
        self._setup_ui()

        # Load initial values from config
        self._load_from_config()

        # Connect signals
        self._connect_signals()

        # Update examples
        self._update_example()
        self._update_folder_example()

    def _setup_ui(self) -> None:
        """Set up the main UI components"""
        # Central widget with scroll area
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for the form
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(15, 10, 15, 10)
        scroll_layout.setSpacing(10)

        # Templates section (at the top for easy access)
        self._create_templates_section(scroll_layout)

        # Source and Destination folders
        self._create_folder_inputs(scroll_layout)

        # Extension and Base Name
        self._create_basic_inputs(scroll_layout)

        # Sorting options
        self._create_sorting_section(scroll_layout)

        # Rename pattern (left) and Folder organization (right) side by side
        # Each column lives in a container whose width hint is ignored, so the two
        # stretch factors split the row exactly 50/50 no matter how long a label is.
        two_col = QHBoxLayout()
        two_col.setSpacing(20)
        pattern_box = QWidget()
        pattern_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pattern_col = QVBoxLayout(pattern_box)
        pattern_col.setContentsMargins(0, 0, 0, 0)
        pattern_col.setSpacing(10)
        self._create_pattern_section(pattern_col)
        pattern_col.addStretch()
        folder_box = QWidget()
        folder_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        folder_col = QVBoxLayout(folder_box)
        folder_col.setContentsMargins(0, 0, 0, 0)
        folder_col.setSpacing(10)
        self._create_folder_organization_section(folder_col)
        folder_col.addStretch()
        two_col.addWidget(pattern_box, 1)
        two_col.addWidget(folder_box, 1)
        scroll_layout.addLayout(two_col)

        # Buttons
        self._create_buttons(scroll_layout)

        # Status listbox — takes every remaining pixel instead of a trailing stretch
        self._create_status_listbox(scroll_layout)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

    def _create_section_title(self, text: str) -> QLabel:
        """Create a section title label"""
        label = QLabel(text)
        label.setProperty("cssClass", "section-title")
        font = QFont("Arial", 12)
        font.setBold(True)
        label.setFont(font)
        return label

    def _create_italic_label(self, text: str = "") -> QLabel:
        """Create an italic label for examples"""
        label = QLabel(text)
        label.setProperty("cssClass", "italic")
        font = QFont("Arial", 9)
        font.setItalic(True)
        label.setFont(font)
        return label

    def _create_templates_section(self, parent_layout: QVBoxLayout) -> None:
        """Create templates section for saving/loading presets"""
        # Title
        parent_layout.addWidget(self._create_section_title("Templates"))

        # Controls row
        controls_layout = QHBoxLayout()

        # Template dropdown
        self.template_combo = QComboBox()
        self.template_combo.addItems(self.template_manager.get_template_names())
        self.template_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.template_combo.currentTextChanged.connect(self._load_template)
        controls_layout.addWidget(self.template_combo)

        # Load button
        self.load_template_btn = QPushButton("Load")
        self.load_template_btn.clicked.connect(self._load_template)
        controls_layout.addWidget(self.load_template_btn)

        # Save button
        self.save_template_btn = QPushButton("Save")
        self.save_template_btn.clicked.connect(self._save_template)
        controls_layout.addWidget(self.save_template_btn)

        # Manage button
        self.manage_templates_btn = QPushButton("Manage")
        self.manage_templates_btn.clicked.connect(self._manage_templates)
        controls_layout.addWidget(self.manage_templates_btn)

        parent_layout.addLayout(controls_layout)

        # Add spacing after section
        parent_layout.addSpacing(10)

    def _create_folder_inputs(self, parent_layout: QVBoxLayout) -> None:
        """Create source and destination folder inputs"""
        # Source Folder
        parent_layout.addWidget(QLabel("Source Folder:"))
        source_layout = QHBoxLayout()
        self.source_entry = FolderDropLineEdit()
        self.source_entry.folder_dropped.connect(self._on_source_dropped)
        source_layout.addWidget(self.source_entry)
        self.source_browse_btn = QPushButton("Browse")
        self.source_browse_btn.setProperty("cssClass", "browse")
        self.source_browse_btn.clicked.connect(self._browse_source)
        source_layout.addWidget(self.source_browse_btn)
        parent_layout.addLayout(source_layout)

        # Destination Folder
        parent_layout.addWidget(QLabel("Destination Folder:"))
        dest_layout = QHBoxLayout()
        self.dest_entry = FolderDropLineEdit()
        self.dest_entry.folder_dropped.connect(self._on_dest_dropped)
        dest_layout.addWidget(self.dest_entry)
        self.dest_browse_btn = QPushButton("Browse")
        self.dest_browse_btn.setProperty("cssClass", "browse")
        self.dest_browse_btn.clicked.connect(self._browse_destination)
        dest_layout.addWidget(self.dest_browse_btn)
        parent_layout.addLayout(dest_layout)

    def _create_basic_inputs(self, parent_layout: QVBoxLayout) -> None:
        """Create extension and base name inputs"""
        # Extension
        row = QHBoxLayout()
        row.setSpacing(20)

        # Extension (left)
        ext_col = QVBoxLayout()
        self.ext_label = QLabel("Extension:")
        ext_col.addWidget(self.ext_label)
        self.ext_entry = ExtensionCombo()
        self.ext_entry.setToolTip("Extensions found in the source folder, most common first. You can also type one.")
        ext_col.addWidget(self.ext_entry)
        row.addLayout(ext_col, 1)

        # Base name (right)
        name_col = QVBoxLayout()
        name_col.addWidget(QLabel("Base Name:"))
        self.rename_entry = QLineEdit()
        name_col.addWidget(self.rename_entry)
        row.addLayout(name_col, 1)

        parent_layout.addLayout(row)

        # Example label spans both columns
        self.example_label = self._create_italic_label()
        parent_layout.addWidget(self.example_label)

    def _create_sorting_section(self, parent_layout: QVBoxLayout) -> None:
        """Create sorting options section"""
        parent_layout.addWidget(self._create_section_title("Sorting Options"))

        # Sort by and order in one row
        sort_layout = QHBoxLayout()

        # Sort by
        sort_by_layout = QVBoxLayout()
        sort_by_layout.addWidget(QLabel("Sort by:"))
        self.sort_by_combo = QComboBox()
        self.sort_by_combo.addItems(["name", "date_modified", "date_created", "size"])
        sort_by_layout.addWidget(self.sort_by_combo)
        sort_layout.addLayout(sort_by_layout)

        # Sort order
        sort_order_layout = QVBoxLayout()
        sort_order_layout.addWidget(QLabel("Order:"))
        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItems(["asc", "desc"])
        sort_order_layout.addWidget(self.sort_order_combo)
        sort_layout.addLayout(sort_order_layout)

        parent_layout.addLayout(sort_layout)

    def _create_pattern_section(self, parent_layout: QVBoxLayout) -> None:
        """Create rename pattern options section"""
        parent_layout.addWidget(self._create_section_title("Rename Pattern"))

        # Pattern type
        parent_layout.addWidget(QLabel("Pattern Type:"))
        self.pattern_type_combo = QComboBox()
        self.pattern_type_combo.addItems(["numbering", "datetime", "prefix", "custom"])
        self.pattern_type_combo.currentTextChanged.connect(self._on_pattern_type_changed)
        parent_layout.addWidget(self.pattern_type_combo)

        # Datetime options frame (shown when datetime pattern selected)
        self.datetime_options_widget = QWidget()
        datetime_layout = QVBoxLayout(self.datetime_options_widget)
        datetime_layout.setContentsMargins(0, 5, 0, 0)

        datetime_layout.addWidget(QLabel("DateTime Format:"))
        self.datetime_format_combo = QComboBox()
        self.datetime_format_combo.addItems([
            "YYYYMMDD", "YYYY_MM_DD", "YYYYMMDD_HHMMSS",
            "YYYY_MM_DD_HH_MM_SS", "MMDDYYYY", "DDMMYYYY"
        ])
        datetime_layout.addWidget(self.datetime_format_combo)

        self.include_counter_check = QCheckBox("Include counter")
        self.include_counter_check.setChecked(True)
        datetime_layout.addWidget(self.include_counter_check)

        self.datetime_options_widget.setVisible(False)
        parent_layout.addWidget(self.datetime_options_widget)

        # Custom pattern frame (shown when custom pattern selected)
        self.custom_pattern_widget = QWidget()
        custom_layout = QVBoxLayout(self.custom_pattern_widget)
        custom_layout.setContentsMargins(0, 5, 0, 0)

        custom_layout.addWidget(QLabel("Custom Pattern:"))
        hint_label = self._create_italic_label(
            "Available: {counter}, {date}, {time}, {datetime}, {year}, {month}, {day}, {original}"
        )
        hint_label.setWordWrap(True)
        custom_layout.addWidget(hint_label)
        self.custom_pattern_entry = QLineEdit()
        self.custom_pattern_entry.setText("{counter}")
        custom_layout.addWidget(self.custom_pattern_entry)

        self.custom_pattern_widget.setVisible(False)
        parent_layout.addWidget(self.custom_pattern_widget)

    def _create_folder_organization_section(self, parent_layout: QVBoxLayout) -> None:
        """Create folder organization section"""
        parent_layout.addWidget(self._create_section_title("Folder Organization"))

        # Folder structure
        parent_layout.addWidget(QLabel("Organize into:"))
        self.folder_structure_combo = QComboBox()
        self.folder_structure_combo.addItems([
            "flat", "year", "year_month", "year_month_day", "date", "month"
        ])
        self.folder_structure_combo.currentTextChanged.connect(self._update_folder_example)
        parent_layout.addWidget(self.folder_structure_combo)

        # Base-name folder option: dest\[Base Name]\year\month\day
        self.base_name_folder_check = QCheckBox("Folder named after Base Name")
        self.base_name_folder_check.setToolTip(
            "Files are moved into dest\\[Base Name]\\year\\month\\day.\n"
            "Any date organization above is created inside the Base Name folder."
        )
        self.base_name_folder_check.stateChanged.connect(self._update_folder_example)
        parent_layout.addWidget(self.base_name_folder_check)

        # Example label
        self.folder_example_label = self._create_italic_label()
        self.folder_example_label.setWordWrap(True)
        parent_layout.addWidget(self.folder_example_label)

    def _create_buttons(self, parent_layout: QVBoxLayout) -> None:
        """Create action buttons"""
        button_layout = QHBoxLayout()

        self.preview_button = QPushButton("Preview")
        self.preview_button.setToolTip("Dry run: list what would be moved and renamed without touching any files")
        self.preview_button.clicked.connect(self._preview)
        button_layout.addWidget(self.preview_button)

        self.move_button = QPushButton("Move and Rename")
        self.move_button.clicked.connect(self._move_and_rename)
        button_layout.addWidget(self.move_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_operation)
        button_layout.addWidget(self.cancel_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self._open_settings)
        button_layout.addWidget(self.settings_button)

        button_layout.addStretch()
        parent_layout.addLayout(button_layout)

    def _create_status_listbox(self, parent_layout: QVBoxLayout) -> None:
        """Create status listbox with progress bar"""
        parent_layout.addWidget(QLabel("Status:"))

        # Progress bar (initially hidden)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m files (%p%)")
        parent_layout.addWidget(self.progress_bar)

        # Progress label
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        progress_font = QFont("Arial", 9)
        progress_font.setItalic(True)
        self.progress_label.setFont(progress_font)
        parent_layout.addWidget(self.progress_label)

        self.status_listbox = QListWidget()
        self.status_listbox.setMinimumHeight(150)
        self.status_listbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        parent_layout.addWidget(self.status_listbox, 1)

        # Initial status message
        self.add_status("Ready to move and rename files...")

    def _load_from_config(self) -> None:
        """Load values from configuration"""
        self.source_entry.setText(self.config.get("default_source_folder", ""))
        self.dest_entry.setText(self.config.get("default_destination_folder", ""))
        self.ext_entry.setText(self.config.get("last_extension", ""))
        self.rename_entry.setText(self.config.get("last_rename_to", ""))

        # Sorting
        sort_by = self.config.get("sort_by", "name")
        idx = self.sort_by_combo.findText(sort_by)
        if idx >= 0:
            self.sort_by_combo.setCurrentIndex(idx)

        sort_order = self.config.get("sort_order", "asc")
        idx = self.sort_order_combo.findText(sort_order)
        if idx >= 0:
            self.sort_order_combo.setCurrentIndex(idx)

        # Pattern
        pattern_type = self.config.get("pattern_type", "numbering")
        idx = self.pattern_type_combo.findText(pattern_type)
        if idx >= 0:
            self.pattern_type_combo.setCurrentIndex(idx)

        datetime_format = self.config.get("datetime_format", "YYYYMMDD")
        idx = self.datetime_format_combo.findText(datetime_format)
        if idx >= 0:
            self.datetime_format_combo.setCurrentIndex(idx)

        self.include_counter_check.setChecked(self.config.get("include_counter", True))
        self.custom_pattern_entry.setText(self.config.get("custom_pattern", "{counter}"))

        # Folder structure
        folder_structure = self.config.get("folder_structure", "flat")
        idx = self.folder_structure_combo.findText(folder_structure)
        if idx >= 0:
            self.folder_structure_combo.setCurrentIndex(idx)
        self.base_name_folder_check.setChecked(bool(self.config.get("base_name_folder", False)))

        # Restore last selected template in the dropdown (without loading it)
        last_template = self.config.get("last_template", "")
        if last_template:
            idx = self.template_combo.findText(last_template)
            if idx >= 0:
                # Block the signal so it doesn't trigger _load_template and overwrite the
                # config-restored settings we just applied above
                self.template_combo.blockSignals(True)
                self.template_combo.setCurrentIndex(idx)
                self.template_combo.blockSignals(False)

        # Update visibility
        self._on_pattern_type_changed()

    def _connect_signals(self) -> None:
        """Connect UI signals to slots"""
        # Source folder -> refresh extension dropdown (debounced so typing a path
        # doesn't scan on every keystroke; browse/drop/template/config all funnel
        # through the same textChanged signal)
        self._ext_scan_timer = QTimer(self)
        self._ext_scan_timer.setSingleShot(True)
        self._ext_scan_timer.setInterval(350)
        self._ext_scan_timer.timeout.connect(self._refresh_extension_list)
        self.source_entry.textChanged.connect(self._ext_scan_timer.start)
        self._refresh_extension_list()

        # Text changes that update example
        self.ext_entry.textChanged.connect(self._update_example)
        self.rename_entry.textChanged.connect(self._update_example)
        self.rename_entry.textChanged.connect(self._update_folder_example)
        self.datetime_format_combo.currentTextChanged.connect(self._update_example)
        self.include_counter_check.stateChanged.connect(self._update_example)
        self.custom_pattern_entry.textChanged.connect(self._update_example)

    @Slot()
    def _browse_source(self) -> None:
        """Handle source folder browse button"""
        initial_dir = self.source_entry.text() or self.config.get("default_source_folder", "")
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Source Folder",
            initial_dir
        )
        if folder:
            self.source_entry.setText(folder)
            self.config.set("default_source_folder", folder)
            self.config.save()
            self.add_status(f"Source folder selected: {folder}")

    @Slot()
    def _browse_destination(self) -> None:
        """Handle destination folder browse button"""
        initial_dir = self.dest_entry.text() or self.config.get("default_destination_folder", "")
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Destination Folder",
            initial_dir
        )
        if folder:
            self.dest_entry.setText(folder)
            self.config.set("default_destination_folder", folder)
            self.config.save()
            self.add_status(f"Destination folder selected: {folder}")

    @Slot()
    def _on_pattern_type_changed(self) -> None:
        """Handle pattern type change"""
        pattern_type = self.pattern_type_combo.currentText()

        # Hide all pattern-specific frames
        self.datetime_options_widget.setVisible(False)
        self.custom_pattern_widget.setVisible(False)

        # Show relevant frame
        if pattern_type == "datetime":
            self.datetime_options_widget.setVisible(True)
        elif pattern_type == "custom":
            self.custom_pattern_widget.setVisible(True)

        self._update_example()

    @Slot()
    def _refresh_extension_list(self) -> None:
        """Fill the Extension dropdown with the extensions present in the source folder"""
        folder = self.source_entry.text().strip()
        if not folder or not os.path.isdir(folder):
            self.ext_entry.set_extensions([])
            self.ext_label.setText("Extension:")
            return

        counts = FileScanner.get_extension_counts(folder)
        self.ext_entry.set_extensions(counts)

        if counts:
            kinds = len(counts)
            self.ext_label.setText(f"Extension:  ({kinds} type{'s' if kinds != 1 else ''} found in source)")
            summary = ", ".join(f"{ext} \u00d7{n}" for ext, n in counts[:8])
            if kinds > 8:
                summary += f", \u2026 +{kinds - 8} more"
            self.add_status(f"Source folder contains: {summary}")
        else:
            self.ext_label.setText("Extension:  (no files found in source)")

    @Slot()
    def _update_example(self) -> None:
        """Update the example filename as user types"""
        try:
            base_name = self.rename_entry.text().strip()
            extension = self.ext_entry.text().strip()

            if not extension.startswith('.') and extension:
                extension = '.' + extension

            if not base_name:
                self.example_label.setText("")
                return

            # Create pattern
            pattern_type = PatternType(self.pattern_type_combo.currentText())
            pattern = self._create_pattern(pattern_type)

            # Generate example filename
            example_filename = pattern.generate_filename(
                base_name,
                extension,
                1,
                None
            )

            self.example_label.setText(f"Example: {example_filename}")
        except Exception:
            self.example_label.setText("")

    @Slot()
    def _update_folder_example(self) -> None:
        """Update the folder organization example"""
        try:
            structure = FolderStructure(self.folder_structure_combo.currentText())
            base_name_folder = None
            if self.base_name_folder_check.isChecked():
                base_name_folder = self.rename_entry.text().strip() or "[Base Name]"
            example = FolderOrganizer.get_folder_structure_example(structure, base_name_folder)
            self.folder_example_label.setText(f"Example: {example}")
        except Exception:
            self.folder_example_label.setText("")

    def _create_pattern(self, pattern_type: PatternType):
        """Create rename pattern from UI settings"""
        if pattern_type == PatternType.NUMBERING:
            return PatternFactory.create_pattern(PatternType.NUMBERING)

        elif pattern_type == PatternType.DATETIME:
            dt_format = DateTimeFormat[self.datetime_format_combo.currentText()]
            return PatternFactory.create_pattern(
                PatternType.DATETIME,
                datetime_format=dt_format,
                include_counter=self.include_counter_check.isChecked(),
                use_file_date=True
            )

        elif pattern_type == PatternType.PREFIX:
            return PatternFactory.create_pattern(
                PatternType.PREFIX,
                prefix=self.rename_entry.text().strip(),
                keep_original_name=True
            )

        elif pattern_type == PatternType.CUSTOM:
            return PatternFactory.create_pattern(
                PatternType.CUSTOM,
                pattern_string=self.custom_pattern_entry.text()
            )

        else:
            return PatternFactory.create_pattern(PatternType.NUMBERING)

    @Slot()
    def _open_settings(self) -> None:
        """Open the settings dialog"""
        from ui.settings_dialog_qt import SettingsDialogQt
        dialog = SettingsDialogQt(self, self)
        dialog.exec()

    def _collect_operation(self) -> Optional[dict]:
        """
        Read and validate every input the operation needs.

        Shows an error dialog and returns None when something is missing or invalid.
        """
        source_folder = self.source_entry.text().strip()
        dest_folder = self.dest_entry.text().strip()
        extension = self.ext_entry.text().strip()
        base_name = self.rename_entry.text().strip()

        if not source_folder:
            QMessageBox.critical(self, "Error", "Please select a source folder")
            return None
        if not dest_folder:
            QMessageBox.critical(self, "Error", "Please select a destination folder")
            return None
        if not extension:
            QMessageBox.critical(self, "Error", "Please enter a file extension")
            return None
        if not base_name:
            QMessageBox.critical(self, "Error", "Please enter a base name")
            return None

        # Pre-validate before spinning up the thread so errors surface as dialogs
        from file_operations import FileValidator
        try:
            FileValidator.validate_folder_exists(source_folder)
            FileValidator.validate_extension(extension)
            FileValidator.validate_rename_pattern(base_name)
        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", str(e))
            return None

        try:
            pattern_type = PatternType(self.pattern_type_combo.currentText())
            pattern = self._create_pattern(pattern_type)
            sort_by_value = self.sort_by_combo.currentText()
            sort_by = {
                "name": SortBy.NAME,
                "date_modified": SortBy.DATE_MODIFIED,
                "date_created": SortBy.DATE_CREATED,
                "size": SortBy.SIZE,
            }.get(sort_by_value, SortBy.NAME)
            sort_order = (
                SortOrder.ASCENDING if self.sort_order_combo.currentText() == "asc"
                else SortOrder.DESCENDING
            )
            folder_structure = FolderStructure(self.folder_structure_combo.currentText())
        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", str(e))
            return None

        return {
            "source_folder": source_folder,
            "dest_folder": dest_folder,
            "extension": extension,
            "base_name": base_name,
            "rename_pattern": pattern,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "folder_structure": folder_structure,
            "verify_hash": self.config.get("verify_hash", False),
            "base_name_folder": self.base_name_folder_check.isChecked(),
        }

    @Slot()
    def _preview(self) -> None:
        """Dry run: list the planned moves in the status box without touching files."""
        op = self._collect_operation()
        if op is None:
            return

        renamer = FileRenamer(
            rename_pattern=op["rename_pattern"],
            sort_by=op["sort_by"],
            sort_order=op["sort_order"],
            folder_structure=op["folder_structure"],
            base_name_folder=op["base_name_folder"],
        )
        try:
            preview = renamer.generate_preview(
                op["source_folder"], op["extension"], op["base_name"], op["dest_folder"]
            )
        except Exception as e:
            QMessageBox.critical(self, "Preview Error", str(e))
            return

        self.status_listbox.clear()
        if not preview:
            self.add_status(f"Preview: no '{op['extension']}' files found in source folder")
            return

        self.add_status(f"Preview: {len(preview)} file(s) would be moved to {op['dest_folder']}")
        for original, new_path in preview:
            self.add_status(f"  {original} → {new_path}")
        self.add_status("Preview only — nothing has been moved.")
        self.status_listbox.scrollToTop()

    @Slot()
    def _move_and_rename(self) -> None:
        """Handle move and rename operation — starts a background worker thread."""
        op = self._collect_operation()
        if op is None:
            return
        source_folder = op["source_folder"]
        dest_folder = op["dest_folder"]
        extension = op["extension"]
        base_name = op["base_name"]
        pattern = op["rename_pattern"]
        sort_by = op["sort_by"]
        sort_order = op["sort_order"]
        folder_structure = op["folder_structure"]
        verify_hash = op["verify_hash"]

        # Snapshot config values to save when the worker finishes
        self._pending_config = {
            "last_extension": extension,
            "last_rename_to": base_name,
            "sort_by": self.sort_by_combo.currentText(),
            "sort_order": self.sort_order_combo.currentText(),
            "pattern_type": self.pattern_type_combo.currentText(),
            "datetime_format": self.datetime_format_combo.currentText(),
            "include_counter": self.include_counter_check.isChecked(),
            "folder_structure": self.folder_structure_combo.currentText(),
            "base_name_folder": self.base_name_folder_check.isChecked(),
            "custom_pattern": self.custom_pattern_entry.text(),
        }

        self.add_status("Starting move and rename operation...")
        self.progress_bar.setMaximum(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText("")
        self.progress_label.setVisible(True)
        self.move_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._worker = RenameWorker(
            source_folder=source_folder,
            dest_folder=dest_folder,
            extension=extension,
            base_name=base_name,
            rename_pattern=pattern,
            sort_by=sort_by,
            sort_order=sort_order,
            folder_structure=folder_structure,
            verify_hash=verify_hash,
            base_name_folder=op["base_name_folder"],
        )
        self._worker.status_updated.connect(self.add_status)
        self._worker.progress_updated.connect(self._on_worker_progress)
        self._worker.operation_finished.connect(self._on_worker_finished)
        self._worker.start()

    def add_status(self, message: str) -> None:
        """Add a status message to the listbox"""
        self.status_listbox.addItem(message)
        self.status_listbox.scrollToBottom()

    @Slot(int, int, str)
    def _on_worker_progress(self, current: int, total: int, filename: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"Processing: {filename}")

    @Slot()
    def _cancel_operation(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.add_status("Cancelling operation...")

    @Slot(list)
    def _on_worker_finished(self, results: list) -> None:
        cancelled = bool(self._worker and self._worker._cancelled)

        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.move_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        if cancelled:
            self.add_status("Operation cancelled.")
        else:
            success_count = sum(1 for r in results if r.success)
            error_count = sum(1 for r in results if not r.success)
            if error_count == 0 and success_count > 0:
                QMessageBox.information(self, "Success", f"Successfully moved and renamed {success_count} files")
            elif success_count > 0:
                QMessageBox.warning(
                    self,
                    "Completed with errors",
                    f"Moved {success_count} files with {error_count} errors. Check status for details.",
                )
            elif error_count == 0:
                QMessageBox.information(self, "No Files", "No files were found to process")

        for key, value in self._pending_config.items():
            self.config.set(key, value)
        self.config.save()

        self._worker = None

    @Slot(str)
    def _on_source_dropped(self, folder: str) -> None:
        self.config.set("default_source_folder", folder)
        self.config.save()
        self.add_status(f"Source folder selected: {folder}")

    @Slot(str)
    def _on_dest_dropped(self, folder: str) -> None:
        self.config.set("default_destination_folder", folder)
        self.config.save()
        self.add_status(f"Destination folder selected: {folder}")

    def update_from_config(self) -> None:
        """Update UI fields from configuration"""
        self.source_entry.setText(self.config.get("default_source_folder", ""))
        self.dest_entry.setText(self.config.get("default_destination_folder", ""))

    def _get_current_settings(self) -> dict:
        """Get all current UI settings as a dictionary"""
        return {
            "default_source_folder": self.source_entry.text(),
            "default_destination_folder": self.dest_entry.text(),
            "last_extension": self.ext_entry.text(),
            "last_rename_to": self.rename_entry.text(),
            "sort_by": self.sort_by_combo.currentText(),
            "sort_order": self.sort_order_combo.currentText(),
            "pattern_type": self.pattern_type_combo.currentText(),
            "datetime_format": self.datetime_format_combo.currentText(),
            "include_counter": self.include_counter_check.isChecked(),
            "folder_structure": self.folder_structure_combo.currentText(),
            "base_name_folder": self.base_name_folder_check.isChecked(),
            "custom_pattern": self.custom_pattern_entry.text()
        }

    def _apply_settings(self, settings: dict) -> None:
        """Apply settings dictionary to UI"""
        if "default_source_folder" in settings:
            self.source_entry.setText(settings["default_source_folder"] or "")
        if "default_destination_folder" in settings:
            self.dest_entry.setText(settings["default_destination_folder"] or "")
        if "last_extension" in settings:
            self.ext_entry.setText(settings["last_extension"] or "")
        if "last_rename_to" in settings:
            self.rename_entry.setText(settings["last_rename_to"] or "")

        if "sort_by" in settings:
            idx = self.sort_by_combo.findText(settings["sort_by"] or "name")
            if idx >= 0:
                self.sort_by_combo.setCurrentIndex(idx)

        if "sort_order" in settings:
            idx = self.sort_order_combo.findText(settings["sort_order"] or "asc")
            if idx >= 0:
                self.sort_order_combo.setCurrentIndex(idx)

        if "pattern_type" in settings:
            idx = self.pattern_type_combo.findText(settings["pattern_type"] or "numbering")
            if idx >= 0:
                self.pattern_type_combo.setCurrentIndex(idx)

        if "datetime_format" in settings:
            idx = self.datetime_format_combo.findText(settings["datetime_format"] or "YYYYMMDD")
            if idx >= 0:
                self.datetime_format_combo.setCurrentIndex(idx)

        if "include_counter" in settings:
            self.include_counter_check.setChecked(settings.get("include_counter", True))

        if "folder_structure" in settings:
            idx = self.folder_structure_combo.findText(settings["folder_structure"] or "flat")
            if idx >= 0:
                self.folder_structure_combo.setCurrentIndex(idx)

        if "base_name_folder" in settings:
            self.base_name_folder_check.setChecked(bool(settings.get("base_name_folder", False)))

        if "custom_pattern" in settings:
            self.custom_pattern_entry.setText(settings["custom_pattern"] or "{counter}")

        # Update pattern UI visibility
        self._on_pattern_type_changed()

    def _refresh_template_list(self) -> None:
        """Refresh the template dropdown with current templates"""
        current_text = self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItems(self.template_manager.get_template_names())
        self.template_combo.blockSignals(False)
        # Try to restore selection
        idx = self.template_combo.findText(current_text)
        if idx >= 0:
            self.template_combo.setCurrentIndex(idx)

    @Slot()
    def _load_template(self) -> None:
        """Load selected template and apply settings"""
        template_name = self.template_combo.currentText()
        if not template_name:
            QMessageBox.warning(self, "No Template Selected", "Please select a template to load.")
            return

        template = self.template_manager.get_template(template_name)
        if template:
            self._apply_settings(template)
            self.config.set("last_template", template_name)
            self.config.save()
            self.add_status(f"Template '{template_name}' loaded successfully.")
        else:
            QMessageBox.critical(self, "Error", f"Template '{template_name}' not found.")

    @Slot()
    def _save_template(self) -> None:
        """Save current settings as a template"""
        from ui.save_template_dialog_qt import SaveTemplateDialogQt
        dialog = SaveTemplateDialogQt(self, self)
        dialog.exec()

    @Slot()
    def _manage_templates(self) -> None:
        """Open template management dialog"""
        from ui.manage_templates_dialog_qt import ManageTemplatesDialogQt
        dialog = ManageTemplatesDialogQt(self, self)
        dialog.exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save all current UI state when the window is closed"""
        self.config.update(self._get_current_settings())
        self.config.set("last_template", self.template_combo.currentText())
        self.config.save()
        super().closeEvent(event)
