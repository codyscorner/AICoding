"""Main application window for Music Player.

  * toolbar: Add Folder, Include-subfolders toggle, live search box
  * playlist table (Title/Artist/Album/Time/Size/Format/Path) with header sort,
    drag-to-reorder, and a right-click menu (play/remove/reveal/properties/clear)
  * playback via Player: double-click to play, transport bar, seek, volume,
    now-playing highlight, auto-advance, repeat (off/all/one) and shuffle
  * exact playlist auto-saved/restored across launches; remembers recursive
    toggle / volume / repeat / shuffle
"""

from __future__ import annotations

import os
import random
import subprocess

import settings
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.library import (
    Track,
    format_duration,
    human_size,
    read_album_art,
)
from core.player import Player
from core import playlist as pl
from core.playlist import load_session, save_session
from core.export import ExportWorker, plan_targets
from core.scanner import ScanWorker
from ui.export_dialog import ExportDialog
from ui.playlist_view import PlaylistSidebar, PlaylistTable
from ui.transport_bar import TransportBar

ACCENT = QColor("#5a9ffd")


class NumericItem(QTableWidgetItem):
    """Table cell that sorts by an underlying numeric value while displaying
    a formatted string (e.g. shows "8.1 MB", sorts by raw byte count)."""

    def __init__(self, text: str, value: float):
        super().__init__(text)
        self._value = value

    def __lt__(self, other: object) -> bool:
        if isinstance(other, NumericItem):
            return self._value < other._value
        return super().__lt__(other)  # type: ignore[arg-type]


# Column layout.
(
    COL_INDEX,
    COL_TITLE,
    COL_ARTIST,
    COL_ALBUM,
    COL_TIME,
    COL_SIZE,
    COL_FORMAT,
    COL_PATH,
) = range(8)
HEADERS = ["#", "Title", "Artist", "Album", "Time", "Size", "Format", "Path"]


class MainWindow(QMainWindow):
    def __init__(self, version: str = ""):
        super().__init__()
        self._version = version
        self._tracks: list[Track] = []
        self._playing_path = ""
        self._auto_skips = 0  # consecutive failed tracks auto-skipped
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._scanned_count = 0
        self._repeat_mode = "off"  # off | all | one
        self._current_view: str | None = None  # None = Library, else playlist name
        self._shuffle = False
        self._shuffle_queue: list[str] = []   # upcoming paths
        self._shuffle_history: list[str] = []  # previously played paths
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None

        self.setWindowTitle(f"Music Player  v{version}" if version else "Music Player")
        self.resize(960, 640)

        self.player = Player(self)
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._wire_player()

        # Restore remembered preferences.
        self.recursive_check.setChecked(settings.get_recursive())
        vol = settings.get_volume()
        self.transport.volume_slider.setValue(vol)
        self.player.set_volume(vol)

        self._repeat_mode = settings.get_repeat_mode()
        self.transport.set_repeat_mode(self._repeat_mode)
        self._shuffle = settings.get_shuffle()
        self.transport.set_shuffle(self._shuffle)

        self._restore_session()

    # ------------------------------------------------------------------ UI
    def _build_menu(self) -> None:
        library_menu = self.menuBar().addMenu("&Library")
        library_menu.addAction("Set Library Folder…", self._choose_library_root)
        library_menu.addAction("Rescan Library", self._rescan_library)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.add_btn = QPushButton("Add Folder…")
        self.add_btn.clicked.connect(self._on_add_folder)
        toolbar.addWidget(self.add_btn)

        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setChecked(True)
        toolbar.addWidget(self.recursive_check)

        spacer = QWidget()
        spacer.setSizePolicy(
            spacer.sizePolicy().horizontalPolicy().Expanding,
            spacer.sizePolicy().verticalPolicy().Preferred,
        )
        toolbar.addWidget(spacer)

        toolbar.addWidget(QLabel("Search: "))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by title, artist, album…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(240)
        self.search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_edit)

    def _build_central(self) -> None:
        self.table = PlaylistTable(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._on_row_activated)
        self.table.rowsMoved.connect(self._on_rows_moved)
        self.table.filesDropped.connect(self._on_files_dropped)
        self.table.playPauseRequested.connect(self._on_play_pause)
        self.table.seekRelative.connect(self.player.seek_relative)
        self.table.nextRequested.connect(self._on_next)
        self.table.prevRequested.connect(self._on_prev)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        del_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        del_sc.activated.connect(self._remove_selected)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_INDEX, 48)
        self.table.setColumnWidth(COL_ARTIST, 160)
        self.table.setColumnWidth(COL_ALBUM, 160)
        self.table.setColumnWidth(COL_TIME, 60)
        self.table.setColumnWidth(COL_SIZE, 90)
        self.table.setColumnWidth(COL_FORMAT, 70)

        self.transport = TransportBar()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.table, 1)
        right_layout.addWidget(self.transport)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 710])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Add a folder to begin.")

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        v = QVBoxLayout(panel)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        v.addWidget(QLabel("Playlists"))
        self.playlist_list = PlaylistSidebar()
        self.playlist_list.itemClicked.connect(self._on_playlist_clicked)
        self.playlist_list.tracksDropped.connect(self._add_selected_to_playlist)
        self.playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self._show_sidebar_menu)
        v.addWidget(self.playlist_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        new_btn = QPushButton("＋ New")
        new_btn.setToolTip("New playlist")
        new_btn.clicked.connect(self._new_playlist)
        rename_btn = QPushButton("✎ Rename")
        rename_btn.setToolTip("Rename selected playlist")
        rename_btn.clicked.connect(self._rename_playlist)
        del_btn = QPushButton("🗑 Delete")
        del_btn.setToolTip("Delete selected playlist")
        del_btn.clicked.connect(self._delete_playlist)
        for b in (new_btn, rename_btn, del_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        v.addLayout(buttons)
        return panel

    def _wire_player(self) -> None:
        self.transport.playPauseClicked.connect(self._on_play_pause)
        self.transport.prevClicked.connect(self._on_prev)
        self.transport.nextClicked.connect(self._on_next)
        self.transport.seekRequested.connect(self.player.seek)
        self.transport.volumeChanged.connect(self._on_volume_changed)
        self.transport.repeatClicked.connect(self._cycle_repeat)
        self.transport.shuffleToggled.connect(self._set_shuffle)

        self.player.positionChanged.connect(self.transport.set_position)
        self.player.positionChanged.connect(self._on_progress)
        self.player.durationChanged.connect(self.transport.set_duration)
        self.player.playingChanged.connect(self.transport.set_playing)
        self.player.trackEnded.connect(self._on_track_ended)
        self.player.errorOccurred.connect(self._on_play_error)

    # -------------------------------------------------------------- folders
    def _restore_session(self) -> None:
        """Reload the working Library list saved from the previous session."""
        self._current_view = None
        tracks = load_session()
        if tracks:
            self._add_tracks(tracks)
            self.statusBar().showMessage(
                f"Restored {len(tracks)} track(s) from last session."
            )
        self._refresh_playlist_sidebar()

    def _on_add_folder(self) -> None:
        start_dir = settings.get_last_folder()
        folder = QFileDialog.getExistingDirectory(
            self, "Select a music folder", start_dir
        )
        if not folder:
            return
        # Folders always populate the Library, not a named playlist.
        if self._current_view is not None:
            self._switch_view(None)
        recursive = self.recursive_check.isChecked()
        settings.set_last_folder(folder)
        settings.set_recursive(recursive)
        self._start_scan(folder)

    def _on_files_dropped(self, paths: list[str]) -> None:
        """Files/folders dragged in from Explorer are added to the Library."""
        if not paths:
            return
        if self._current_view is not None:
            self._switch_view(None)  # external drops go into the Library
        self._start_scan(paths)

    # ------------------------------------------------------- library root
    def _choose_library_root(self) -> None:
        start = settings.get_library_root() or settings.get_last_folder()
        folder = QFileDialog.getExistingDirectory(
            self, "Choose your music library folder", start
        )
        if not folder:
            return
        settings.set_library_root(folder)
        self._scan_library_root(folder)

    def _rescan_library(self) -> None:
        root = settings.get_library_root()
        if not root:
            QMessageBox.information(
                self,
                "Rescan Library",
                "No library folder set yet.\nUse Library ▸ Set Library Folder… first.",
            )
            return
        self._scan_library_root(root)

    def _scan_library_root(self, root: str) -> None:
        """Rebuild the Library from every audio file under its root folder."""
        if self._current_view is not None:
            self._switch_view(None)
        # Library root is always scanned recursively, replacing the old contents.
        self._start_scan(root, recursive=True, replace=True)

    # -------------------------------------------------- playlists / sidebar
    def _persist_current(self) -> None:
        """Save the current view back to its source (session or playlist file)."""
        if self._current_view is None:
            save_session(self._tracks)
        else:
            pl.save_playlist(self._current_view, self._tracks)

    def _refresh_playlist_sidebar(self) -> None:
        self.playlist_list.blockSignals(True)
        self.playlist_list.clear()
        library = QListWidgetItem("📚  Library")
        library.setData(Qt.ItemDataRole.UserRole, None)
        self.playlist_list.addItem(library)
        for name in pl.list_playlists():
            item = QListWidgetItem(f"🎵  {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.playlist_list.addItem(item)
        self.playlist_list.blockSignals(False)
        self._select_sidebar_view(self._current_view)

    def _select_sidebar_view(self, view: str | None) -> None:
        for i in range(self.playlist_list.count()):
            item = self.playlist_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == view:
                self.playlist_list.setCurrentRow(i)
                return

    def _on_playlist_clicked(self, item: QListWidgetItem) -> None:
        self._switch_view(item.data(Qt.ItemDataRole.UserRole))

    def _switch_view(self, view: str | None) -> None:
        """Persist the current list, then load Library (None) or a playlist."""
        if view == self._current_view:
            return
        self._persist_current()
        self._current_view = view
        if view is None:
            self._tracks = load_session()
        else:
            self._tracks = pl.load_playlist(view)
        self._shuffle_queue = []
        self._shuffle_history = []
        self._populate_table()
        self._select_sidebar_view(view)
        label = "Library" if view is None else f"playlist “{view}”"
        self.statusBar().showMessage(f"Loaded {label} — {len(self._tracks)} track(s).")

    def _selected_tracks(self) -> list[Track]:
        paths, out = set(), []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), COL_PATH)
            if item:
                paths.add(item.text())
        return [t for t in self._tracks if t.path in paths]

    def _new_playlist(self, tracks: list[Track] | None = None) -> None:
        name, ok = QInputDialog.getText(self, "New playlist", "Playlist name:")
        name = name.strip()
        if not ok or not name:
            return
        if pl.playlist_exists(name):
            QMessageBox.warning(self, "New playlist", f"“{name}” already exists.")
            return
        pl.save_playlist(name, tracks or [])
        self._refresh_playlist_sidebar()
        if tracks:
            self.statusBar().showMessage(
                f"Created “{name}” with {len(tracks)} track(s)."
            )

    def _rename_playlist(self) -> None:
        item = self.playlist_list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not name:
            return
        new, ok = QInputDialog.getText(
            self, "Rename playlist", "New name:", text=name
        )
        new = new.strip()
        if not ok or not new or new == name:
            return
        if not pl.rename_playlist(name, new):
            QMessageBox.warning(self, "Rename", f"Couldn't rename to “{new}”.")
            return
        if self._current_view == name:
            self._current_view = new
        self._refresh_playlist_sidebar()

    def _delete_playlist(self) -> None:
        item = self.playlist_list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not name:
            return
        if QMessageBox.question(
            self, "Delete playlist", f"Delete playlist “{name}”?"
        ) != QMessageBox.StandardButton.Yes:
            return
        pl.delete_playlist(name)
        if self._current_view == name:
            self._current_view = None
            self._tracks = load_session()
            self._populate_table()
        self._refresh_playlist_sidebar()

    def _add_selected_to_playlist(self, name: str) -> None:
        tracks = self._selected_tracks()
        if not tracks:
            return
        added = pl.add_to_playlist(name, tracks)
        self.statusBar().showMessage(
            f"Added {added} track(s) to “{name}”"
            + ("" if added == len(tracks) else f" ({len(tracks) - added} already there)")
        )
        self._refresh_playlist_sidebar()

    def _show_sidebar_menu(self, pos) -> None:
        item = self.playlist_list.itemAt(pos)
        if item is None:
            return
        view = item.data(Qt.ItemDataRole.UserRole)  # None = Library
        menu = QMenu(self)
        menu.addAction("Export…", lambda: self._export_view(view))
        if view is not None:  # named playlist actions
            menu.addSeparator()
            menu.addAction("Rename…", self._rename_playlist)
            menu.addAction("Delete", self._delete_playlist)
        menu.exec(self.playlist_list.viewport().mapToGlobal(pos))

    # -------------------------------------------------------------- export
    def _tracks_for_view(self, view: str | None) -> list[Track]:
        if view == self._current_view:
            return list(self._tracks)  # current in-memory order/edits
        return load_session() if view is None else pl.load_playlist(view)

    def _export_view(self, view: str | None) -> None:
        name = "Library" if view is None else view
        tracks = self._tracks_for_view(view)
        if not tracks:
            QMessageBox.information(self, "Export", f"“{name}” has no tracks to export.")
            return

        dlg = ExportDialog(name, len(tracks), settings.get_last_folder(), self)
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return

        dest = dlg.destination()
        targets = plan_targets(tracks, dest, dlg.preserve())
        m3u_path = None
        if dlg.write_m3u():
            safe = "".join(c for c in name if c not in '<>:"/\\|?*').strip() or "playlist"
            m3u_path = os.path.join(dest, f"{safe}.m3u")

        self._start_export(targets, dlg.overwrite(), m3u_path, tracks, name)

    def _start_export(self, targets, overwrite, m3u_path, tracks, name) -> None:
        total = len(targets)
        self._export_progress = QProgressDialog(
            f"Exporting “{name}”…", "Cancel", 0, total, self
        )
        self._export_progress.setWindowTitle("Exporting")
        self._export_progress.setMinimumDuration(0)
        self._export_progress.setValue(0)

        self._export_thread = QThread(self)
        self._export_worker = ExportWorker(targets, overwrite, m3u_path, tracks)
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_progress.canceled.connect(self._export_worker.cancel)
        self._export_thread.start()

    def _on_export_progress(self, done: int, total: int, name: str) -> None:
        self._export_progress.setMaximum(total)
        self._export_progress.setValue(done)
        if name:
            self._export_progress.setLabelText(f"Copying: {name}")

    def _on_export_finished(self, copied: int, skipped: int, errors: int) -> None:
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait()
        self._export_thread = None
        self._export_worker = None
        self._export_progress.close()
        msg = f"Exported {copied} file(s)."
        if skipped:
            msg += f" Skipped {skipped} existing."
        if errors:
            msg += f" {errors} error(s)."
        self.statusBar().showMessage(msg)
        QMessageBox.information(self, "Export complete", msg)

    # ----------------------------------------------------- background scan
    def _start_scan(
        self, sources, recursive: bool | None = None, replace: bool = False
    ) -> None:
        """Scan folder(s)/file(s) on a worker thread, streaming into the table.

        ``sources`` is a folder path or a list of files/folders. recursive=None
        uses the toolbar checkbox; replace=True clears the list first (used when
        (re)building the Library from its root folder).
        """
        self._stop_scan()  # cancel any in-flight scan first
        if recursive is None:
            recursive = self.recursive_check.isChecked()
        if replace:
            self._tracks = []
            self.table.setRowCount(0)

        label = sources if isinstance(sources, str) else f"{len(sources)} item(s)"
        self.add_btn.setEnabled(False)
        self.table.setSortingEnabled(False)  # append at bottom; sort on finish
        self._scanned_count = 0
        self.statusBar().showMessage(f"Scanning {label}…")

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(sources, recursive)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.batch.connect(self._on_scan_batch)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_thread.start()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._stop_scan()
        if self._export_worker is not None:
            self._export_worker.cancel()
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait()
        super().closeEvent(event)

    def _stop_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.stop()
            # Detach signals so a cancelled scan's queued batch/finished events
            # can't touch the UI (or cancel the scan that replaces it).
            try:
                self._scan_worker.batch.disconnect()
                self._scan_worker.finished.disconnect()
            except TypeError:
                pass
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_worker = None
        self._scan_thread = None

    def _on_scan_batch(self, tracks: list[Track]) -> None:
        existing = {t.path for t in self._tracks}
        new_tracks = [t for t in tracks if t.path not in existing]
        if not new_tracks:
            return
        start = len(self._tracks)
        self._tracks.extend(new_tracks)
        self._append_rows(new_tracks, start)
        self._scanned_count = len(self._tracks)
        self.statusBar().showMessage(f"Scanning… {self._scanned_count} found")

    def _on_scan_finished(self, total: int) -> None:
        self._stop_scan()
        self.add_btn.setEnabled(True)
        self.table.setSortingEnabled(True)
        self.table.sortItems(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self._apply_filter(self.search_edit.text())
        self._mark_playing_row()
        self._update_status_count()
        self._persist_current()

    def _add_tracks(self, tracks: list[Track]) -> None:
        """Synchronous add (used by tests); threaded scans use _on_scan_batch."""
        existing = {t.path for t in self._tracks}
        new_tracks = [t for t in tracks if t.path not in existing]
        self._tracks.extend(new_tracks)
        self._populate_table()

    def _set_row(self, row: int, number: int, track: Track) -> None:
        """Fill one table row with a track's cells."""
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        index_item = NumericItem(str(number), number)
        index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        title_item = QTableWidgetItem(track.display_title)
        artist_item = QTableWidgetItem(track.artist)
        album_item = QTableWidgetItem(track.album)
        time_item = NumericItem(
            format_duration(track.duration_secs), track.duration_secs
        )
        time_item.setTextAlignment(right)
        size_item = NumericItem(human_size(track.size_bytes), track.size_bytes)
        size_item.setTextAlignment(right)
        format_item = QTableWidgetItem(track.ext.upper())
        format_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        path_item = QTableWidgetItem(track.path)

        self.table.setItem(row, COL_INDEX, index_item)
        self.table.setItem(row, COL_TITLE, title_item)
        self.table.setItem(row, COL_ARTIST, artist_item)
        self.table.setItem(row, COL_ALBUM, album_item)
        self.table.setItem(row, COL_TIME, time_item)
        self.table.setItem(row, COL_SIZE, size_item)
        self.table.setItem(row, COL_FORMAT, format_item)
        self.table.setItem(row, COL_PATH, path_item)

    def _append_rows(self, tracks: list[Track], start: int) -> None:
        """Append rows for newly scanned tracks without rebuilding the table."""
        first = self.table.rowCount()
        self.table.setRowCount(first + len(tracks))
        for offset, track in enumerate(tracks):
            self._set_row(first + offset, start + offset + 1, track)

    def _populate_table(self) -> None:
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._tracks))
        for row, track in enumerate(self._tracks):
            self._set_row(row, row + 1, track)

        self.table.setSortingEnabled(was_sorting)
        if was_sorting:
            # Enabling sorting applies the current indicator (defaults to
            # descending); pin a predictable ascending-by-# order.
            self.table.sortItems(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self._apply_filter(self.search_edit.text())
        self._mark_playing_row()
        self._update_status_count()

    # ------------------------------------------------- reorder / edit list
    def _current_table_order(self) -> list[Track]:
        """Tracks in the current visual (row) order of the table."""
        by_path = {t.path: t for t in self._tracks}
        order: list[Track] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_PATH)
            if item and item.text() in by_path:
                order.append(by_path[item.text()])
        return order

    def _on_rows_moved(self, sources: list[int], target: int) -> None:
        order = self._current_table_order()
        if not order:
            return
        moving = [order[i] for i in sources if 0 <= i < len(order)]
        remaining = [t for i, t in enumerate(order) if i not in set(sources)]
        insert_at = target - sum(1 for i in sources if i < target)
        insert_at = max(0, min(insert_at, len(remaining)))
        remaining[insert_at:insert_at] = moving
        self._tracks = remaining
        self._populate_table()  # renumbers # and pins the new manual order
        self._persist_current()

    def _remove_selected(self) -> None:
        if self._current_view is None:
            # The Library mirrors your files; you can't hand-remove from it.
            self.statusBar().showMessage(
                "Library reflects your files on disk — remove from a playlist instead."
            )
            return
        paths = set()
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), COL_PATH)
            if item:
                paths.add(item.text())
        if not paths:
            return
        self._drop_paths(paths)
        self._persist_current()

    def _drop_paths(self, paths: set[str]) -> None:
        self._tracks = [t for t in self._tracks if t.path not in paths]
        self._shuffle_queue = [p for p in self._shuffle_queue if p not in paths]
        self._shuffle_history = [p for p in self._shuffle_history if p not in paths]
        self._populate_table()

    def _clear_playlist(self) -> None:
        if self._current_view is None:
            self.statusBar().showMessage(
                "Library can't be cleared — set/rescan a library folder instead."
            )
            return
        self._tracks = []
        self._shuffle_queue = []
        self._shuffle_history = []
        self._populate_table()
        self._persist_current()

    def _show_context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        menu = QMenu(self)
        if row >= 0:
            # If the clicked row isn't part of the selection, select just it so
            # the actions operate on what was right-clicked.
            selected = {i.row() for i in self.table.selectionModel().selectedRows()}
            if row not in selected:
                self.table.selectRow(row)
            path_item = self.table.item(row, COL_PATH)
            path = path_item.text() if path_item else ""
            menu.addAction("Play", lambda: self._play_row(row))
            menu.addAction("Remove from list", self._remove_selected)

            add_menu = menu.addMenu("Add to playlist")
            add_menu.addAction("New playlist…", lambda: self._new_playlist(self._selected_tracks()))
            names = pl.list_playlists()
            if names:
                add_menu.addSeparator()
            for name in names:
                if name == self._current_view:
                    continue  # already in this one
                add_menu.addAction(name, lambda _=False, n=name: self._add_selected_to_playlist(n))

            menu.addSeparator()
            menu.addAction("Reveal in Explorer", lambda: self._reveal_in_explorer(path))
            menu.addAction("Properties", lambda: self._show_properties(path))
            menu.addSeparator()
        clear = menu.addAction("Clear playlist", self._clear_playlist)
        clear.setEnabled(bool(self._tracks))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _reveal_in_explorer(self, path: str) -> None:
        if path and os.path.exists(path):
            # /select, highlights the file within its folder
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def _show_properties(self, path: str) -> None:
        track = next((t for t in self._tracks if t.path == path), None)
        if track is None:
            return
        lines = [
            f"Title:\t{track.display_title}",
            f"Artist:\t{track.artist or '—'}",
            f"Album:\t{track.album or '—'}",
            f"Duration:\t{format_duration(track.duration_secs) or '—'}",
            f"Size:\t{human_size(track.size_bytes)}",
            f"Format:\t{track.ext.upper()}",
            f"Path:\t{track.path}",
        ]
        QMessageBox.information(self, "Track properties", "\n".join(lines))

    # ------------------------------------------------------------ playback
    def _on_row_activated(self, index) -> None:
        self._play_row(index.row())

    def _play_row(self, row: int) -> None:
        path_item = self.table.item(row, COL_PATH)
        if path_item is None:
            return
        path = path_item.text()
        title_item = self.table.item(row, COL_TITLE)
        title = title_item.text() if title_item else path
        if not os.path.exists(path):
            self._handle_missing_file(path, title)
            return
        self._playing_path = path
        self.player.play_file(path)
        self.transport.set_now_playing(title)
        self.transport.set_art(read_album_art(path))
        self._mark_playing_row()

    def _handle_missing_file(self, path: str, title: str) -> None:
        """A track's file is gone — offer to remove it from the library and every
        playlist that points at the same file."""
        answer = QMessageBox.question(
            self,
            "File not found",
            f"Can't find the file for:\n\n{title}\n{path}\n\n"
            "Remove it from your Library and any playlists that reference it?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        pl.remove_path_everywhere(path)
        self._drop_paths({path})          # update the current view on screen
        self.statusBar().showMessage(f"Removed missing file: {title}")

    def _on_play_pause(self) -> None:
        if not self.player.current_path:
            # Nothing loaded yet — start the first visible row.
            row = self._first_visible_row()
            if row is not None:
                self._play_row(row)
            return
        self.player.toggle_pause()

    def _on_next(self) -> None:
        if self._shuffle:
            self._play_shuffle_next()
            return
        row = self._visible_row_of_playing()
        nxt = self._next_visible_row(row)
        if nxt is None and self._repeat_mode == "all":
            nxt = self._first_visible_row()
        if nxt is not None:
            self._play_row(nxt)

    def _on_prev(self) -> None:
        if self._shuffle:
            self._play_shuffle_prev()
            return
        row = self._visible_row_of_playing()
        prev = self._prev_visible_row(row)
        if prev is None and self._repeat_mode == "all":
            prev = self._last_visible_row()
        if prev is not None:
            self._play_row(prev)

    # ----------------------------------------------------- repeat & shuffle
    def _cycle_repeat(self) -> None:
        order = ["off", "all", "one"]
        self._repeat_mode = order[(order.index(self._repeat_mode) + 1) % 3]
        settings.set_repeat_mode(self._repeat_mode)
        self.transport.set_repeat_mode(self._repeat_mode)

    def _set_shuffle(self, on: bool) -> None:
        self._shuffle = on
        settings.set_shuffle(on)
        if on:
            self._rebuild_shuffle_queue(exclude=self._playing_path)
            self._shuffle_history = []
        else:
            self._shuffle_queue = []
            self._shuffle_history = []

    def _rebuild_shuffle_queue(self, exclude: str | None = None) -> None:
        paths = [p for p in self._visible_paths() if p != exclude]
        random.shuffle(paths)
        self._shuffle_queue = paths

    def _play_shuffle_next(self) -> None:
        if self._playing_path:
            self._shuffle_history.append(self._playing_path)
        if not self._shuffle_queue:
            # Empty queue with a played history means a full cycle finished;
            # stop there unless repeat is on. First use (no history) refills.
            if self._shuffle_history and self._repeat_mode == "off":
                return
            self._rebuild_shuffle_queue(exclude=self._playing_path)
        while self._shuffle_queue:
            path = self._shuffle_queue.pop(0)
            row = self._visible_row_of_path(path)
            if row is not None:
                self._play_row(row)
                return

    def _play_shuffle_prev(self) -> None:
        while self._shuffle_history:
            path = self._shuffle_history.pop()
            row = self._visible_row_of_path(path)
            if row is not None:
                if self._playing_path:
                    # so a following Next returns to where we were
                    self._shuffle_queue.insert(0, self._playing_path)
                self._play_row(row)
                return

    def _play_path(self, path: str) -> None:
        row = self._visible_row_of_path(path)
        if row is not None:
            self._play_row(row)
        else:
            self._playing_path = path
            self.player.play_file(path)

    def _on_volume_changed(self, value: int) -> None:
        self.player.set_volume(value)
        settings.set_volume(value)

    def _on_progress(self, ms: int) -> None:
        # Real playback progress means the current file is fine — reset the
        # bad-file skip guard.
        if ms > 0:
            self._auto_skips = 0

    def _on_track_ended(self) -> None:
        self._auto_skips = 0
        if self._repeat_mode == "one" and self._playing_path:
            self._play_path(self._playing_path)  # replay same track
        else:
            self._on_next()

    def _on_play_error(self, message: str) -> None:
        row = self._visible_row_of_playing()
        title_item = self.table.item(row, COL_TITLE) if row is not None else None
        name = title_item.text() if title_item else "track"

        self._auto_skips += 1
        if self._auto_skips > self.table.rowCount():
            self.player.stop()
            self.statusBar().showMessage("Stopped — multiple files could not be played.")
            return

        nxt = self._next_visible_row(row)
        if nxt is not None:
            self.statusBar().showMessage(f"Can't play “{name}” — skipping.")
            self._play_row(nxt)
        else:
            self.player.stop()
            self.statusBar().showMessage(f"Can't play “{name}”. End of list.")

    # ----------------------------------------------- row navigation helpers
    def _first_visible_row(self) -> int | None:
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                return row
        return None

    def _last_visible_row(self) -> int | None:
        for row in range(self.table.rowCount() - 1, -1, -1):
            if not self.table.isRowHidden(row):
                return row
        return None

    def _visible_row_of_playing(self) -> int | None:
        return self._visible_row_of_path(self._playing_path)

    def _visible_row_of_path(self, path: str) -> int | None:
        if not path:
            return None
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, COL_PATH)
            if item and item.text() == path:
                return row
        return None

    def _visible_paths(self) -> list[str]:
        paths = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, COL_PATH)
            if item:
                paths.append(item.text())
        return paths

    def _next_visible_row(self, row: int | None) -> int | None:
        start = 0 if row is None else row + 1
        for r in range(start, self.table.rowCount()):
            if not self.table.isRowHidden(r):
                return r
        return None

    def _prev_visible_row(self, row: int | None) -> int | None:
        if row is None:
            return self._first_visible_row()
        for r in range(row - 1, -1, -1):
            if not self.table.isRowHidden(r):
                return r
        return None

    def _mark_playing_row(self) -> None:
        """Show a ▶ marker and accent the currently playing row."""
        playing_row = self._visible_row_of_playing()
        for row in range(self.table.rowCount()):
            index_item = self.table.item(row, COL_INDEX)
            title_item = self.table.item(row, COL_TITLE)
            if index_item is None or title_item is None:
                continue
            is_playing = row == playing_row
            index_item.setText("▶" if is_playing else str(int(index_item._value)))
            font = title_item.font()
            font.setBold(is_playing)
            title_item.setFont(font)
            if is_playing:
                title_item.setForeground(ACCENT)
            else:
                # Clear the role so the title inherits the theme's white text
                # (an invalid QColor() would render as black/unreadable).
                title_item.setData(Qt.ItemDataRole.ForegroundRole, None)

    # --------------------------------------------------------------- filter
    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible = 0
        cols = (COL_TITLE, COL_ARTIST, COL_ALBUM, COL_PATH)
        for row in range(self.table.rowCount()):
            parts = []
            for col in cols:
                item = self.table.item(row, col)
                if item:
                    parts.append(item.text())
            haystack = " ".join(parts).lower()
            match = needle in haystack
            self.table.setRowHidden(row, not match)
            if match:
                visible += 1
        if needle:
            self.statusBar().showMessage(
                f"{visible} of {len(self._tracks)} track(s) match “{text}”"
            )
        else:
            self._update_status_count()

    def _update_status_count(self) -> None:
        count = len(self._tracks)
        if count:
            self.statusBar().showMessage(f"{count} track(s) in playlist.")
        else:
            self.statusBar().showMessage("Add a folder to begin.")
