# PDF Edit — Changelog

## Unreleased
- **Icon-only buttons now have a short text label.** Buttons that showed only a symbol (↻, …, 🎲, 🗑 and so on) now read e.g. "↻ Refresh" or "Browse" in regular-weight, regular-size text; their fixed widths were dropped so they size to their label. Covers: the annotation colour swatch now reads "Color".

## v1.1.0 — 2026-07-05

Phase 3 completion release.

- **Hover comment popups**: with the Select or Pan tool, hovering over any
  annotation that carries text (sticky notes, text boxes, callouts) shows
  its content in a tooltip.
- **Sticky notes are now editable**: double-click a note marker with the
  Select tool to read/edit its comment.
- **Fit Page** view mode (Ctrl+9) alongside Fit Width (Ctrl+0), on the
  toolbar and View menu.
- Deferred: continuous multi-page scroll (single-page view + thumbnail
  navigation stays; revisit if needed).

## v1.0.6 — 2026-07-05

Fixes from real-world testing on 200-DPI rotated scans, plus annotation editing.

- **Fixed: upside-down text** on rotated pages — text boxes and callouts now
  pass the page rotation to the annotation so text always displays upright.
- **Fixed: microscopic text/notes on high-DPI scans** — font sizes and
  text-box dimensions now scale with the page size (a 200-DPI letter scan is
  ~2.8x the units of a standard page). Sticky notes get a fixed-size yellow
  marker drawn by the viewer (the PDF's own note icon is pinned to 16x16 by
  the renderer, standard viewer behavior).
- **Text Box now uses the full styling dialog** (previously a bare text
  prompt): font family (Helvetica/Times/Courier), bold, font size, text
  color, and background color. The Callout dialog gained font family + bold
  too. Choices are remembered between uses.
- **New Select tool** (shortcut S): click any annotation to select it
  (dashed outline), drag to move it — callout tails, line endpoints and ink
  strokes move along. Double-click a text box or callout to re-edit its
  text and styling. Delete/Backspace removes the selected annotation.

## v1.0.5 — 2026-07-05

- New Callout tool (shortcut B): drag FROM the thing you're pointing at TO
  where the bubble should sit, then enter text. Dialog offers background
  color, text color, and font size (choices are remembered). Stored as a
  native PDF FreeText callout annotation — the arrow tail attaches to the
  nearest bubble edge and shows in other PDF viewers too. Bubble auto-sizes
  to the text; eraser/undo work as usual.

## v1.0.4 — 2026-07-05

- Toolbar now uses icons instead of text labels (drawn programmatically in
  `ui/icons.py` to match the dark green theme; tooltips show name + shortcut)
- Rotate Left / Rotate Right added to the toolbar, placed on the left side
  next to undo/redo for quick access when fixing scanned pages

## v1.0.3 — 2026-07-05

- New "Cross Out" tool (shortcut C): drag a box to draw a boxed-X across
  content — the same look the old redaction mark had. Uses the selected
  annotation color and pen width; works on scans without a text layer
  (visual substitute for strikeout). Stored as one ink annotation, so
  eraser and undo work on it.

## v1.0.2 — 2026-07-05

- Highlight tool reworked: now a drag-box with a 30%-opacity color fill,
  so it works on scanned PDFs with no text layer (previously it required
  text selection and silently did nothing on scans). Live preview shows
  the translucent fill while dragging.
- Underline and strikeout remain text-selection based (they require a
  text layer; scans without OCR show a status-bar hint).

## v1.0.1 — 2026-07-05

- Redact tool now applies immediately on mouse release: the selected area
  turns solid black and underlying content (text + image pixels) is
  permanently stripped, instead of leaving a red "redaction mark" that
  required Edit > Apply Redactions. Undo (Ctrl+Z) still reverses it before
  saving. The menu action remains for PDFs carrying redaction marks made
  by other tools.

## v1.0.0 — 2026-07-05

Initial release implementing all three PLAN.md phases.

### Phase 1 — Viewer + page management
- Open PDF via dialog, drag-drop onto window, or command-line argument
- Async thumbnail panel (worker thread renders from an independent document copy)
- Basic zoom (Ctrl+wheel, Ctrl+=/-, fit-width Ctrl+0) and page navigation (PgUp/PgDn)
- Drag-drop thumbnail reordering (implemented via `doc.select()` on the new order)
- Delete / rotate left-right / duplicate page (menu, shortcuts, thumbnail context menu)
- Insert PDF, merge multiple PDFs, split into single-page files
- Save As (save-a-copy; same-path save serializes, releases the file handle, rewrites)
- Snapshot-based undo/redo (25 levels) covering page ops AND annotations
- **200-page hard cap** — refuses to open or insert/merge past 200 pages

### Phase 2 — Markup annotations
- Highlight / underline / strikeout via editor-style word selection
  (reading-order drag selection, merged to one quad per line)
- Pen (ink) tool with adjustable color and width
- Shapes: rectangle, ellipse, line, arrow
- Text box (FreeText) and sticky note annotations
- Eraser: whole-annotation delete (v1 scope per plan)
- Scanned pages (no text layer) disable text-markup with a status hint

### Phase 3 — Polish
- Text search across the document (F3 / Shift+F3, hit highlighting)
- Export flattened copy (`doc.bake()`); normal saves keep annotations editable
- True redaction: mark black boxes, Edit > Apply Redactions strips content
- Dark green UI theme
- Coordinate mapping centralized in `transform.PageTransform`
  (verified for page rotations 0/90/180/270)
