import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QTextEdit, QLineEdit, QComboBox, QApplication,
)

from config import ConfigManager
from llm_worker import PromptWorker, ModelListWorker
from providers import PROVIDERS
from ui.styles import COLORS
from ui.history import HistoryDialog, append_history


def _resources_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "resources"
    return Path(__file__).parent.parent / "resources"


RESOURCES_DIR = _resources_dir()

H3_MODES = ["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]
TARGET_FORMATS = ["WAN 2.2", "MiniMax H3", "General"]

WAN_SYSTEM_PROMPT = """You write video-generation prompts for WAN 2.2 (image-to-video and text-to-video).

WAN prompts are plain, natural-language descriptions — not a multi-field structure. Write one tight paragraph (2-5 sentences) covering, in this rough order:
1. Subject and appearance (who/what is in frame, key visual details).
2. Setting and lighting/style (environment, time of day, art style if relevant).
3. The action or motion that happens over the clip.
4. Camera movement (e.g. slow push in, static shot, pan left, handheld) — only if it adds something.

Keep it concise and concrete — avoid vague mood words, avoid multi-shot cuts unless asked, avoid dialogue/subtitle notation. Output ONLY the final prompt text, nothing else (no preamble, no explanation, no markdown headers)."""

GENERAL_SYSTEM_PROMPT = """You are a prompt-writing assistant. Rewrite the user's rough idea into a clear, well-structured prompt suitable for feeding to another AI model (image, video, text, or chat). Preserve their intent, sharpen vague language into concrete, specific detail, and organize it logically. Output ONLY the final rewritten prompt text, nothing else (no preamble, no explanation, no markdown headers)."""

H3_MODE_NOTES = {
    "T2VA": "Mode: T2VA — build the full audiovisual timeline from text alone, no reference image.",
    "I2VA": "Mode: I2VA — the video starts from a first-frame reference image (<Picture 1>) and develops forward from it. Include the required first-frame instruction line before the core fields.",
    "FL2VA": "Mode: FL2VA — a first-frame and last-frame reference image are both supplied. Describe the continuous path between them. Include the required alignment instruction line before the core fields.",
    "L2VA": "Mode: L2VA — only a last-frame reference image is supplied (<Picture 1> is the final frame). Infer a plausible opening and converge to it. Include the required alignment instruction line before the core fields.",
    "Ref2VA": "Mode: Ref2VA — full-reference mode using subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music in that order, per the Ref2VA guide.",
}


def _load_h3_guide(mode: str) -> str:
    fname = "h3_ref_guide.txt" if mode == "Ref2VA" else "h3_base_guide.txt"
    path = RESOURCES_DIR / fname
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


class PromptTab(QWidget):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self._worker: PromptWorker | None = None
        self._model_worker: ModelListWorker | None = None
        self._build_ui()
        self._restore_state()
        self._on_provider_changed()
        self._on_format_changed()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(10)

        # ── Provider + target format ────────────────────────────────────
        top_group = QGroupBox("Provider && Target Format")
        top_layout = QVBoxLayout(top_group)
        top_layout.setSpacing(8)

        provider_row = QHBoxLayout()
        provider_lbl = QLabel("Provider:")
        provider_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._provider_combo = QComboBox()
        for provider_id, info in PROVIDERS.items():
            self._provider_combo.addItem(info["label"], provider_id)
        self._provider_combo.setFixedHeight(30)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        model_lbl = QLabel("Model:")
        model_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setFixedHeight(30)
        self._model_combo.setMinimumWidth(240)

        self._refresh_models_btn = QPushButton("⟳ Refresh")
        self._refresh_models_btn.setFixedHeight(30)
        self._refresh_models_btn.setToolTip("Fetch the live model list from this provider's API")
        self._refresh_models_btn.clicked.connect(self._on_refresh_models)

        provider_row.addWidget(provider_lbl)
        provider_row.addWidget(self._provider_combo)
        provider_row.addSpacing(16)
        provider_row.addWidget(model_lbl)
        provider_row.addWidget(self._model_combo, stretch=1)
        provider_row.addWidget(self._refresh_models_btn)
        top_layout.addLayout(provider_row)

        format_row = QHBoxLayout()
        format_lbl = QLabel("Format:")
        format_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._format_combo = QComboBox()
        self._format_combo.addItems(TARGET_FORMATS)
        self._format_combo.setFixedHeight(30)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)

        self._mode_lbl = QLabel("H3 Mode:")
        self._mode_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(H3_MODES)
        self._mode_combo.setFixedHeight(30)

        format_row.addWidget(format_lbl)
        format_row.addWidget(self._format_combo)
        format_row.addSpacing(16)
        format_row.addWidget(self._mode_lbl)
        format_row.addWidget(self._mode_combo)
        format_row.addStretch()
        top_layout.addLayout(format_row)

        root.addWidget(top_group)

        # ── Idea input ────────────────────────────────────────────────────
        idea_group = QGroupBox("Rough Idea")
        idea_layout = QVBoxLayout(idea_group)
        idea_layout.setSpacing(6)
        self._idea_edit = QTextEdit()
        self._idea_edit.setPlaceholderText(
            "Describe what you want in plain language — subject, setting, action, mood..."
        )
        self._idea_edit.setFixedHeight(110)
        idea_layout.addWidget(self._idea_edit)

        notes_row = QHBoxLayout()
        notes_lbl = QLabel("Notes:")
        notes_lbl.setStyleSheet(f"color:{COLORS['fg_secondary']}; font-size:10pt;")
        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("Optional — duration, aspect ratio, style hints...")
        notes_row.addWidget(notes_lbl)
        notes_row.addWidget(self._notes_edit, stretch=1)
        idea_layout.addLayout(notes_row)
        root.addWidget(idea_group)

        # ── Generate button + status ─────────────────────────────────────
        btn_row = QHBoxLayout()
        self._gen_btn = QPushButton("✨  Generate Prompt")
        self._gen_btn.setMinimumHeight(40)
        self._gen_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._gen_btn)
        self._history_btn = QPushButton("🕘  History")
        self._history_btn.setMinimumHeight(40)
        self._history_btn.clicked.connect(self._on_history)
        btn_row.addWidget(self._history_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("subtitle")
        root.addWidget(self._status_lbl)

        # ── Output ────────────────────────────────────────────────────────
        out_group = QGroupBox("Generated Prompt")
        out_layout = QVBoxLayout(out_group)
        self._output_edit = QTextEdit()
        self._output_edit.setReadOnly(True)
        self._output_edit.setPlaceholderText("Generated prompt will appear here...")
        out_layout.addWidget(self._output_edit)

        out_btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("📋  Copy")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy)
        out_btn_row.addWidget(self._copy_btn)
        out_btn_row.addStretch()
        out_layout.addLayout(out_btn_row)

        root.addWidget(out_group, stretch=1)

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #

    def _restore_state(self):
        provider_id = self._config.get("provider", "anthropic")
        idx = self._provider_combo.findData(provider_id)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)

        fmt = self._config.get("target_format", "WAN 2.2")
        if fmt in TARGET_FORMATS:
            self._format_combo.setCurrentText(fmt)

        h3_mode = self._config.get("h3_mode", "I2VA")
        if h3_mode in H3_MODES:
            self._mode_combo.setCurrentText(h3_mode)

    def refresh_mode(self):
        """Called when Settings closes — re-check API key state."""
        self._refresh_key_state()

    # ------------------------------------------------------------------ #
    # Behavior
    # ------------------------------------------------------------------ #

    def _current_provider_id(self) -> str:
        return self._provider_combo.currentData()

    def _on_provider_changed(self):
        provider_id = self._current_provider_id()
        self._config.set("provider", provider_id)

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model_id, label in PROVIDERS[provider_id]["models"]:
            self._model_combo.addItem(label, model_id)
        last_model = self._config.get("last_model", {}).get(provider_id)
        if last_model:
            idx = self._model_combo.findData(last_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            else:
                self._model_combo.setCurrentText(last_model)
        self._model_combo.blockSignals(False)

        self._refresh_key_state()

    def _current_model(self) -> str:
        text = self._model_combo.currentText().strip()
        idx = self._model_combo.findText(text)
        if idx >= 0:
            return self._model_combo.itemData(idx)
        return text  # user typed a custom model id not in the curated list

    def _on_format_changed(self):
        fmt = self._format_combo.currentText()
        self._config.set("target_format", fmt)
        is_h3 = fmt == "MiniMax H3"
        self._mode_lbl.setVisible(is_h3)
        self._mode_combo.setVisible(is_h3)

    def _update_button_states(self):
        provider_id = self._current_provider_id()
        has_key = bool(self._config.get(PROVIDERS[provider_id]["key_config"], "").strip())
        busy = self._worker is not None and self._worker.isRunning()
        models_busy = self._model_worker is not None and self._model_worker.isRunning()
        self._gen_btn.setEnabled(has_key and not busy)
        # OpenRouter's model list is public and works without a key.
        self._refresh_models_btn.setEnabled((has_key or provider_id == "openrouter") and not models_busy)

    def _refresh_key_state(self):
        self._update_button_states()
        provider_id = self._current_provider_id()
        has_key = bool(self._config.get(PROVIDERS[provider_id]["key_config"], "").strip())
        busy = self._worker is not None and self._worker.isRunning()
        if not has_key:
            label = PROVIDERS[provider_id]["label"]
            self._status_lbl.setText(f"Set your {label} API key in Settings to use this provider.")
        elif not busy:
            self._status_lbl.setText("")

    def _on_refresh_models(self):
        provider_id = self._current_provider_id()
        api_key = self._config.get(PROVIDERS[provider_id]["key_config"], "").strip()

        self._refresh_models_btn.setEnabled(False)
        self._status_lbl.setText("Fetching model list...")

        self._model_worker = ModelListWorker(provider_id, api_key)
        self._model_worker.result_ready.connect(lambda models: self._on_models_fetched(provider_id, models))
        self._model_worker.error.connect(self._on_error)
        self._model_worker.finished.connect(self._update_button_states)
        self._model_worker.start()

    def _on_models_fetched(self, provider_id: str, models: list):
        if provider_id != self._current_provider_id():
            return  # user switched providers while the request was in flight
        current = self._current_model()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model_id, label in models:
            self._model_combo.addItem(label, model_id)
        idx = self._model_combo.findData(current)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        else:
            self._model_combo.setEditText(current)
        self._model_combo.blockSignals(False)
        self._status_lbl.setText(f"Loaded {len(models)} model(s) from {PROVIDERS[provider_id]['label']}.")

    def _build_system_prompt(self) -> str:
        fmt = self._format_combo.currentText()
        if fmt == "WAN 2.2":
            return WAN_SYSTEM_PROMPT
        if fmt == "General":
            return GENERAL_SYSTEM_PROMPT
        mode = self._mode_combo.currentText()
        guide = _load_h3_guide(mode)
        note = H3_MODE_NOTES.get(mode, "")
        return (
            "You write MiniMax H3 video-generation prompts by following the reference guide below exactly.\n\n"
            f"{note}\n\n"
            "Reference guide:\n"
            f"{guide}\n\n"
            "Output ONLY the final rewritten prompt text in the exact structure defined by the guide, "
            "nothing else (no preamble, no explanation, no markdown code fences)."
        )

    def _on_generate(self):
        idea = self._idea_edit.toPlainText().strip()
        if not idea:
            self._status_lbl.setText("Enter a rough idea first.")
            return

        provider_id = self._current_provider_id()
        api_key = self._config.get(PROVIDERS[provider_id]["key_config"], "").strip()
        if not api_key:
            self._refresh_key_state()
            return

        model = self._current_model()
        if not model:
            self._status_lbl.setText("Enter or pick a model.")
            return

        last_model = self._config.get("last_model", {})
        last_model[provider_id] = model
        self._config.set("last_model", last_model)
        self._config.save()

        notes = self._notes_edit.text().strip()
        user_message = idea if not notes else f"{idea}\n\nAdditional notes: {notes}"

        system_prompt = self._build_system_prompt()

        self._gen_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._status_lbl.setText("Generating...")
        self._output_edit.clear()

        self._worker = PromptWorker(provider_id, model, api_key, system_prompt, user_message)
        self._worker.result_ready.connect(lambda text: self._on_result(text, provider_id, model, idea, notes))
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._update_button_states)
        self._worker.start()

    def _on_result(self, text: str, provider_id: str, model: str, idea: str, notes: str):
        self._output_edit.setPlainText(text)
        self._status_lbl.setText("Done.")
        self._copy_btn.setEnabled(True)
        append_history(self._config.history_path(), {
            "provider": PROVIDERS[provider_id]["label"],
            "model": model,
            "target": self._format_combo.currentText(),
            "idea": idea,
            "notes": notes,
            "output": text,
        })

    def _on_error(self, message: str):
        self._status_lbl.setText(message)

    def _on_copy(self):
        QApplication.clipboard().setText(self._output_edit.toPlainText())
        self._status_lbl.setText("Copied to clipboard.")

    def _on_history(self):
        dlg = HistoryDialog(self._config.history_path(), self)
        if dlg.exec():
            entry = dlg.selected_entry()
            if entry:
                self._idea_edit.setPlainText(entry.get("idea", ""))
                self._notes_edit.setText(entry.get("notes", ""))
                self._output_edit.setPlainText(entry.get("output", ""))
                self._copy_btn.setEnabled(bool(entry.get("output", "").strip()))
                target = entry.get("target", "")
                if target in TARGET_FORMATS:
                    self._format_combo.setCurrentText(target)
                self._status_lbl.setText("Loaded from history.")
