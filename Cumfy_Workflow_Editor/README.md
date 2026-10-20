# ComfyUI Workflow Editor — Plan

## Overview

A desktop form editor for ComfyUI workflow JSON files.
Open a `.json` workflow and every node appears as its own card with all of its editable
settings — prompts, LoRA strengths, sampler settings, resolutions, file names, flags —
then save. No node canvas, no wires: just a clean, filterable scrollable form.

Everything in the JSON the editor doesn't show (links, positions, groups, metadata) is
passed through untouched on save.

---

## Supported File Formats

| Format | Detected by | Field names come from |
|--------|-------------|-----------------------|
| **API format** (`Save (API)` in ComfyUI) | top-level `{id: {class_type, inputs, _meta}}` | the `inputs` keys |
| **UI / graph format** (normal `Save`) | top-level `nodes[]` + `links[]` | `WIDGET_NAMES` table in `workflow_model.py` for known node types; `Value N` otherwise |

In the API format, an input whose value is `[node_id, slot]` is a connection and is shown
read-only. In the UI format, an input that has a `widget.name` and a link is a converted
widget and its positional value is shown read-only.

---

## What Each Node Card Shows

- **Header** — node title, class type, `#id`, and a BYPASSED / MUTED badge (UI format `mode`).
  Click the arrow to collapse.
- **Fields** — one editor per scalar value, chosen by type:

  | JSON value | Editor |
  |------------|--------|
  | `true` / `false` | checkbox |
  | int | spin box (range/step by field name; seeds and >32-bit ints use a plain text box) |
  | float — or an int in a float-named field (`cfg: 1`) | double spin box, written back as int while whole |
  | string in `CHOICES` (`sampler_name`, `scheduler`, `control_after_generate`, `upscale_method`, `weight_dtype`, …) | editable drop-down |
  | string named `text` / `prompt` / `expression` / … or multi-line / >100 chars | text area (negative prompts tinted red) |
  | any other string | line edit |

- **Connections** — dim footer listing `input ← Source node [id]` for wired inputs.

Cards are grouped and colour-coded by category, in this order:
**Prompts · LoRAs · Sampling · Image / Video / Latent · Loaders · Output · Other · Notes**.
A node with a paragraph field named `text` / `prompt` / `positive` / `negative` is a
Prompt node regardless of its class type.

---

## Opening Files

- **File → Open…** (Ctrl+O) or the toolbar **Open** button
- **Drag and drop** — drop a `.json` file anywhere on the window (v1.1.0+).
  Non-JSON drags are refused; dropping multiple files opens the first `.json`.
- Either route prompts to save first when the open workflow has unsaved edits.

## Startup

- Window opens centred on the current screen and is brought to the front once
  (`bring_to_front()` right after `show()` and again 150 ms later) — never always-on-top.

## Navigating Big Graphs

- **Find node** box in the toolbar (Ctrl+F) filters cards by title, class type, or `#id`.
- **Show all nodes** toggle — nodes with no editable fields (VAEDecode,
  ReferenceLatent, switches, …) are hidden by default; the setting is remembered.
- **View → Expand all / Collapse all** (Ctrl+Shift+E / Ctrl+Shift+C).

---

## Tech Stack

- Python + PyQt6
- No ComfyUI server connection needed — pure file editor

---

## File Structure

```
Cumfy_Workflow_Editor/
  main.py                  ← entry point (v1.2.0)
  run.bat                  ← run from source via the shared .venv
  workflow_model.py        ← format detection + document model (parse_workflow, NodeInfo, Field,
                              WIDGET_NAMES / CHOICES tables, number_hint)
  settings.py              ← last_dir, show_all_nodes  (workflow_editor_config.json)
  ui/
    __init__.py
    styles.py              ← dark theme + category colours (shared with Chain Automator)
    main_window.py         ← window chrome, toolbar filter, file open/save, drag-and-drop
    node_section.py        ← NodeSection card widget + make_editor() factory
    node_cards.py          ← (unused, kept for future canvas mode)
    canvas.py              ← (unused, kept for future canvas mode)
  Test files/              ← sample workflows (local only, not committed)
```

---

## Extending

- **New choice list:** add the field name to `CHOICES` in `workflow_model.py`.
- **UI-format names for a node type:** add its widget order to `WIDGET_NAMES`.
- **Numeric range/step:** add a rule to `_known_hint()`.
- **Category rules:** `_category_for()`.

---

## Out of Scope (for now)

- Node canvas / drag-drop node layout
- Adding, removing, or rewiring nodes
- Connecting to the ComfyUI server (would let the UI format use real widget names via `/object_info`)

---

## Build

Double-click `build.bat` (or run `python build_exe.py`). The script passes the shared-venv
`--exclude-module` list (torch, tensorflow, cv2, …) — mandatory, or the EXE balloons ~10× —
and copies the result to the EXE target below.

**Gotcha:** the model module is `workflow_model.py`, not `workflow.py`. PyInstaller ships a
contrib hook for a PyPI package called `workflow`; a local module with that name makes the
build abort with `Failed to import module __PyInstaller_hooks_0_workflow`.

---

## App Name

**ComfyUI Workflow Editor**
EXE target: `P:\Apps\AICoded\ComfyUI Workflow Editor\`
