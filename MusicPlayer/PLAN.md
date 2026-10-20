# Music Player — Plan

A desktop music player: point it at a folder, scan for audio files (optionally
recursing into subfolders), and load them into a playlist you can reorder, sort,
search, and play from.

## Decisions
- **Framework:** PyQt6 (desktop, Windows), packaged with PyInstaller
- **Audio engine:** Qt Multimedia (`QMediaPlayer` + `QAudioOutput`) — no external
  DLLs, uses Windows Media Foundation, bundles cleanly into the EXE
- **Formats:** MP3, WAV, FLAC, M4A/AAC, OGG
- **Metadata:** tinytag (or mutagen) to read tags + duration without playing
- **Persistence:** full — named playlists, last-session restore, `.m3u`
  import/export, remembered folder/volume/window via `QSettings`
- **Theme:** dark-blue color scheme (dark UI, blue accents)
- **Build output:** `P:\Apps\AICoded\Music Player\`

## UI layout (single window)
```
┌─────────────────────────────────────────────┐
│ [Add Folder] [☑ Include subfolders] [Search] │  toolbar
├─────────────────────────────────────────────┤
│  #  Title   Artist  Album  Time  Size  Fmt   │  sortable playlist
│  1  Song A  ...     ...    3:42  8.1MB mp3    │  (drag to reorder)
│  ...                                          │
├─────────────────────────────────────────────┤
│ ◄◄ ▶/❚❚ ►►  [──●──seek──] 1:12/3:42           │  transport
│ 🔊[vol] ⟲repeat ⤨shuffle   Now: Song A        │
└─────────────────────────────────────────────┘
```

## Features

### Must-have (spec)
- Add folder; optional recursive subfolder scan
- Sortable columns: # / Title / Artist / Album / Duration / Size / Format / Path
- Drag-and-drop row reorder
- Click header to sort by any column (name, length, size, ...)
- Play / pause / stop / next / previous, seek bar, volume
- Double-click row to play

### Good-player additions
- Metadata + album art from tags, filename fallback
- Repeat (off/all/one) and shuffle
- Live search/filter box
- Save & load playlists (`.m3u` + JSON for order/state)
- Remember last folder, volume, window size (QSettings)
- Keyboard shortcuts (Space = play/pause, arrows = seek/skip)
- Right-click menu: play, remove, reveal in Explorer, properties
- Status bar: track count + total duration
- Drag files/folders from Explorer into the window

### Later / optional
- Now-playing highlight + auto-scroll
- Column show/hide, remembered widths
- Global media-key support
- Ratings/favorites, equalizer, waveform/spectrum visualizer

## Project structure
```
MusicPlayer/
├── main.py                 # entry, __version__, bootstrap
├── ui/
│   ├── main_window.py      # window, toolbar, transport, wiring
│   ├── playlist_view.py    # sortable/drag-reorder table model+view
│   └── transport_bar.py    # play/seek/volume controls
├── core/
│   ├── player.py           # QMediaPlayer wrapper
│   ├── library.py          # folder scan + metadata read
│   └── playlist.py         # model, save/load .m3u + JSON
├── settings.py             # QSettings helpers
├── PROJECT_SUMMARY.md
├── CHANGELOG.md
├── PLAN.md
└── requirements.txt
```

## Build phases
1. **Skeleton** — window, folder picker, recursive scan, table with name/size/format
2. **Playback** — QMediaPlayer transport, seek, volume, double-click, now-playing highlight
3. **Metadata** — tinytag scan for title/artist/album/duration + art; sortable columns
4. **Playlist power** — drag reorder, search filter, right-click menu, repeat/shuffle
5. **Persistence** — save/load playlists, `.m3u` import/export, session + settings restore
6. **Polish & build** — shortcuts, Explorer drag-in, version bump, PyInstaller EXE

## Conventions (standing rules)
- Keep `CHANGELOG.md` + `PROJECT_SUMMARY.md` updated on every change
- Bump patch version in `main.py` + summary + changelog before each EXE build
- Always stage MD files; never gitignore them
