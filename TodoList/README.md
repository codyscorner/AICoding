# TodoList

A simple desktop todo list with a dark aqua-purple theme, built with Python and PyQt6.

## Features

- **Add tasks** — type and press Enter (or click Add), with Low / Medium / High priority
- **Toggle complete** — click the checkbox on a task row
- **Edit a task** — pencil button opens an inline text editor
- **Delete a task** — X button on the row
- **Clear Completed** — removes all finished tasks (with a confirm dialog)
- **Progress counter** — shows "N of M completed" up top, plus an "All done" state
- **Persistence** — tasks save to `todos.json` next to the script/EXE, so your list survives restarts
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

- **v1.0.1** — App icon on the taskbar, title bar, dialogs, EXE and desktop shortcut. Full history in [CHANGELOG.md](CHANGELOG.md).
- **v1.0.0** — Initial release.
