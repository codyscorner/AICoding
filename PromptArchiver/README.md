# Prompt Archiver

A desktop application for storing, organizing, and viewing AI prompts alongside their generated outputs (text, images, or videos).

## Features

### Core Features
- **Local-First Storage**: All data stored locally on your machine with no cloud dependency
- **Automatic Organization**: Creates organized folder structure by content type (text/image/video)
- **Media Support**: Built-in viewers for text, images, and videos
- **Search & Filter**: Find prompts by content or tags
- **Tagging System**: Organize prompts with custom tags
- **Star Rating System**: Rate prompts from 0-5 stars for easy quality tracking
- **Export/Backup**: Export selected prompts to ZIP files for backup or sharing
- **Native Desktop App**: Built with Python + PyQt6 (v2.0.0 rewrite; originally Electron)

### File Management
- **Multiple File Support**: Attach multiple output files to a single prompt
- **Drag-and-Drop**: Drag files directly into Add/Edit dialogs for quick attachment
- **Add or Replace Files**: Choose to add more files to existing prompts or replace all files
- **Smart Conflict Resolution**: Automatic file renaming when duplicates are detected

### Prompt Management
- **Clone Prompts**: Duplicate entire prompts with all files and metadata for iteration
- **Edit Everything**: Modify prompts, tags, metadata, and files after creation
- **Change Type**: Move prompts between type categories (text/image/video)
- **Delete Protection**: Confirmation dialog prevents accidental deletions

### AI Model Tracking
- **AI Source**: Track where the output was generated (e.g., "Stable Diffusion WebUI", "ChatGPT")
- **Model Name**: Record specific model used (e.g., "GPT-4", "DALL-E 3", "Flux")
- **Model Type**: Categorize the model type (e.g., "Text", "Image", "Video")
- **Base Model**: Document base model variants (e.g., "SDXL 1.5", "Llama 2")
- **Negative Prompts**: Store negative prompts for image/video generation workflows

## Installation

### Prerequisites
- Python 3.11+ with PyQt6 (`pip install -r requirements.txt`), or use the shared
  AICoding venv at `..\.venv`

### Running from source
```bash
run.bat          # or: python main.py
```

### Building the EXE
```bash
build-app.bat    # PyInstaller one-file build → deploys to P:\Apps\AICoded\Prompt Archiver\
```

## Usage

### Adding Prompts
1. Click the "+" button to open the Add Prompt dialog
2. Enter your prompt text (required)
3. Add a title for easy identification (optional, max 40 characters)
4. Select the content type (text, image, or video)
5. Add AI model information (optional but recommended):
   - AI Source (e.g., "Midjourney", "Claude", "ComfyUI")
   - Model Name (e.g., "Claude 3.5 Sonnet", "Stable Diffusion XL")
   - Model Type (e.g., "Chat", "Image Generation")
   - Base Model (e.g., "VEO 3", "Flux Dev")
6. Add a negative prompt if applicable (for image/video generation)
7. Add tags for organization (press Enter after each tag)
8. **Attach output files** using one of these methods:
   - Click "Select Files" to browse and select multiple files
   - **Drag and drop files** directly into the dashed box area
   - Files appear in a list where you can remove individual items
9. Click "Save Prompt"

### Browsing Prompts
- Use the sidebar to browse all saved prompts
- **Filter by type** using the dropdown (All/Text/Image/Video)
- **Filter by rating** to see only your best prompts
- **Search** by prompt content, title, or tags
- Click on any prompt to view its details

### Viewing and Managing Prompts
- **View Details**: Click any prompt to see full details, metadata, and output files
- **Rate Prompts**: Click on stars to rate from 0-5
- **Copy to Clipboard**: Click the copy icon next to prompts to copy text
- **Browse Files**: Use tabs to switch between multiple output files
- **Menu Options** (click ⋮ icon):
  - **Edit Prompt**: Modify text, tags, metadata, and files
  - **Clone Prompt**: Create a duplicate for variations/iterations
  - **Change Type**: Move to a different category
  - **Delete Prompt**: Permanently remove (with confirmation)

### Editing Prompts
1. Click the ⋮ menu icon and select "Edit Prompt"
2. Modify any field (prompt text, title, tags, metadata)
3. **Manage files** using these options:
   - **Add More Files**: Keeps existing files and adds new ones
   - **Replace All Files**: Removes all existing files and adds new ones
   - **Drag and Drop**: Drop files directly into the dialog to add them
4. Click "Save Changes"

### Cloning Prompts
1. Click the ⋮ menu icon and select "Clone Prompt"
2. A complete copy is created with:
   - All prompt text and metadata
   - All output files duplicated
   - New timestamp
   - Rating reset to 0
   - Tracked origin in metadata
3. Use clones to iterate on prompts without losing the original

### Exporting
1. Select prompts using the checkboxes in the sidebar
2. Click "Export Selected" to create a ZIP backup
3. Choose the export location
4. All files and metadata are included in the export

### Settings
- Click the settings icon to configure the archive location
- The default location is `~/Prompt_Archive`
- All data is stored locally in organized folders

## File Structure

The application organizes your prompts in the following structure:

```
Prompt_Archive/
├── text/
│   ├── prompt_2024-01-01T10-00-00/
│   │   ├── prompt.txt
│   │   ├── negative_prompt.txt (if applicable)
│   │   ├── metadata.json
│   │   ├── output_1.txt
│   │   └── output_2.txt
├── image/
│   ├── prompt_2024-01-01T11-00-00/
│   │   ├── prompt.txt
│   │   ├── negative_prompt.txt
│   │   ├── metadata.json
│   │   ├── image_1.png
│   │   ├── image_2.png
│   │   └── image_3.png
└── video/
    ├── prompt_2024-01-01T12-00-00/
    │   ├── prompt.txt
    │   ├── negative_prompt.txt
    │   ├── metadata.json
    │   ├── video_1.mp4
    │   └── video_2.mp4
```

Each prompt folder contains:
- `prompt.txt`: The original prompt text
- `negative_prompt.txt`: Negative prompt (optional, for image/video generation)
- `metadata.json`: Comprehensive metadata including:
  - Timestamp and folder name
  - Title (optional)
  - Tags
  - AI source, model name, model type, base model
  - Rating (0-5 stars)
  - Clone tracking (if cloned from another prompt)
- **Multiple output files**: Any number of generated content files (images, videos, text files)

## Technical Details

### Built With
- **Python 3 + PyQt6**: Native desktop UI (dark-blue AICoded theme)
- **PyQt6 QtMultimedia**: In-app video playback (FFmpeg backend)
- **PyInstaller**: Single-file EXE packaging

### Source Layout
- `main.py` — entry point (version, theme, icon)
- `archive.py` — all file/metadata operations on the archive folder
- `ui/` — main window, sidebar, content area, dialogs, media viewer, theme

### Key Features
- **Security**: Local-only storage with no external data transmission
- **Performance**: Handles thousands of prompts efficiently with quick search and filtering
- **Extensibility**: Modular architecture for future enhancements
- **Data Integrity**: Smart conflict resolution prevents file overwrites
- **Backup-Friendly**: Simple folder structure makes manual backups easy

### Recent Updates (v2.0.0)
- ✅ **Full PyQt6 rewrite** - Electron/React replaced with the standard Python + PyQt6 toolset
- ✅ **Same archive format** - existing archives load unchanged; v1.x can still read v2 metadata
- ✅ **Automatic settings migration** - archive path picked up from the old electron-store config
- ✅ **Dark-blue theme** - consistent with the other AICoded apps
- ✅ **Recovers hidden prompts** - folders missing prompt.txt now load instead of being skipped
- ✅ Feature parity: multi-file support, clone, add/replace file modes, star ratings,
  AI model tracking, negative prompts, drag-and-drop (now also in dev mode)

## Tips and Best Practices

### Organizing Your Prompts
- **Use descriptive titles** - Makes browsing easier, especially with many prompts
- **Tag consistently** - Establish a tagging convention (e.g., "style:photorealistic", "subject:portrait")
- **Rate as you go** - Rate prompts immediately after reviewing outputs
- **Add model info** - Future-you will thank you for documenting which models worked best

### Working with Files
- **Multiple variations** - Attach all variations from a single prompt session
- **Drag and drop** - Fastest way to add files to prompts
- **Clone before editing** - Create a clone before major edits to preserve the original
- **Use meaningful filenames** - Files keep their original names in the archive

### Workflow Suggestions
1. **Iteration workflow**: Create initial prompt → Rate output → Clone → Modify clone → Compare
2. **Batch generation**: Generate multiple outputs → Save all to one prompt → Rate best ones 5 stars
3. **Template building**: Create and rate base prompts → Clone for variations → Build a library of proven prompts

### File Management
- **Add vs Replace**: Use "Add More Files" for additional variations, "Replace" when starting fresh
- **Archive location**: Choose a location that's regularly backed up (OneDrive, Dropbox, etc.)
- **Export regularly**: Create ZIP backups of your best prompts for safekeeping

## Future Enhancements

- Batch operations (tag multiple prompts at once)
- Markdown support for text prompts with live preview
- Side-by-side comparison view for prompt variations
- AI-powered auto-tagging suggestions
- Optional NAS/private cloud sync
- Import from other formats (ChatGPT exports, etc.)
- Custom metadata fields
- Advanced search with filters and boolean operators

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Future Enhancements

- [ ] Sync/publish selected prompts to the codyleaf.com web version
- [ ] Duplicate detection on import
- [ ] Bulk tag editing
- [ ] Prompt version history (track edits to a prompt over time)

## Support

If you encounter any issues or have suggestions, please open an issue on GitHub.

## License

MIT License - see LICENSE file for details