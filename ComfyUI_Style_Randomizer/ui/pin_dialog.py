from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
)
from PyQt6.QtCore import Qt

from worker import PromptEntry


class PinPromptDialog(QDialog):
    """Lets the user pin a specific style prompt to one image, overriding random/sequential selection."""

    def __init__(self, image_name: str, prompts: list[PromptEntry], current_pin: str | None, parent=None):
        super().__init__(parent)
        self._prompts = prompts
        self.chosen: str | None = current_pin  # None = no change, "" = clear pin
        self.setWindowTitle(f"Pin Style — {image_name}")
        self.setMinimumSize(520, 420)
        self.resize(900, 720)
        self._build_ui(image_name, current_pin)

    def _build_ui(self, image_name: str, current_pin: str | None):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hint = QLabel(f"Pick a style to pin to <b>{image_name}</b> — it will always use this prompt.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._list = QListWidget()
        # Show each prompt in full, wrapped to the list width. Many prompts share
        # the same opening sentence, so a truncated preview can't tell them apart.
        self._list.setWordWrap(True)
        self._list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setStyleSheet("QListWidget::item { padding: 6px 4px; }")
        for i, entry in enumerate(self._prompts):
            label = f"{i+1}.  {' '.join(entry.text.split())}"
            if entry.weight != 1.0:
                label += f"   [{entry.weight:g}x]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry.text)
            self._list.addItem(item)
            if current_pin is not None and entry.text == current_pin:
                self._list.setCurrentItem(item)
        layout.addWidget(self._list, stretch=1)

        bottom = QHBoxLayout()
        clear_btn = QPushButton("Clear Pin")
        clear_btn.setObjectName("cancel_btn")
        clear_btn.setEnabled(current_pin is not None)
        clear_btn.clicked.connect(self._clear)
        bottom.addWidget(clear_btn)
        bottom.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.setMinimumWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        pin_btn = QPushButton("Pin")
        pin_btn.setMinimumWidth(90)
        pin_btn.clicked.connect(self._pin)
        bottom.addWidget(pin_btn)

        layout.addLayout(bottom)

    def _pin(self):
        item = self._list.currentItem()
        if not item:
            return
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _clear(self):
        self.chosen = ""
        self.accept()
