"""Audio alert for events worth walking back to the desk for.

Played in-process through Qt Multimedia (the same backend as the built-in video
player), so .mp3/.wav/.ogg/.flac/.m4a all play without spawning an external
player window. Failures are swallowed — a missing or unplayable sound file must
never take down whatever it was announcing.

The sound exists to call you back from another room; once you are at the desk
it has done its job. So while an alert is playing, any key press or mouse
click in any of the app's windows stops it at once (the key/click still does
whatever it normally does). Qt only sees input while the app has focus, so
from another program the first click on this app is what silences it.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QMetaObject, QObject, Qt, QThread, QUrl, pyqtSlot
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QApplication

WAV_FILTER = "Audio Files (*.wav *.mp3 *.ogg *.flac *.aac *.m4a *.wma);;All Files (*)"


class _Player(QObject):
    """Lives on the GUI thread; owns every in-flight alert until it finishes."""

    _STOP_EVENTS = (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress)

    def __init__(self):
        super().__init__()
        self._path = ""
        self._active: list[tuple[QMediaPlayer, QAudioOutput]] = []
        self._filtering = False

    # ---- any key / click while playing stops every alert ---------------
    def _watch(self, on: bool):
        app = QApplication.instance()
        if app is None or on == self._filtering:
            return
        if on:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._filtering = on

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if event.type() in self._STOP_EVENTS and self._active:
            self.stop_all()
        return False                      # never swallow the key or click

    @pyqtSlot()
    def stop_all(self):
        for player, audio in list(self._active):
            try:
                player.stop()
            except Exception:             # noqa: BLE001
                pass
            self._active.remove((player, audio))
            player.deleteLater()
            audio.deleteLater()
        self._watch(False)

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
                if not self._active:
                    self._watch(False)

            player.mediaStatusChanged.connect(
                lambda s: _done() if s in (QMediaPlayer.MediaStatus.EndOfMedia,
                                           QMediaPlayer.MediaStatus.InvalidMedia) else None)
            player.errorOccurred.connect(_done)
            player.play()
            self._watch(True)
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


def stop() -> None:
    """Silence any alert that is still playing (safe to call from any thread)."""
    if _player is None:
        return
    if QThread.currentThread() is _player.thread():
        _player.stop_all()
    else:
        QMetaObject.invokeMethod(_player, "stop_all", Qt.ConnectionType.QueuedConnection)
