# TodoList

A simple desktop todo list with a navy-blue dark theme, built with Python and PyQt6.

## Features

- **Add tasks** — type and press Enter (or click Add), with Low / Medium / High priority
- **Complete with a closing comment** — click the checkbox; an optional comment dialog appears (Ctrl+Enter to confirm, Cancel keeps the task open)
- **Edit a task** — pencil button opens a text editor
- **History, nothing lost** — "Clear Completed" and the ✕ button move tasks to the History view instead of deleting them; restore with ↩ or remove for good with "Delete forever"
- **Progress counter** — "N of M completed", plus an "All done" state
- **Resizable** — task text wraps and expands with the window; long lists scroll
- **Persistence** — tasks save to `todos.json` next to the script/EXE (atomic writes; a corrupt file is backed up, not overwritten)
- Newest tasks appear at the top of the list

## Requirements

```
Python 3.x
PyQt6
```

```bash
pip install PyQt6
```

## Usage

```bash
python todo.py
```

Data is stored in `TodoList/todos.json` (or next to the EXE when frozen).

## Building an EXE

```bat
build_todolist.bat
```

Produces `TodoList.exe`, deploys it to `P:\Apps\VibeCoded\TodoList\`, and updates the desktop shortcut (with the app icon).

`app_icon.ico` must sit next to `todo.py`; it is embedded in the EXE and bundled for the window/taskbar icon. Regenerate it with `IconMaker/make_icons.py`.

## Recent Changes

- **v1.1.0** — Navy blue theme (the default palette for new apps), text no longer in dark boxes and expands with the window, frameless checkbox, optional closing comment on completion, History view (nothing is ever deleted by accident), scrolling list, atomic saves. See [CHANGELOG.md](CHANGELOG.md).
- **v1.0.1** — App icon on the taskbar, title bar, dialogs, EXE and desktop shortcut.
- **v1.0.0** — Initial release.
