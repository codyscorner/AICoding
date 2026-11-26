"""Transport bar: playback controls docked at the bottom of the window.

Prev / Play-Pause / Next buttons, a seek slider with elapsed/total time, a
volume slider, and a "now playing" label. It is a dumb view — it emits signals
and exposes setters; MainWindow owns the Player and does the wiring.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

ART_SIZE = 38


def format_time(ms: int) -> str:
    """Milliseconds -> "m:ss" (or "h:mm:ss" for long tracks)."""
    if ms <= 0:
        return "0:00"
    total = ms // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class TransportBar(QWidget):
    playPauseClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    seekRequested = pyqtSignal(int)      # position in ms
    volumeChanged = pyqtSignal(int)      # 0..100
    repeatClicked = pyqtSignal()         # cycle off -> all -> one
    shuffleToggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._duration = 0
        self._user_scrubbing = False
        self._build()

    def _build(self) -> None:
        self.prev_btn = QPushButton("◄◄ Prev")
        self.play_btn = QPushButton("▶ Play")
        self.next_btn = QPushButton("►► Next")
        # Text flips Play/Pause at runtime; hold the longer width so the bar doesn't jump.
        self.play_btn.setMinimumWidth(self.play_btn.fontMetrics().horizontalAdvance("❚❚ Pause") + 28)

        self.prev_btn.clicked.connect(self.prevClicked)
        self.play_btn.clicked.connect(self.playPauseClicked)
        self.next_btn.clicked.connect(self.nextClicked)

        self.shuffle_btn = QPushButton("🔀 Shuffle")
        self.shuffle_btn.setObjectName("modeBtn")
        self.shuffle_btn.setCheckable(True)
        self.shuffle_btn.setToolTip("Shuffle")
        self.shuffle_btn.toggled.connect(self.shuffleToggled)

        self.repeat_btn = QPushButton("🔁 Repeat")
        self.repeat_btn.setObjectName("modeBtn")
        self.repeat_btn.setCheckable(True)
        self.repeat_btn.setToolTip("Repeat: Off")
        self.repeat_btn.clicked.connect(self.repeatClicked)

        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setFixedWidth(48)
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_label = QLabel("0:00")
        self.total_label.setFixedWidth(48)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self._on_scrub_start)
        self.seek_slider.sliderReleased.connect(self._on_scrub_end)

        self.art_label = QLabel()
        self.art_label.setObjectName("albumArt")
        self.art_label.setFixedSize(ART_SIZE, ART_SIZE)
        self.art_label.setScaledContents(True)
        self.art_label.setVisible(False)

        self.now_label = QLabel("Nothing playing")
        self.now_label.setObjectName("nowPlaying")
        self.now_label.setMinimumWidth(160)

        vol_label = QLabel("🔊")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(110)
        self.volume_slider.valueChanged.connect(self.volumeChanged)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.next_btn)
        layout.addSpacing(4)
        layout.addWidget(self.shuffle_btn)
        layout.addWidget(self.repeat_btn)
        layout.addSpacing(6)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.seek_slider, 1)
        layout.addWidget(self.total_label)
        layout.addSpacing(10)
        layout.addWidget(self.art_label)
        layout.addWidget(self.now_label)
        layout.addSpacing(10)
        layout.addWidget(vol_label)
        layout.addWidget(self.volume_slider)

    # --------------------------------------------------------- scrub state
    def _on_scrub_start(self) -> None:
        self._user_scrubbing = True

    def _on_scrub_end(self) -> None:
        self._user_scrubbing = False
        self.seekRequested.emit(self.seek_slider.value())

    # ------------------------------------------------------------- setters
    def set_duration(self, ms: int) -> None:
        self._duration = ms
        self.seek_slider.setRange(0, ms)
        self.total_label.setText(format_time(ms))

    def set_position(self, ms: int) -> None:
        if not self._user_scrubbing:
            self.seek_slider.setValue(ms)
        self.elapsed_label.setText(format_time(ms))

    def set_playing(self, playing: bool) -> None:
        self.play_btn.setText("❚❚ Pause" if playing else "▶ Play")

    def set_now_playing(self, text: str) -> None:
        self.now_label.setText(text or "Nothing playing")

    def set_repeat_mode(self, mode: str) -> None:
        """mode is 'off', 'all', or 'one'."""
        self.repeat_btn.setText("🔂 Repeat 1" if mode == "one" else "🔁 Repeat")
        self.repeat_btn.setToolTip(f"Repeat: {mode.capitalize()}")
        self.repeat_btn.setChecked(mode != "off")

    def set_shuffle(self, on: bool) -> None:
        self.shuffle_btn.blockSignals(True)
        self.shuffle_btn.setChecked(on)
        self.shuffle_btn.blockSignals(False)

    def set_art(self, image_bytes: bytes | None) -> None:
        """Show embedded cover art next to the now-playing label, or hide it."""
        if not image_bytes:
            self.art_label.clear()
            self.art_label.setVisible(False)
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(image_bytes):
            self.art_label.setPixmap(pixmap)
            self.art_label.setVisible(True)
        else:
            self.art_label.setVisible(False)
