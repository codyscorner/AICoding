from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider
from PySide6.QtCore import Qt, QUrl, QEvent, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget


def _ms_to_str(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


class VideoPlayerPanel(QWidget):
    navigateRequested = Signal(int)  # +1 = next, -1 = previous

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Video widget ---
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: #000;")
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.installEventFilter(self)
        layout.addWidget(self.video_widget)

        # --- Seek slider ---
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setFixedHeight(16)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #444;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3d6aff;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #fff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self._seeking = False
        layout.addWidget(self.seek_slider)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 4)
        toolbar.setSpacing(6)

        self.play_pause_btn = QPushButton("▶ Play")
        # Text flips Play/Pause at runtime; hold the longer width so the bar doesn't jump.
        self.play_pause_btn.setMinimumWidth(self.play_pause_btn.fontMetrics().horizontalAdvance("⏸ Pause") + 28)
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        toolbar.addWidget(self.play_pause_btn)

        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.clicked.connect(self._stop)
        toolbar.addWidget(self.stop_btn)

        self.fullscreen_btn = QPushButton("⛶ Full screen")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        toolbar.addWidget(self.fullscreen_btn)

        toolbar.addStretch()

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("color: #ccc; font-size: 12px;")
        toolbar.addWidget(self.time_label)

        toolbar.addSpacing(12)

        # Volume icon + slider
        vol_label = QLabel("🔊")
        vol_label.setStyleSheet("color: #ccc; font-size: 12px;")
        toolbar.addWidget(vol_label)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #444; height: 4px; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #888; height: 4px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #ccc; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
        """)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        toolbar.addWidget(self.volume_slider)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setStyleSheet("background-color: #1e1e1e;")
        layout.addWidget(toolbar_widget)

        # --- Error label ---
        self.error_label = QLabel()
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setStyleSheet("color: #f88; padding: 4px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # --- Player ---
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(self.volume_slider.value() / 100.0)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.errorOccurred.connect(self._on_error)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)

        self._duration_ms = 0
        self.current_path: str | None = None

        # --- Keyboard shortcuts ---
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play_pause)
        QShortcut(QKeySequence(Qt.Key_F), self, self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._seek_forward)
        QShortcut(QKeySequence(Qt.Key_Left), self, self._seek_backward)
        QShortcut(QKeySequence(Qt.Key_M), self, self._toggle_mute)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def release(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.current_path = None
        self._duration_ms = 0
        self.seek_slider.setRange(0, 0)
        self.time_label.setText("0:00 / 0:00")

    def load_video(self, path: str) -> None:
        self.error_label.setVisible(False)
        self.player.stop()
        self.current_path = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def toggle_play_pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_fullscreen(self) -> None:
        self.video_widget.setFullScreen(not self.video_widget.isFullScreen())

    def eventFilter(self, obj, event) -> bool:
        if obj is self.video_widget and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Escape, Qt.Key_F):
                if self.video_widget.isFullScreen():
                    self.video_widget.setFullScreen(False)
                    return True
            if key == Qt.Key_Space:
                self.toggle_play_pause()
                return True
            if key == Qt.Key_Down:
                self.navigateRequested.emit(1)
                return True
            if key == Qt.Key_Up:
                self.navigateRequested.emit(-1)
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Seek slider
    # ------------------------------------------------------------------

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_released(self) -> None:
        self._seeking = False
        self.player.setPosition(self.seek_slider.value())

    def _on_seek_moved(self, value: int) -> None:
        self.time_label.setText(f"{_ms_to_str(value)} / {_ms_to_str(self._duration_ms)}")

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def _on_volume_changed(self, value: int) -> None:
        self.audio_output.setVolume(value / 100.0)

    def _toggle_mute(self) -> None:
        self.audio_output.setMuted(not self.audio_output.isMuted())

    # ------------------------------------------------------------------
    # Seek shortcuts (±10 s)
    # ------------------------------------------------------------------

    def _seek_forward(self) -> None:
        self.player.setPosition(min(self._duration_ms, self.player.position() + 10_000))

    def _seek_backward(self) -> None:
        self.player.setPosition(max(0, self.player.position() - 10_000))

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _stop(self) -> None:
        self.player.stop()

    def _on_playback_state_changed(self, state) -> None:
        self.play_pause_btn.setText("⏸ Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ Play")

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self.seek_slider.setValue(position_ms)
        self.time_label.setText(f"{_ms_to_str(position_ms)} / {_ms_to_str(self._duration_ms)}")

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._duration_ms = duration_ms
        self.seek_slider.setRange(0, duration_ms)
        self.time_label.setText(f"0:00 / {_ms_to_str(duration_ms)}")

    def _on_error(self, error, error_string: str) -> None:
        self.error_label.setText(f"Cannot play file: {error_string}")
        self.error_label.setVisible(True)
