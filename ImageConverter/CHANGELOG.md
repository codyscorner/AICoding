# Changelog

## Unreleased
- **Icon-only buttons now have a short text label.** Buttons that showed only a symbol (↻, …, 🎲, 🗑 and so on) now read e.g. "↻ Refresh" or "Browse" in regular-weight, regular-size text; their fixed widths were dropped so they size to their label. Covers: the source and output folder Browse buttons.

## v1.1.0 — 2026-07-08

- Drag-and-drop: drop a folder or file onto the window to set the source folder.
- Resize-on-convert: optional max-dimension cap (aspect ratio preserved via `Image.thumbnail`).
- HEIC/HEIF input support via the optional `pillow-heif` package; the app still runs fine without it, just without HEIC input.
- Metadata handling: EXIF and ICC profile are now preserved by default on conversion; a new "Strip metadata" checkbox opts out.
- Parallel workers: optional 2-16 worker `ThreadPoolExecutor` to speed up large batches on multi-core machines.
- Added `pillow-heif` to `hiddenimports` and the shared-venv ML-package `excludes` list in `ImageConverter.spec`.

## v1.0.0 — initial release

- Batch image conversion between PNG, JPG, WebP, BMP, TIFF.
- Quality slider for lossy formats, recursive subfolders, delete-originals option.
- JPEG alpha-flattening (RGBA → white-background RGB).
- Supersedes JPG2PNG_Converter.
