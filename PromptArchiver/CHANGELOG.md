# Changelog

All notable changes to Prompt Archiver are documented here.

## Unreleased
- **Icon-only buttons now have a short text label.** Buttons that showed only a symbol (↻, …, 🎲, 🗑 and so on) now read e.g. "↻ Refresh" or "Browse" in regular-weight, regular-size text; their fixed widths were dropped so they size to their label. Covers: ⚙ Settings, ⋮ Actions and ✕ Remove.

## [2.0.0] — 2026-07-11

### Changed — full PyQt6 rewrite

Complete rewrite from Electron + React + Material-UI to Python + PyQt6, matching
the standard AICoded toolset (same stack as Music Player, AI Image Studio, etc.).

- **Archive format unchanged** — existing `Prompt_Archive` folders load as-is;
  `metadata.json` keys are identical, so files written by v2 remain readable by v1.x
- **Settings migration** — on first run, the archive path is picked up automatically
  from the old electron-store config (`%APPDATA%\prompt-archiver\config.json`)
- **Dark-blue theme** — replaces the MUI light theme, consistent with the other apps
- Single ~small PyInstaller EXE replaces the Electron installer + `node_modules`
- Feature parity with v1.2.5: add/edit/clone/delete prompts, change type,
  star ratings, tags, search + type/rating filters, multi-file attachments
  (picker + drag-and-drop), add-vs-replace file modes with duplicate-name
  suffixing, ZIP export of checked prompts, image/video/text preview tabs,
  copy prompt / negative prompt to clipboard, settings + help dialog

### Fixed

- Prompt folders without a `prompt.txt` (created by some v1.x flows) were silently
  hidden by the old app; they now load and display with an empty prompt text
- Drag-and-drop now also works when running from source (the Electron version
  required a compiled build for drag-and-drop)

### Removed

- Electron/React sources (`src/`, `public/`, `package.json`, `node_modules`),
  electron-builder packaging, `start-prompt-archiver.bat`

## [1.2.5] and earlier

Electron era — see README.md history and git log. Final Electron
feature set: multi-file support, clone prompts, add/replace file modes, star
ratings, AI model metadata, negative prompts, drag-and-drop in compiled app.
