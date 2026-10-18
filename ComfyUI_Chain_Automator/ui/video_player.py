from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, QEvent, QTimer, QThread, QByteArray, QBuffer, QIODevice, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

from ui.styles import COLORS


def _ms_to_str(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


# Videos are read fully into RAM before they play. Streaming an MP4 straight
# off disk makes the decoder seek between the index and the audio/video chunks;
# on a hard drive (or a just-written file still being scanned) those seeks make
# the first play skip and pause. Reading it sequentially once, on a worker
# thread, then playing from memory removes that. Past this size we skip the
# preload and stream from the file as before.
PRELOAD_MAX_BYTES = 1024 * 1024 * 1024
_LIVE_LOADERS: set = set()   # keeps a running loader alive if its dialog closes


class _FileLoader(QThread):
    loaded = pyqtSignal(str, QByteArray)
    failed = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        try:
            if Path(self._path).stat().st_size > PRELOAD_MAX_BYTES:
                raise OSError("too large to preload")
            data = Path(self._path).read_bytes()
        except OSError:
            self.failed.emit(self._path)
            return
        self.loaded.emit(self._path, QByteArray(data))


class VideoPlayerDialog(QDialog):
    def __init__(self, video_path: str, parent=None, playlist: list[str] = None,
                 auto_close: bool = False):
        super().__init__(parent)
        # auto_close: shut the window when the last video finishes (Library
        # playback) instead of sitting on the final frame until dismissed.
        self._auto_close = auto_close
        self._playlist = playlist if playlist else [video_path]
        self._playlist_index = 0 if not playlist else playlist.index(video_path) if video_path in playlist else 0

        self.setMinimumSize(900, 560)
        self.resize(1000, 620)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(f"""
            QDialog, QWidget {{
                background-color: #000000;
                color: {COLORS['fg_primary']};
                font-family: "Segoe UI";
            }}
            QPushButton {{
                background-color: {COLORS['accent']};
                color: white;
                font-weight: normal;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 10pt;
            }}
            QPushButton:hover {{ background-color: {COLORS['accent_hover']}; }}
            QPushButton:disabled {{ background-color: {COLORS['bg_light']}; color: {COLORS['fg_secondary']}; }}
            QSlider::groove:horizontal {{
                background: {COLORS['bg_light']};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['accent_hover']};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLORS['accent']};
                border-radius: 2px;
            }}
            QLabel {{ background: transparent; color: {COLORS['fg_secondary']}; font-size: 9pt; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video surface
        self._video_widget = QVideoWidget()
        self._video_widget.setStyleSheet("background-color: #000;")
        self._video_widget.installEventFilter(self)
        layout.addWidget(self._video_widget, stretch=1)

        # Seek bar
        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.setContentsMargins(8, 0, 8, 0)
        self._seek.sliderMoved.connect(self._on_seek)
        layout.addWidget(self._seek)

        # Toolbar
        toolbar_widget = QWidget()
        toolbar_widget.setStyleSheet(f"background-color: {COLORS['bg_medium']};")
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(10, 6, 10, 6)
        toolbar.setSpacing(8)

        self._play_btn = QPushButton("⏸ Pause")
        # Text flips Pause/Play at runtime; hold the longer width so the bar doesn't jump.
        self._play_btn.setMinimumWidth(self._play_btn.fontMetrics().horizontalAdvance("⏸ Pause") + 28)
        self._play_btn.clicked.connect(self._toggle_play)
        toolbar.addWidget(self._play_btn)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._stop)
        toolbar.addWidget(self._stop_btn)

        self._fullscreen_btn = QPushButton("⛶ Full screen")
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        toolbar.addWidget(self._fullscreen_btn)

        # Playlist nav (only shown when playlist has multiple items)
        self._prev_btn = QPushButton("⏮ Prev")
        self._prev_btn.clicked.connect(self._prev)
        toolbar.addWidget(self._prev_btn)

        self._next_btn = QPushButton("⏭ Next")
        self._next_btn.clicked.connect(self._next)
        toolbar.addWidget(self._next_btn)

        if len(self._playlist) <= 1:
            self._prev_btn.setVisible(False)
            self._next_btn.setVisible(False)

        toolbar.addStretch()

        self._track_label = QLabel("")
        toolbar.addWidget(self._track_label)

        self._time_label = QLabel("0:00 / 0:00")
        toolbar.addWidget(self._time_label)

        toolbar.addStretch()

        close_btn = QPushButton("✕ Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.close)
        toolbar.addWidget(close_btn)

        layout.addWidget(toolbar_widget)

        # Player
        self._audio = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video_widget)
        self._player.errorOccurred.connect(self._on_error)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._duration_ms = 0

        # Keyboard shortcuts
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_F), self, self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self._prev)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self._next)

        self._cache: dict[str, QByteArray] = {}
        self._loading: dict[str, _FileLoader] = {}
        self._direct: set[str] = set()   # paths that must stream from the file
        self._buffer = None
        self._current_path = None
        self._started = False
        self._load_current()

    def _load_current(self):
        path = self._playlist[self._playlist_index]
        self._current_path = path
        self._started = False
        self._player.stop()
        n = len(self._playlist)
        if n > 1:
            self._track_label.setText(f"{self._playlist_index + 1}/{n}  ")
            self.setWindowTitle(f"{self._playlist_index + 1}/{n} — {Path(path).name}")
        else:
            self._track_label.setText("")
            self.setWindowTitle(Path(path).name)
        if path in self._cache or path in self._direct:
            self._start_playback(path)
        else:
            self._time_label.setText("Loading…")
            self._request_load(path)
        self._prev_btn.setEnabled(self._playlist_index > 0)
        self._next_btn.setEnabled(self._playlist_index < n - 1)

    # ---- preload: read the file into RAM, then play from the buffer -------

    def _request_load(self, path: str):
        if path in self._cache or path in self._loading or path in self._direct:
            return
        loader = _FileLoader(path)
        self._loading[path] = loader
        _LIVE_LOADERS.add(loader)
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_load_failed)
        loader.finished.connect(lambda l=loader: _LIVE_LOADERS.discard(l))
        loader.start()

    def _on_loaded(self, path: str, data: QByteArray):
        self._loading.pop(path, None)
        self._cache[path] = data
        if path == self._current_path and not self._started:
            self._start_playback(path)

    def _on_load_failed(self, path: str):
        # Unreadable or huge: fall back to streaming from the file.
        self._loading.pop(path, None)
        self._direct.add(path)
        if path == self._current_path and not self._started:
            self._start_playback(path)

    def _start_playback(self, path: str):
        self._started = True
        url = QUrl.fromLocalFile(path)
        data = self._cache.get(path)
        old = self._buffer
        if data is not None:
            buf = QBuffer(self)
            buf.setData(data)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            self._player.setSourceDevice(buf, url)
            self._buffer = buf
        else:
            self._player.setSource(url)
            self._buffer = None
        if old is not None:
            old.deleteLater()
        self._player.play()
        # Keep only this clip and the next in memory.
        nxt = self._next_path()
        for k in [k for k in self._cache if k not in (path, nxt)]:
            del self._cache[k]
        if nxt:
            self._request_load(nxt)

    def _next_path(self):
        i = self._playlist_index + 1
        return self._playlist[i] if i < len(self._playlist) else None

    def _prev(self):
        if self._playlist_index > 0:
            self._playlist_index -= 1
            self._load_current()

    def _next(self):
        if self._playlist_index < len(self._playlist) - 1:
            self._playlist_index += 1
            self._load_current()

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _stop(self):
        self._player.stop()

    def _toggle_fullscreen(self):
        self._video_widget.setFullScreen(not self._video_widget.isFullScreen())

    def _on_seek(self, position):
        self._player.setPosition(position)

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._play_btn.setText("⏸ Pause")
        else:
            self._play_btn.setText("▶ Play")

    def _on_position_changed(self, ms: int):
        self._seek.setValue(ms)
        self._time_label.setText(f"{_ms_to_str(ms)} / {_ms_to_str(self._duration_ms)}")

    def _on_duration_changed(self, ms: int):
        self._duration_ms = ms
        self._seek.setRange(0, ms)
        self._time_label.setText(f"0:00 / {_ms_to_str(ms)}")

    def _on_media_status(self, status: QMediaPlayer.MediaStatus):
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._playlist_index < len(self._playlist) - 1:
            self._playlist_index += 1
            QTimer.singleShot(0, self._load_current)
        elif self._auto_close:
            QTimer.singleShot(0, self.close)

    def _on_error(self, error, error_string: str):
        self._time_label.setText(f"Error: {error_string}")

    def eventFilter(self, obj, event):
        if obj is self._video_widget and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_F):
                if self._video_widget.isFullScreen():
                    self._video_widget.setFullScreen(False)
                    return True
            if key == Qt.Key.Key_Space:
                self._toggle_play()
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self._player.stop()
        self._player.setSource(QUrl())   # drop the in-memory buffer's hold
        self._cache.clear()
        self._buffer = None
        event.accept()
