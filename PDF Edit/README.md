# PDF Edit — Project Summary

**Version:** 1.1.0
**Status:** All three PLAN.md phases complete (continuous scroll deferred)
**Stack:** Python 3.12, PyQt6, PyMuPDF (fitz), PyInstaller

A desktop PDF editor for markup (annotations) and page rearrangement, with a
dark green UI theme.

## Architecture

| File | Role |
|---|---|
| `main.py` | Entry point, app version, theme + icon setup |
| `document.py` | `PdfDocument`: fitz wrapper, snapshot undo/redo (25 levels), all page ops + annotation writers, 200-page cap |
| `transform.py` | `PageTransform`: the ONLY place PDF↔pixel coordinate math lives |
| `theme.py` | Dark green QSS stylesheet |
| `ui/main_window.py` | Menus, toolbar, search, wiring |
| `ui/page_view.py` | Page renderer + all mouse tools (markup, shapes, eraser, redact) |
| `ui/thumbnail_panel.py` | Async thumbnails, drag reorder, external PDF drops, context menu |

## Key invariants (do not break)

- **All model coordinates are unrotated PDF page space.** Only
  `PageTransform` converts to/from pixels. Pixmaps are rendered with the
  plain zoom matrix (rotation already applied); the mapping matrix is
  `page.rotation_matrix * Matrix(zoom, zoom)`. No Y-flip.
- **Undo is snapshot-based** (`doc.tobytes()` before every mutation).
  Every mutating method in `PdfDocument` must call `_snapshot()` first.
- **200-page hard cap** (`document.MAX_PAGES`) on open, insert, merge,
  duplicate.
- **fitz is not thread-safe**: the thumbnail worker opens its own document
  copy from bytes; never pass the live document to a thread.
- Annotations stay editable PDF annotation objects; flatten only on
  File > Export Flattened (uses `doc.bake()` on a copy).

## Build

```powershell
$ex = @("torch","torchvision","torchaudio","tensorflow","transformers","cv2",
        "scipy","pandas","matplotlib","PIL","numpy","onnx","onnxruntime",
        "triton","IPython","jupyter","sklearn","numba","jax","safetensors",
        "tokenizers","einops","av","soundfile") | ForEach-Object { "--exclude-module"; $_ }
python -m PyInstaller --noconfirm --noconsole --onefile --name "PDF Edit" `
    --icon app_icon.ico --add-data "app_icon.ico;." @ex main.py
```

**The excludes are mandatory** — the shared AICoding venv contains ML
packages (torch, tensorflow, …); without excludes the EXE balloons from
~56 MB to ~590 MB.

EXE is copied to `P:\Apps\AICoded\PDF Edit\` after each build.
Bump the patch version in `main.py` + this file + CHANGELOG before every build.

## Test material

- `PDF Files\` — sample PDFs for manual testing.
