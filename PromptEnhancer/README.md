# Prompt Enhancer

Standalone desktop app that turns a rough idea into a structured, model-ready video-generation prompt. Split out of the ComfyUI Chain Automator's Prompt Writer tab as its own app (v1.0.0, 2026-08-22).

## Features

- Rough idea → structured prompt for a chosen target format: **WAN 2.2**, **MiniMax H3** (T2VA / I2VA / FL2VA / L2VA / Ref2VA), or **General**
- Four LLM providers: **Anthropic** (Claude, paid), **Google Gemini**, **Groq**, and **OpenRouter** (each with a free tier)
- Provider and model selectable per generation; model field is editable for custom/new model IDs
- **Live model list**: refresh button fetches each provider's current models from their API; OpenRouter's list is filtered to free-tagged models and needs no key
- Global searchable prompt history (`prompt_history.json` next to the EXE) — reuse or delete past idea/output pairs
- Settings dialog holds one API key per provider

## Layout

| File | Purpose |
|------|---------|
| `main.py` | Entry point, version, taskbar icon fix |
| `config.py` | `ConfigManager` — `main_config.json` next to the EXE |
| `providers.py` | Provider definitions, curated model lists, live model-list fetchers |
| `llm_worker.py` | Background QThread that calls the selected provider's API |
| `ui/` | PyQt6 main window + settings dialog |

## Building the EXE

```
python build_exe.py
```

Deploys to `P:\Apps\AICoded\Prompt Enhancer\`. `main_config.json` (API keys) sits next to the EXE and is never overwritten by a rebuild.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.
