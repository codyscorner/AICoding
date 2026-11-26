# Changelog

## Unreleased
- **Icon-only buttons now have a short text label.** Buttons that showed only a symbol (↻, …, 🎲, 🗑 and so on) now read e.g. "↻ Refresh" or "Browse" in regular-weight, regular-size text; their fixed widths were dropped so they size to their label. Covers: ⟳ Refresh next to the model picker.

## v1.0.1 (2026-08-22)
- **Live model list**: refresh button next to the model picker fetches each provider's current models from their API (Anthropic `/v1/models`, Gemini `/v1beta/models`, Groq and OpenRouter's OpenAI-compatible `/models`) instead of relying only on the static curated list. OpenRouter's list is filtered to free-tagged models and works without an API key (public endpoint).
- AI-generated app icon.

## v1.0.0 (2026-08-22)
- Initial standalone release, split out of the ComfyUI Chain Automator's Prompt Writer tab.
- Rough idea → structured prompt, with target formats: WAN 2.2, MiniMax H3 (T2VA/I2VA/FL2VA/L2VA/Ref2VA), and General.
- Multi-provider support: Anthropic (Claude, paid), Google Gemini, Groq, and OpenRouter (each with a free tier); provider and model are selectable per generation, with editable model field for custom/updated model IDs.
- Global searchable prompt history (prompt_history.json next to the EXE) — reuse or delete past idea/output pairs.
- Settings dialog holds one API key per provider.
