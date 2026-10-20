# PDF Edit — Project Plan

A desktop PDF editor for markup (annotations) and page rearrangement.

## Stack
- **PyQt6** — UI framework (consistent with other AICoding apps)
- **PyMuPDF (fitz)** — PDF rendering, page manipulation, and annotation writing
- **PyInstaller** — packaging to EXE

> **Licensing note:** PyMuPDF is AGPL-licensed (commercial license available). Fine for a personal tool; revisit if the app is ever distributed.

## Feature Scope

### Phase 1 — Viewer + page management
- Open PDF, render pages as thumbnails (left panel) + main preview pane
  - Thumbnail rendering must be async/lazy from the start so large/scanned PDFs don't freeze the UI on open
- Basic zoom (fit-to-width + zoom slider) and page navigation — a viewer without zoom is unusable even for testing
- Drag-and-drop a PDF file onto the window to open it (in addition to File > Open dialog)
- Drag-and-drop a PDF onto the thumbnail panel to insert/merge it into the open document
- Drag-and-drop thumbnail reordering
- Delete / rotate / duplicate page
- Insert pages from another PDF, split PDF into separate files, merge multiple PDFs
- Save / Save As (save-a-copy to avoid clobbering originals)
- **Undo/redo command stack built here** — page ops (delete/rotate/reorder) need undo too, and retrofitting a command pattern later is painful; Phase 2 annotations hang off the same stack
- Create CHANGELOG.md and PROJECT_SUMMARY.md from the first commit, updated with every change (project convention)

### Phase 2 — Markup annotations
- Highlight, underline, strikeout (text-based, via text selection)
- Freehand drawing/ink annotation (pen tool, adjustable color/width)
- Shapes: rectangle, ellipse, line, arrow
- Text box / sticky note annotations
- Eraser — scoped as whole-annotation delete for v1 (partial stroke erasing means splitting ink point lists; out of scope)
- Annotation undo/redo via the Phase 1 command stack
- Annotations are stored as real PDF annotation objects (editable, visible in standard viewers); flattening is an export option in Phase 3

### Phase 3 — Polish
- Advanced view controls: pan, fit modes (fit width + fit page); search text in PDF (`page.search_for`)
  - Continuous multi-page scroll: **deferred** (large viewer refactor; single-page view + thumbnail navigation covers the markup workflow)
- Export annotated PDF (flatten vs. keep editable annotations)
- Basic redaction (black-box permanent removal) — PyMuPDF makes true redaction cheap via `add_redact_annot` + `apply_redactions` (strips underlying content, not just draws over it)
- Icon, versioning, EXE build to `P:\Apps\AICoded\PDF Edit\` following usual project conventions

## Technical Risks
1. **Coordinate mapping** between the rendered pixmap and PDF page space — zoom, page rotation, and PDF's coordinate system all interact. Every drawing tool depends on getting this right once; centralize it in a single transform helper.

   **Approach:** store everything in PDF page space, convert only at the view boundary, and make one class own the transform in both directions.
   - Render with `page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))` — the pixmap already includes page rotation. Map coordinates with `self.matrix = page.rotation_matrix * fitz.Matrix(zoom, zoom)` (verified 2026-07-05 for rotations 0/90/180/270: round-trips exact, mapped rects land inside the pixmap). Expose exactly two conversion methods — `widget_to_pdf` (multiply by `~self.matrix`, the inverse) and `pdf_to_widget`. Never recompute scale factors independently. If the widget letterboxes/scrolls the pixmap, subtract that offset in these two methods and nowhere else.
   - All model data (ink strokes, shape rects, highlight quads, text-box positions) lives in PDF space as `fitz.Point`/`fitz.Rect`; the view converts on mouse events in and paint overlays out. Zoom changes touch no annotation data; saving needs no conversion.
   - Let PyMuPDF handle rotation via `page.rotation_matrix`/`derotation_matrix` — composing rotation into the render matrix means rotated pages (`/Rotate 90` scans) are not a special case anywhere else.
   - No Y-flip needed: PyMuPDF normalizes to top-left origin, matching Qt. Document this on the transform class so it isn't re-asked and half-fixed.
   - Test the round-trip before building any drawing tool: for zooms × rotations (0/90/180/270), assert `widget_to_pdf(pdf_to_widget(p)) ≈ p` and that a known word's `search_for` rect maps to the visually correct pixels.

   Payoff: highlights, ink, eraser hit-testing, and search-result highlighting all consume the same two methods — the risk is retired once, not once per tool.
2. **Text hit-testing** for highlight/underline/strikeout — requires quad lookup via `page.get_text("words")`; the fiddliest part of Phase 2.

   **Approach:** word-level selection snapped to reading order, cached per page, merged into per-line quads.
   - Extract words once per page via `page.get_text("words")` → `(x0, y0, x1, y1, word, block_no, line_no, word_no)`; build lazily on first text-tool use and cache. Linear scan is fast enough; no spatial index.
   - Select like a text editor, not a marquee: word nearest drag anchor → word nearest cursor, select everything between in reading order (sort key `block_no, line_no, word_no`).
   - Merge contiguous selected words on the same line into one rect per line for clean highlight bands; pass the list to `page.add_highlight_annot(quads=[...])` (or underline/strikeout siblings).
   - Word coordinates are in unrotated page space (same as `search_for` — verified) — route through the Risk #1 transform class.
   - Scanned pages return an empty word list: disable text-markup tools with a "no selectable text" hint rather than failing silently. OCR out of scope.
   - Known v1 limitation: rotated/vertical text gets axis-aligned highlights. Acceptable; `page.search_for(..., quads=True)` shows the slanted-quad representation if it ever matters.
   - Ergonomics: a few pixels of hit tolerance around word rects; a drag touching no words creates no annotation.

3. **Large-document rendering** — thumbnails and page renders must be lazy/async (worker thread). **Hard cap: 200 pages per PDF** — refuse to open larger files, and refuse insert/merge operations that would push the document past 200 pages. Keeps rendering, snapshots, and undo memory safely bounded.

## Resolved Questions
1. **Annotations stay editable** as real PDF annotation objects by default; flatten offered as an export option (PyMuPDF supports both).
2. **Large/scanned PDF performance** — handled by async/lazy rendering plus a hard 200-page-per-PDF cap (see Technical Risks #3).
3. **Standalone app**, consistent with the other AICoding projects.
4. **UI theme: dark green color scheme** across the app.
