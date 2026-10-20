# Music Player — Project Summary

**Version:** 1.0.0
**Stack:** PyQt6 (UI + Qt Multimedia audio), PyInstaller for packaging
**Build output:** `P:\Apps\AICoded\Music Player\`

## What it is
A desktop music player: point it at a folder, scan for audio files (optionally
recursing into subfolders), and load them into a sortable, drag-reorderable
playlist to play. Dark-blue themed.

## Decisions
- Audio engine: Qt Multimedia (`QMediaPlayer` / `QAudioOutput`) — no external DLLs
- Formats: MP3, WAV, FLAC, M4A/AAC, OGG
- Metadata: tinytag/mutagen (Phase 3)
- Persistence: QSettings + `.m3u`/JSON playlists (Phase 5)
- Theme: dark blue (dark bg, blue accents)

## Structure
```
MusicPlayer/
├── main.py            # entry, __version__, theme apply
├── ui/
│   ├── main_window.py  # window, toolbar, table, playback, menu, reorder
│   ├── playlist_view.py# PlaylistTable (reorder) + PlaylistSidebar (drop target)
│   ├── transport_bar.py# play/seek/volume/repeat/shuffle + album-art thumb
│   └── theme.py        # dark-blue Qt stylesheet
├── core/
│   ├── library.py      # scan/iter, Track model, tag + album-art reading
│   ├── scanner.py      # ScanWorker (threaded, batched folder scan)
│   ├── playlist.py     # session + named-playlist save/load/rename/delete
│   ├── export.py       # ExportWorker + plan_targets + .m3u writer
│   └── player.py       # QMediaPlayer wrapper
├── assets/             # icon.png + icon.ico (window / EXE icon)
├── settings.py         # QSettings: last folder / recursive / volume
└── requirements.txt
```

## Build phases
1. **Skeleton** ✅ — window, folder picker, recursive scan, table (name/size/format)
2. **Playback** ✅ — QMediaPlayer transport, seek, volume, double-click, now-playing,
   auto-advance; remembers last folder/volume
3. **Metadata** ✅ — tinytag tags (title/artist/album/duration) + album art;
   Title/Artist/Album/Time columns; background threaded scanning
4. **Playlist power** ✅ — drag reorder, right-click menu, repeat/shuffle
5. Persistence — save/load playlists, `.m3u` import/export, session + settings
6. **Polish & build** ✅ — shortcuts, Explorer drag-in, PyInstaller EXE (1.0.0)

## Status
**v1.0.0 — feature complete and shipped.** All 6 phases done, plus Library root,
named playlists, drag-to-playlist, removal rules, missing-file cleanup, app icon,
export-to-folder (+.m3u), keyboard shortcuts, and Explorer drag-in. Built with
PyInstaller and deployed to `P:\Apps\AICoded\Music Player\`.

Build: `python -m PyInstaller --noconfirm --clean --windowed --name "Music Player"
--icon assets/icon.ico --add-data "assets;assets" main.py`, then robocopy
`dist\Music Player` → `P:\Apps\AICoded\Music Player`.
