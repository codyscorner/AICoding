# Changelog

All notable changes to File Rename Mover will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased
- **Icon-only buttons now have a short text label.** Buttons that showed only a symbol (↻, …, 🎲, 🗑 and so on) now read e.g. "↻ Refresh" or "Browse" in regular-weight, regular-size text; their fixed widths were dropped so they size to their label. Covers: the six folder Browse buttons (main window, Settings, Edit Template).

## [3.5.1] - 2026-09-05

### Changed
- **Two-column form.** Extension and Base Name now sit side by side (example
  line spans both). Rename Pattern (left) and Folder Organization (right) share
  one row. The form is ~180 px shorter, so the Status box is no longer cut off
  at the default 1000×870 window.
- Status box now stretches to fill whatever height is left instead of a fixed
  150 px block with empty space under it.
- Shorter checkbox text ("Folder named after Base Name") and word-wrapped
  example/hint labels so nothing clips in a half-width column.

## [3.5.0] - 2026-09-05

### Added
- **Extension dropdown filled from the source folder.** The Extension box is now
  an editable dropdown. Whenever the Source Folder changes (browse, drag-and-drop,
  typing, template load, startup) the folder is scanned and the dropdown lists
  every extension found there, most common first, with a file count as tooltip.
  An empty Extension box auto-selects the most common one; a value you already
  typed is kept (and snapped to the matching entry, so `png` becomes `.png`). The label shows how many types were found and the status box
  logs a summary (`.mp4 ×12, .png ×3, …`).
- `FileScanner.get_extension_counts()` — non-recursive extension census.

### Changed
- Scan is debounced (350 ms) so typing a path by hand doesn't rescan per keystroke.

## [3.4.0] - 2026-09-05

### Added
- **Base Name folder option** — new checkbox under Folder Organization:
  "Create a folder named after the Base Name". When on, files land in
  `dest\[Base Name]\...` with any date organization created inside that folder,
  e.g. `dest\Sahara\2026\09\05\Sahara_000001.mp4`. Works with every structure
  including `flat` (which gives plain `dest\[Base Name]\`).
  - Saved in config (`base_name_folder`) and in templates; editable in the
    Edit Template dialog; shown in Manage Templates details.
  - Counter continuation scans only `dest\[Base Name]` when the option is on, so a
    large shared destination (NAS root) is not walked in full and files with the
    same base name elsewhere in the destination don't affect the numbering.
- **Preview button** — dry run that lists every planned move
  (`original → [Base Name]\yyyy\mm\dd\new_name`) in the status box without
  touching any files. Uses the same validation as Move and Rename.
- Folder Organization example line now updates live as you type the Base Name
  and toggle the checkbox.

### Changed
- `FolderOrganizer.get_destination_subfolder()` / `get_folder_structure_example()`
  take an optional `base_name_folder` argument.
- `FileRenamer.generate_preview()` now returns the relative destination path
  (subfolders included), not just the new filename.
- Input validation and option collection factored into
  `MainWindowQt._collect_operation()` shared by Preview and Move and Rename.
- Build spec excludes the shared venv's ML packages (torch, tensorflow, cv2, …)
  and PyQt5/PyQt6 so the EXE stays lean.

## [3.3.0] - 2026-06-21

### Added
- Progress bar wired to a QThread worker; UI stays responsive during operations
- Cancel button aborts after the current file completes
- Source/Destination fields accept folders dragged from Windows Explorer

## [2.1.4] - 2025-12-08

### Fixed
- Fixed filename formatting to remove trailing underscore before extension
  - NumberingPattern: `photo_000001.jpg` instead of `photo_000001_.jpg`
  - DateTimePattern: `photo_20251208_000001.jpg` instead of `photo_20251208_000001_.jpg`
  - PrefixPattern: `backup_file.jpg` instead of `backup_file_.jpg`
- Fixed preview generation to use current pattern strategy instead of hardcoded legacy format
- Preview now respects sorting configuration and all pattern types

### Added
- Comprehensive filename validation and sanitization
  - Path traversal protection (blocks `..` in filenames)
  - Invalid character detection (blocks `<>:"/\|?*`)
  - Reserved Windows name validation (blocks CON, PRN, AUX, NUL, COM1-9, LPT1-9)
- Enhanced extension validation with character checking
- Better error messages for validation failures

### Security
- Added protection against path traversal attacks
- Filename sanitization prevents directory traversal vulnerabilities
- Validates against Windows reserved filenames

## [2.1.1] - 2025-11-27

### Fixed
- Fixed SortBy enum conversion bug that caused "not a valid SortBy" error when using date_created or date_modified sorting
- Fixed folder path separators to use Windows backslashes (\\) instead of forward slashes (/) in UI examples
- Improved same-folder operation handling to properly distinguish between rename and move operations

### Added
- Added duplicate file checking to prevent overwriting existing files
- Added skip logic for files that already have the target name
- Enhanced status logging to show "Renamed:" vs "Moved:" for clarity

### Changed
- Improved error messages for file operation failures
- Better path handling for Windows-specific operations

## [2.1.0] - 2025-11-27

### Added
- **Custom Sorting Options**
  - Sort by: Name, Date Modified, Date Created, Size
  - Sort order: Ascending or Descending
- **Multiple Rename Patterns**
  - Numbering Pattern (simple sequential)
  - DateTime Pattern (various date/time formats)
  - Prefix Pattern (keep original names with prefix)
  - Custom Pattern (user-defined with placeholders)
- **Folder Organization**
  - Flat (no subfolders)
  - By Year (YYYY/)
  - By Year/Month (YYYY/MM/)
  - By Year/Month/Day (YYYY/MM/DD/)
  - By Date (YYYY-MM-DD/)
  - By Month (YYYY-MM/)
- New modules: `sorting.py`, `rename_patterns.py`, `folder_organization.py`
- Enhanced main window (main_window_v2.py) with all new controls
- Scrollable interface for better usability
- Live preview of rename patterns and folder structures
- Configuration persistence for all new settings

### Changed
- Window size increased to 900x750 to accommodate new features
- Enhanced FileRenamer class with pattern and sorting support
- Extended ConfigManager with new preference fields

## [2.0.0] - 2025-11-27

### Added
- Complete refactoring to object-oriented architecture
- Modular project structure with separate concerns
- `config.py` - Configuration management with JSON persistence
- `file_operations.py` - File handling business logic
  - FileValidator - Input validation
  - FileScanner - Directory scanning
  - FileRenamer - Move and rename operations
- `ui/` package for UI components
  - `main_window.py` - Main application window
  - `settings_dialog.py` - Settings dialog
  - `styles.py` - Theme management system
- Theme management with ThemeManager and DarkRedTheme
- Comprehensive error handling and validation
- Type hints and docstrings throughout codebase
- Preview functionality (generate_preview method)

### Changed
- Reorganized from single 445-line file to modular architecture
- Improved separation of UI and business logic
- Enhanced configuration system with defaults
- Better code maintainability and testability

### Maintained
- Backward compatibility with v1.2.4 configurations
- Original dark red theme and UI aesthetics
- All existing functionality preserved

## [1.2.4] - Previous Release

### Features
- Basic file rename and move functionality
- Sequential numbering with 6-digit counters
- Configuration persistence (source/dest folders, extension, rename pattern)
- Dark red theme UI
- Settings dialog for default folders
- Status logging
- Counter continuation from existing files

---

## Version Numbering

- **Major** (X.0.0): Breaking changes, major rewrites
- **Minor** (2.X.0): New features, backward compatible
- **Patch** (2.1.X): Bug fixes, minor improvements
