# File Rename Mover

A PySide6 (Qt6) desktop app that batch-renames files with sequential numbering and moves them into an organized destination tree, with a dry-run preview, templates, and a dark red theme.

**Current version: 3.5.1**

## Features

- **Sequential renaming** — `Base Name_000001.ext`; the counter continues from files already in the destination
- **Extension dropdown from the source folder** — pick a source folder and the Extension box lists every extension actually in it, most common first, file counts on hover (still editable)
- **Base Name folder** — optional `dest\[Base Name]\year\month\day` layout; any date organization is created inside the Base Name folder
- **Folder organization** — flat, `YYYY`, `YYYY\MM`, `YYYY\MM\DD`, `YYYY-MM-DD`, or `YYYY-MM`, driven by each file's modified date
- **Rename patterns** — numbering, datetime (six formats, optional counter), prefix (keep original names), or custom with `{counter}`, `{date}`, `{time}`, `{datetime}`, `{year}`, `{month}`, `{day}`, `{original}`
- **Sorting** — by name, date modified, date created, or size; ascending or descending
- **Preview (dry run)** — lists every planned move as `original → [Base Name]\yyyy\mm\dd\new_name` without touching a file
- **Threaded operation** — progress bar, per-file status, Cancel button; UI stays responsive
- **Safe moves** — copy, verify, then delete; optional SHA-256 hash verification in Settings; never overwrites an existing file
- **Templates** — save, load, edit, duplicate, and manage named configurations; last template is remembered
- **Drag-and-drop** — drop a folder from Explorer onto the Source or Destination field
- **Two-column form** — Extension | Base Name, Sort by | Order, Rename Pattern | Folder Organization; the Status box fills the remaining height and fits a 1000×870 window
- **Portable** — single-file EXE; settings and templates are stored next to it

## Screenshot layout

```
Templates          [dropdown]                 [Load] [Save] [Manage]
Source Folder      [path                                       ] [...]
Destination Folder [path                                       ] [...]
Extension          [.mp4 ▾]        Base Name   [Make out in Bedroom]
                   Example: Make out in Bedroom_000001.mp4
Sorting Options    Sort by [name ▾]            Order [asc ▾]
Rename Pattern     Pattern Type [numbering ▾]  Folder Organization  Organize into [year_month_day ▾]
                                               [x] Folder named after Base Name
                                               Example: dest_folder\Make out in Bedroom\2025\11\27\
[Preview] [Move and Rename] [Cancel] [Settings]
Status             (fills the rest of the window)
```

## Requirements

- Windows 10/11
- Python 3.10+ with PySide6 (`pip install PySide6`)
- PyInstaller for building the EXE (`pip install pyinstaller`)

## Running from Source

```
python main.py
```

or double-click `File Rename Mover.bat`.

## Building the EXE

From the project folder, using the repo's `.venv` (it has PySide6 and PyInstaller):

```
..\.venv\Scripts\pyinstaller.exe --noconfirm --clean FileRenameMover.spec
```

The EXE lands in `dist\FileRenameMover.exe`. Bump `VERSION` in `main.py`, `CHANGELOG.md`, and this README before every build. Built EXEs are deployed to `P:\Apps\AICoded\File Rename Mover\`.

## Files next to the EXE

| File | Purpose |
|------|---------|
| `Filemove_config.json` | Last-used folders, extension, base name, pattern, sorting, folder organization, Base Name folder flag, hash verification |
| `Filemove_templates.json` | Saved templates |

Both are created on first run.

## Project layout

```
File Rename Mover/
├── main.py                        # Entry point, VERSION
├── config.py                      # ConfigManager (JSON next to the EXE)
├── templates.py                   # TemplateManager
├── file_operations.py             # FileValidator, FileScanner, FileRenamer
├── rename_patterns.py             # Numbering / DateTime / Prefix / Custom patterns
├── sorting.py                     # FileSorter
├── folder_organization.py         # FolderOrganizer (date tree + Base Name folder)
├── ui/
│   ├── main_window_qt.py          # Main window, ExtensionCombo, RenameWorker thread
│   ├── settings_dialog_qt.py      # Default folders, hash verification
│   ├── save_template_dialog_qt.py
│   ├── edit_template_dialog_qt.py
│   ├── manage_templates_dialog_qt.py
│   └── styles_qt.py               # DarkRedTheme QSS
├── FileRenameMover.spec           # PyInstaller spec (excludes unused Qt modules and ML packages)
└── CHANGELOG.md                   # Per-version change log
```

## How the counter works

Before moving, the destination is scanned for `Base Name_NNNNNN.ext` files and numbering resumes after the highest one found. With **Folder named after Base Name** on, only `dest\[Base Name]` is scanned, so a large shared destination such as a NAS root is not walked in full and other folders with the same base name do not affect numbering.

## Recent Changes

Full history in [CHANGELOG.md](CHANGELOG.md).

### 3.5.1 — 2026-09-05
- Two-column form: Extension | Base Name, and Rename Pattern | Folder Organization, in the same label-over-field style as Sort by | Order
- Status box stretches to fill the remaining window height; the form fits 1000×870 in every pattern mode
- Shorter "Folder named after Base Name" checkbox text; example and hint labels word-wrap

### 3.5.0 — 2026-09-05
- Extension box is an editable dropdown filled from the source folder (most common first, counts on hover); rescans on any source path change, debounced 350 ms
- Empty Extension box auto-selects the most common extension; a typed value is kept and snapped to the matching entry

### 3.4.0 — 2026-09-05
- "Folder named after Base Name" option: `dest\[Base Name]\year\month\day`; saved in config and templates, editable in Edit Template
- Counter scan limited to `dest\[Base Name]` when the option is on
- Preview button: dry run listing `original → new relative path`
- Folder example line follows the Base Name text live
- Build spec excludes the shared venv's ML packages

### 3.3.0 — 2026-06-21
- Threaded progress bar with Cancel; drag-and-drop folders from Explorer

## Icon

`app_icon.ico` is embedded in the EXE and always shows on the running window and taskbar. On some Windows systems Explorer still shows the generic EXE icon even though PyInstaller reports "Copying icon to EXE". This is a known PyInstaller quirk, not a build error. If it bothers you, re-stamp the icon after building:

- **Resource Hacker** (GUI): open `FileRenameMover.exe`, Action → Replace Icon, pick `app_icon.ico`, save.
- **rcedit** (command line):

```
rcedit.exe FileRenameMover.exe --set-icon app_icon.ico
```

## License

MIT — see `LICENSE`.
