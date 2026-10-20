# Image Converter

Batch-converts images between JPG, PNG, WebP, BMP, and TIFF formats. Supersedes JPG2PNG_Converter.

**Current version: 1.1.0**

## Features

- Select a source folder containing images in any supported format
- Drag-and-drop a folder or file onto the window to set the source folder
- Choose an output format: PNG, JPG, WebP, BMP, TIFF
- Quality slider for lossy formats (JPG, WebP) — range 1–100
- Output folder defaults to same as source; optionally choose a different destination
- Recursive subfolder support with mirrored directory structure in output
- Skip files already in the target format (avoids re-converting)
- Delete originals after conversion (optional)
- HEIC/HEIF input support (phone photos) via optional `pillow-heif` package
- Resize-on-convert: cap the longest side to a max dimension (aspect-ratio preserved)
- Metadata (EXIF/ICC profile) preserved by default; "Strip metadata" option removes it
- Parallel workers (2-16) to speed up large batches on multi-core machines
- JPEG alpha-channel handling: RGBA/LA images composited onto white background
- Cancel mid-batch
- Progress bar and real-time file log with success/error coloring
- Dark navy PyQt6 UI (same theme as other AICoded apps)

## Requirements

- Python 3.10+
- PyQt6
- Pillow
- pillow-heif (optional, enables HEIC/HEIF input)

## Running from Source

```bash
python main.py
```

## Building the EXE

```bash
pyinstaller ImageConverter.spec --clean --noconfirm
```

Output: `dist/ImageConverter.exe`, deployed to `P:\Apps\AICoded\Image Converter\`.

## Notes

- AVIF is not included — it requires the optional `pillow-avif-plugin`; add later if needed

## Recent Changes

Full history in [CHANGELOG.md](CHANGELOG.md).

### v1.1.0
- Drag-and-drop a folder or file onto the window to set the source folder
- Resize-on-convert option (max-dimension spinbox, aspect-preserving)
- HEIC/HEIF input support via `pillow-heif` (optional, skipped gracefully if absent)
- Metadata now preserved by default (EXIF + ICC profile copied through); "Strip metadata" opts out
- Parallel workers option (2-16) for faster large batches

### v1.0.0
- Initial release: batch conversion between PNG, JPG, WebP, BMP, TIFF
- Quality slider for lossy formats, recursive subfolders, delete-originals option
- JPEG alpha-flattening (RGBA → white-background RGB)
- Supersedes JPG2PNG_Converter — all of its functionality is covered and extended
