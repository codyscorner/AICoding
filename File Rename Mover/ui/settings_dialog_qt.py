"""Settings dialog for File Rename Mover application (PySide6 version)"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.main_window_qt import MainWindowQt


class SettingsDialogQt(QDialog):
    """Settings dialog window (PySide6 version)"""

    def __init__(self, parent, app: 'MainWindowQt'):
        """
        Initialize settings dialog

        Args:
            parent: Parent window
            app: Main application window instance
        """
        super().__init__(parent)
        self.app = app

        self.setWindowTitle("Settings")
        self.setFixedSize(700, 380)
        self.setModal(True)

        # Apply same stylesheet as parent
        self.setStyleSheet(app.theme.get_stylesheet())

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the settings dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title_label = QLabel("Default Folder Settings")
        title_font = QFont("Arial", 14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Default Source Folder
        layout.addWidget(QLabel("Default Source Folder:"))
        source_layout = QHBoxLayout()
        self.source_entry = QLineEdit()
        self.source_entry.setText(self.app.config.get("default_source_folder", ""))
        source_layout.addWidget(self.source_entry)

        source_browse_btn = QPushButton("Browse")
        source_browse_btn.setProperty("cssClass", "browse")
        source_browse_btn.clicked.connect(self._browse_source)
        source_layout.addWidget(source_browse_btn)
        layout.addLayout(source_layout)

        # Default Destination Folder
        layout.addWidget(QLabel("Default Destination Folder:"))
        dest_layout = QHBoxLayout()
        self.dest_entry = QLineEdit()
        self.dest_entry.setText(self.app.config.get("default_destination_folder", ""))
        dest_layout.addWidget(self.dest_entry)

        dest_browse_btn = QPushButton("Browse")
        dest_browse_btn.setProperty("cssClass", "browse")
        dest_browse_btn.clicked.connect(self._browse_destination)
        dest_layout.addWidget(dest_browse_btn)
        layout.addLayout(dest_layout)

        # File Safety section
        safety_label = QLabel("File Safety")
        safety_font = QFont("Arial", 12)
        safety_font.setBold(True)
        safety_label.setFont(safety_font)
        layout.addSpacing(10)
        layout.addWidget(safety_label)

        self.verify_hash_check = QCheckBox("Verify file integrity with hash (slower but safer)")
        self.verify_hash_check.setChecked(self.app.config.get("verify_hash", False))
        layout.addWidget(self.verify_hash_check)

        hint_label = QLabel("When enabled, files are verified using MD5 hash after copying.")
        hint_font = QFont("Arial", 9)
        hint_font.setItalic(True)
        hint_label.setFont(hint_font)
        layout.addWidget(hint_label)

        # Add stretch
        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    @Slot()
    def _browse_source(self) -> None:
        """Handle source folder browse button"""
        initial_dir = self.source_entry.text() or None
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Default Source Folder",
            initial_dir or ""
        )
        if folder:
            self.source_entry.setText(folder)

    @Slot()
    def _browse_destination(self) -> None:
        """Handle destination folder browse button"""
        initial_dir = self.dest_entry.text() or None
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Default Destination Folder",
            initial_dir or ""
        )
        if folder:
            self.dest_entry.setText(folder)

    @Slot()
    def _save_settings(self) -> None:
        """Save settings and close dialog"""
        # Update config
        self.app.config.set("default_source_folder", self.source_entry.text())
        self.app.config.set("default_destination_folder", self.dest_entry.text())
        self.app.config.set("verify_hash", self.verify_hash_check.isChecked())
        self.app.config.save()

        # Update main window fields
        self.app.update_from_config()

        QMessageBox.information(self, "Settings Saved", "Settings have been updated successfully!")
        self.accept()
