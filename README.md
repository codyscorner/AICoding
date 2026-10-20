# AI Coding

**Author:** [Cody's Corner](https://github.com/codyscorner) — [@codyscorner](https://github.com/codyscorner)

This is my personal lab. It's a monorepo of small desktop utilities, AI-pipeline tools, and the occasional game, built by AI coding with Claude Code: an idea pops into my head, I describe it, we build it, I use it, and it grows from there.

Nothing here is a product. Each folder is an experiment that solved a real itch on my own machines: moving and renaming batches of files, driving ComfyUI workflows, poking at S3 buckets, pulling metadata out of videos, and whatever else came up that week. Some projects are polished and get used daily; some were one-afternoon curiosities that stopped where the curiosity did. Both kinds stay here on purpose, because the point of the repo is to keep the experiments, the history, and the lessons in one place.

## What you'll find

- **Desktop utilities** — mostly Python with PyQt6 or PySide6, shipped as portable single-file EXEs that keep their settings next to the executable
- **AI and image tools** — front ends and automation for local ComfyUI, image sorting and dedupe with CLIP and YOLO, prompt management
- **File management** — rename, move, copy, sync, dedupe, archive, and find
- **Small games and one-offs** — HTML games and quick scripts that were fun to try

## How it's organized

Every project lives in its own top-level folder and stands alone. Open a folder and you'll find:

- `README.md` — what it does, how to run and build it, and recent changes; this is the one doc every project keeps
- `CHANGELOG.md` — per-version change log
- A PyInstaller `.spec` for projects that build to an EXE

Built EXEs are deployed outside the repo to `P:\Apps\AICoded\<App Name>\`.

## Running things

**Python apps** — from inside the project folder, using the shared `.venv` at the repo root:

```bash
python main.py
```

**Building an EXE** — each project has its own spec; the pattern is:

```bash
..\.venv\Scripts\pyinstaller.exe --noconfirm --clean <Project>.spec
```

**Web games** — open the HTML file in any modern browser.

**.NET and Electron projects** — see the README in that folder.

## Conventions

- One project, one folder, no shared code between projects
- Config lives next to the EXE, never in `%APPDATA%`
- Version is bumped in `main.py`, `CHANGELOG.md`, and `README.md` before every build
- Dialogs must fit a 1920×1080 screen
- Work happens on a feature branch and lands on `master` through a pull request

## License

MIT unless a project folder says otherwise.

---

**Last Updated:** 2026-09-05
