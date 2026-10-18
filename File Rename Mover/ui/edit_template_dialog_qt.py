"""Edit Template dialog for File Rename Mover application (PySide6 version)"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.main_window_qt import MainWindowQt


class EditTemplateDialogQt(QDialog):
    """Dialog for editing an existing template (PySide6 version)"""

    def __init__(self, parent, app: 'MainWindowQt', template_name: str, template_data: dict):
        """
        Initialize edit template dialog

        Args:
            parent: Parent window
            app: Main application window instance
            template_name: Name of the template being edited
            template_data: Current template data dictionary
        """
        super().__init__(parent)
        self.app = app
        self.template_name = template_name
        self.template_data = template_data

        self.setWindowTitle(f"Edit Template: {template_name}")
        self.setMinimumSize(600, 550)
        self.setModal(True)

        # Apply same stylesheet as parent
        self.setStyleSheet(app.theme.get_stylesheet())

        self._setup_ui()
        self._load_template_data()

    def _setup_ui(self) -> None:
        """Set up the dialog UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # Title
        title_label = QLabel(f"Edit Template: {self.template_name}")
        title_font = QFont("Arial", 14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)

        # Scroll area for form content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(0, 10, 10, 10)
        layout.setSpacing(10)

        # Source Folder
        layout.addWidget(QLabel("Source Folder:"))
        source_layout = QHBoxLayout()
        self.source_entry = QLineEdit()
        source_layout.addWidget(self.source_entry)
        source_browse_btn = QPushButton("Browse")
        source_browse_btn.setProperty("cssClass", "browse")
        source_browse_btn.clicked.connect(self._browse_source)
        source_layout.addWidget(source_browse_btn)
        layout.addLayout(source_layout)

        # Destination Folder
        layout.addWidget(QLabel("Destination Folder:"))
        dest_layout = QHBoxLayout()
        self.dest_entry = QLineEdit()
        dest_layout.addWidget(self.dest_entry)
        dest_browse_btn = QPushButton("Browse")
        dest_browse_btn.setProperty("cssClass", "browse")
        dest_browse_btn.clicked.connect(self._browse_destination)
        dest_layout.addWidget(dest_browse_btn)
        layout.addLayout(dest_layout)

        # Extension
        layout.addWidget(QLabel("Extension:"))
        self.ext_entry = QLineEdit()
        layout.addWidget(self.ext_entry)

        # Base Name
        layout.addWidget(QLabel("Base Name:"))
        self.rename_entry = QLineEdit()
        layout.addWidget(self.rename_entry)

        # Sorting section
        section_label = QLabel("Sorting Options")
        section_font = QFont("Arial", 12)
        section_font.setBold(True)
        section_label.setFont(section_font)
        layout.addWidget(section_label)

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

        layout.addLayout(sort_layout)

        # Pattern section
        pattern_label = QLabel("Rename Pattern")
        pattern_label.setFont(section_font)
        layout.addWidget(pattern_label)

        layout.addWidget(QLabel("Pattern Type:"))
        self.pattern_type_combo = QComboBox()
        self.pattern_type_combo.addItems(["numbering", "datetime", "prefix", "custom"])
        self.pattern_type_combo.currentTextChanged.connect(self._on_pattern_type_changed)
        layout.addWidget(self.pattern_type_combo)

        # DateTime options (shown when datetime pattern selected)
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
        layout.addWidget(self.datetime_options_widget)

        # Custom pattern (shown when custom pattern selected)
        self.custom_pattern_widget = QWidget()
        custom_layout = QVBoxLayout(self.custom_pattern_widget)
        custom_layout.setContentsMargins(0, 5, 0, 0)

        custom_layout.addWidget(QLabel("Custom Pattern:"))
        hint_label = QLabel("Available: {counter}, {date}, {time}, {datetime}, {year}, {month}, {day}, {original}")
        hint_font = QFont("Arial", 9)
        hint_font.setItalic(True)
        hint_label.setFont(hint_font)
        custom_layout.addWidget(hint_label)
        self.custom_pattern_entry = QLineEdit()
        custom_layout.addWidget(self.custom_pattern_entry)

        self.custom_pattern_widget.setVisible(False)
        layout.addWidget(self.custom_pattern_widget)

        # Folder organization section
        folder_label = QLabel("Folder Organization")
        folder_label.setFont(section_font)
        layout.addWidget(folder_label)

        layout.addWidget(QLabel("Organize into:"))
        self.folder_structure_combo = QComboBox()
        self.folder_structure_combo.addItems([
            "flat", "year", "year_month", "year_month_day", "date", "month"
        ])
        layout.addWidget(self.folder_structure_combo)

        self.base_name_folder_check = QCheckBox(
            "Create a folder named after the Base Name  ([Base Name]\\year\\month\\day)"
        )
        layout.addWidget(self.base_name_folder_check)

        layout.addStretch()

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        # Buttons
        button_layout = QHBoxLayout()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_template)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

    def _load_template_data(self) -> None:
        """Load template data into form fields"""
        self.source_entry.setText(self.template_data.get("default_source_folder", ""))
        self.dest_entry.setText(self.template_data.get("default_destination_folder", ""))
        self.ext_entry.setText(self.template_data.get("last_extension", ""))
        self.rename_entry.setText(self.template_data.get("last_rename_to", ""))

        # Sorting
        sort_by = self.template_data.get("sort_by", "name")
        idx = self.sort_by_combo.findText(sort_by)
        if idx >= 0:
            self.sort_by_combo.setCurrentIndex(idx)

        sort_order = self.template_data.get("sort_order", "asc")
        idx = self.sort_order_combo.findText(sort_order)
        if idx >= 0:
            self.sort_order_combo.setCurrentIndex(idx)

        # Pattern
        pattern_type = self.template_data.get("pattern_type", "numbering")
        idx = self.pattern_type_combo.findText(pattern_type)
        if idx >= 0:
            self.pattern_type_combo.setCurrentIndex(idx)

        datetime_format = self.template_data.get("datetime_format", "YYYYMMDD")
        idx = self.datetime_format_combo.findText(datetime_format)
        if idx >= 0:
            self.datetime_format_combo.setCurrentIndex(idx)

        self.include_counter_check.setChecked(self.template_data.get("include_counter", True))
        self.custom_pattern_entry.setText(self.template_data.get("custom_pattern", "{counter}"))

        # Folder structure
        folder_structure = self.template_data.get("folder_structure", "flat")
        idx = self.folder_structure_combo.findText(folder_structure)
        if idx >= 0:
            self.folder_structure_combo.setCurrentIndex(idx)
        self.base_name_folder_check.setChecked(bool(self.template_data.get("base_name_folder", False)))

        # Update visibility
        self._on_pattern_type_changed()

    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    @Slot()
    def _browse_source(self) -> None:
        """Handle source folder browse button"""
        initial_dir = self.source_entry.text() or ""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Source Folder",
            initial_dir
        )
        if folder:
            self.source_entry.setText(folder)

    @Slot()
    def _browse_destination(self) -> None:
        """Handle destination folder browse button"""
        initial_dir = self.dest_entry.text() or ""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Destination Folder",
            initial_dir
        )
        if folder:
            self.dest_entry.setText(folder)

    @Slot()
    def _on_pattern_type_changed(self) -> None:
        """Handle pattern type change"""
        pattern_type = self.pattern_type_combo.currentText()

        # Hide all pattern-specific widgets
        self.datetime_options_widget.setVisible(False)
        self.custom_pattern_widget.setVisible(False)

        # Show relevant widget
        if pattern_type == "datetime":
            self.datetime_options_widget.setVisible(True)
        elif pattern_type == "custom":
            self.custom_pattern_widget.setVisible(True)

    def _get_edited_settings(self) -> dict:
        """Get all edited settings as a dictionary"""
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

    @Slot()
    def _save_template(self) -> None:
        """Save the edited template"""
        settings = self._get_edited_settings()

        if self.app.template_manager.save_template(self.template_name, settings):
            self.app.add_status(f"Template '{self.template_name}' updated successfully.")
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Save Failed",
                "Failed to save template changes. Please try again."
            )
