"""Audio alert for events worth walking back to the desk for.

Played in-process through Qt Multimedia (the same backend as the built-in video
player), so .mp3/.wav/.ogg/.flac/.m4a all play without spawning an external
player window. Failures are swallowed — a missing or unplayable sound file must
never take down whatever it was announcing.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMetaObject, QObject, Qt, QThread, QUrl, pyqtSlot
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QApplication

WAV_FILTER = "Audio Files (*.wav *.mp3 *.ogg *.flac *.aac *.m4a *.wma);;All Files (*)"


class _Player(QObject):
    """Lives on the GUI thread; owns every in-flight alert until it finishes."""

    def __init__(self):
        super().__init__()
        self._path = ""
        self._active: list[tuple[QMediaPlayer, QAudioOutput]] = []

    def request(self, path: str):
        self._path = path
        if QThread.currentThread() is self.thread():
            self._start()
        else:
            QMetaObject.invokeMethod(self, "_start", Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _start(self):
        try:
            audio = QAudioOutput()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player.setSource(QUrl.fromLocalFile(self._path))
            entry = (player, audio)
            self._active.append(entry)

            def _done(*_):
                if entry in self._active:
                    self._active.remove(entry)
                    player.deleteLater()
                    audio.deleteLater()

            player.mediaStatusChanged.connect(
                lambda s: _done() if s in (QMediaPlayer.MediaStatus.EndOfMedia,
                                           QMediaPlayer.MediaStatus.InvalidMedia) else None)
            player.errorOccurred.connect(_done)
            player.play()
        except Exception:                     # noqa: BLE001
            pass


_player: _Player | None = None


def play(path: str) -> bool:
    """Fire-and-forget. Returns False when there's nothing playable to try."""
    global _player
    path = (path or "").strip()
    if not path or not Path(path).exists():
        return False
    app = QApplication.instance()
    if app is None:
        return False
    if _player is None:
        _player = _Player()
        _player.moveToThread(app.thread())
    _player.request(path)
    return True
