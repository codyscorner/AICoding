# Changelog

## v1.1.1
- New navy-blue app icon (royal-blue clipboard with a green tick) to match the navy theme; the old one was violet. Regenerated with IconMaker, still unique among the project icons.

## v1.1.0
- **Navy blue theme** replaces the purple one. This palette is now the default for new apps (see `COLORS` in `todo.py`).
- **Text fixed:** task text no longer sits in dark boxes (a blanket `QWidget` background rule was painting every label), uses Segoe UI, and now takes all the spare width so it wraps/expands as the window is resized.
- **Checkbox frame removed:** the checkbox is a bare ☐ / ☑ glyph (green when done).
- **Closing comment:** completing a task opens a small dialog for an optional comment (Ctrl+Enter or Complete; empty is fine; Cancel leaves the task open). The comment, completion time and creation time show on the card. Re-completing pre-fills the earlier comment.
- **Nothing is lost — History:** "Clear Completed" and the ✕ button now move tasks to History (new Active/History switch, with a count) instead of deleting them. In History: ↩ restores a task, ✕ is "Delete forever" (confirmed). Cleared/deleted time is recorded.
- **Scrolling list:** cards keep their size however many tasks there are (previously ~12+ tasks squashed to unreadable slivers).
- **Safer saves:** `todos.json` is written atomically (temp file + replace); a corrupt file is copied to `todos.json.bak-<time>` before starting empty; tasks without an `id` are repaired on load. Existing `todos.json` files load unchanged — new fields are additive.

## v1.0.1
- Added an app icon (`app_icon.ico`, generated with IconMaker: violet clipboard with ticks on navy; 16/32/48/256 px).
- Icon now shows on the taskbar (own `AppUserModelID`, so Windows no longer groups it under python.exe), the title bar, and every dialog (app-level icon).
- Icon is embedded in `TodoList.exe` (Explorer / desktop) and the build script sets the desktop shortcut's `IconLocation` explicitly.
- Bundled icon is now found in PyInstaller's unpack folder when frozen; it was previously looked up next to the EXE, where it never was.

## v1.0.0
- Initial release.
