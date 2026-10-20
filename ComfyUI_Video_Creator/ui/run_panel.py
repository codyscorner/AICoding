"""Right-hand panel of each tab: workflow picker, prompt editing (with
pop-out editor and history), LoRA picker, seed/length options, run
controls, progress, log and results."""

from __future__ import annotations

import os
import random
import shutil
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from config import ConfigManager
from run_worker import TEXT_STEM, RunRequest
from ui.clone_dialog import CloneWorkflowDialog
from ui.prompt_history import (
    PromptExpandDialog, PromptHistoryDialog, add_results, append_entry, history_path,
    make_entry,
)
from ui.styles import COLORS
from ui.widgets import ElidedLabel, FilterComboBox, NoScrollComboBox
from workflow_tools import (
    Analysis, LoraSlot, WorkflowError, analyze, apply_inputs, apply_megapixels, apply_steps,
    apply_value, blank_workflow, list_loras, list_workflows, load_workflow, save_workflow,
)

VIDEO_INPUT_MODES = [
    ("auto", "Auto (video node if the workflow has one, else last frame)"),
    ("last_frame", "Last frame → image input (LoadImage)"),
    ("upload_video", "Upload whole video → video input (LoadVideo)"),
]

MAX_LOG_LINES = 600

# Shown when a run about to be queued repeats one that's already queued or
# running (see _confirm_not_a_repeat).
RANDOM_SEED_NOTE = """The seed is random, so the result won't be identical — but every setting you picked is the same."""
FIXED_SEED_NOTE = """The seed is fixed at the same value, so this would render the very same video."""
# Progress-bar sub-units per plan unit (one sampler step or one
# post-sampling node), so a node's own progress fills its slice.
PROGRESS_SUBUNITS = 100

# The positive prompt editor is what gets edited every run, so it takes
# all the slack in the Prompts pane; the negative is a pop-out only.
POSITIVE_PROMPT_MIN_H = 120
# Most of the splitter belongs to the prompts; Options + LoRAs scroll.
LOWER_PANE_MAX_FRACTION = 0.4

# LoRA names are shared by both tabs; scanning the folder once is enough.
_LORA_LIST: dict[str, list[str]] = {}


class _LoraFetchThread(QThread):
    done = pyqtSignal(list, str)   # names, error

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def run(self):
        from comfy_client import ComfyClient
        try:
            self.done.emit(ComfyClient(self._url).list_models("loras"), "")
        except Exception as e:  # noqa: BLE001
            self.done.emit([], f"{type(e).__name__}: {e}")


class _RewriteThread(QThread):
    done = pyqtSignal(str, str)   # rewritten text, error

    def __init__(self, base_url: str, model: str, mode: str, prompt: str,
                 resolution: str, duration: float, references: str):
        super().__init__()
        self._args = (base_url, model, mode, prompt, resolution, duration, references)

    def run(self):
        import prompt_rewriter as pr
        try:
            text = pr.rewrite(*self._args)
            self.done.emit(text, "")
        except pr.RewriterError as e:
            self.done.emit("", str(e))
        except Exception as e:  # noqa: BLE001
            self.done.emit("", f"{type(e).__name__}: {e}")


class _LMStudioCheckThread(QThread):
    done = pyqtSignal(bool, str)   # reachable, error

    def __init__(self, base_url: str):
        super().__init__()
        self._base_url = base_url

    def run(self):
        import prompt_rewriter as pr
        try:
            pr.list_models(self._base_url)
            self.done.emit(True, "")
        except pr.RewriterError as e:
            self.done.emit(False, str(e))
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, f"{type(e).__name__}: {e}")


class RunPanel(QWidget):
    run_requested = pyqtSignal(object)      # RunRequest
    cancel_requested = pyqtSignal()
    clear_queue_requested = pyqtSignal()
    show_queue_requested = pyqtSignal()
    play_requested = pyqtSignal(str)
    workflows_changed = pyqtSignal()        # a workflow file was added — other tabs rescan
    workflow_selected = pyqtSignal(str)     # the selected workflow changed (path relative to the Workflows folder)
    loras_changed = pyqtSignal(str, str)    # the shared LoRA list was reloaded (folder info, server info)

    def __init__(self, kind: str, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.kind = kind                    # "image" | "video" | "text"
        self._cfg = config
        # Set by MainWindow: given a RunRequest, returns a description of the
        # matching run already queued/running, or "" when it's not a repeat.
        self._queue_probe = None
        self._source: Path | None = None
        self._sources: list[Path] = []          # every selected source; Create queues one run each
        self._workflow_path: Path | None = None
        self._workflow_rel = ""
        # Set by load_reused_entry() (Library → Reuse Settings) so a retry
        # with a tweaked prompt doesn't pile "eighty variations of one
        # attempt" into this workflow's history — the video itself already
        # carries the prompt it was made with. Cleared the moment prompt
        # history is used normally again (the History dialog, or picking a
        # workflow by hand), so a later ordinary run still gets recorded.
        self._history_recording_suppressed = False
        self._loading_reused = False
        # Set by load_reused_entry() so a retry made from Reuse Settings
        # lands back in the Library folder its video came from — someone
        # juggling several Library folders would otherwise have every retry
        # dumped into whichever one is the global Output folder right now.
        self._reused_output_dir: Path | None = None
        self._analysis: Analysis | None = None
        self._prompt_edits: list[tuple[object, QTextEdit]] = []        # (PromptField, editor)
        self._lora_rows: list[tuple[LoraSlot, QComboBox, dict[str, QDoubleSpinBox]]] = []
        self._lora_thread: _LoraFetchThread | None = None
        self._lora_folder_info = ""
        self._lora_server_info = ""
        self._rewrite_thread: _RewriteThread | None = None
        self._lm_check_thread: _LMStudioCheckThread | None = None
        self._run_started = 0.0
        # progress bookkeeping
        self._sampler_total = 0
        self._phases_total = 0
        self._phases_seen = 0
        self._phase_label = ""
        self._offset = 0
        self._last_value = 0
        self._last_max = 0

        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── Workflow ────────────────────────────────────────────────────
        wf_group = QGroupBox("Workflow")
        wf_layout = QVBoxLayout(wf_group)
        wf_layout.setSpacing(4)
        row = QHBoxLayout()
        self._wf_combo = FilterComboBox(placeholder="Type any part of a workflow name to filter…")
        self._wf_combo.setMinimumWidth(300)
        self._wf_combo.setToolTip(
            "Workflows found under the Workflows folder. Click and start typing to filter — "
            "any workflow containing what you type stays in the list, wherever the match falls.")
        self._wf_combo.currentIndexChanged.connect(self._on_workflow_changed)
        row.addWidget(self._wf_combo, stretch=1)
        refresh = QPushButton("↻ Refresh")
        refresh.setObjectName("small_btn")
        refresh.setToolTip("Rescan the workflow folder — on every tab (F5 refreshes every list)")
        refresh.clicked.connect(self.rescan_workflows)
        row.addWidget(refresh)
        self._clone_btn = QPushButton("⧉ Clone")
        self._clone_btn.setObjectName("secondary_btn")
        self._clone_btn.setToolTip("Save this workflow under a new name and switch to it, so the "
                                   "original stays exactly as it is")
        self._clone_btn.clicked.connect(self._clone_workflow)
        row.addWidget(self._clone_btn)
        # Blank workflows exist for the two "create from scratch" tabs only;
        # Extend always starts from an existing video's workflow.
        if kind in ("image", "text"):
            self._new_btn = QPushButton("✚ New")
            self._new_btn.setObjectName("secondary_btn")
            self._new_btn.setToolTip("Create a new workflow from the blank template picked in "
                                     "Settings → Prompts, with every prompt empty and every LoRA off")
            self._new_btn.clicked.connect(self._new_blank_workflow)
            row.addWidget(self._new_btn)
        wf_layout.addLayout(row)
        self._wf_status = QLabel("")
        self._wf_status.setObjectName("status_dim")
        self._wf_status.setWordWrap(True)
        wf_layout.addWidget(self._wf_status)
        self._summary = ElidedLabel("")
        self._summary.setObjectName("status_dim")
        wf_layout.addWidget(self._summary)
        root.addWidget(wf_group)

        # ── Splitter: Prompts / (Options + LoRAs) ───────────────────────
        self._split = QSplitter(Qt.Orientation.Vertical)
        self._split.setChildrenCollapsible(False)

        self._prompt_group = QGroupBox("Prompts")
        pg = QVBoxLayout(self._prompt_group)
        pg.setSpacing(4)
        self._prompt_box = QVBoxLayout()
        self._prompt_box.setSpacing(3)
        pg.addLayout(self._prompt_box, stretch=1)

        # AI Prompt Rewriter — off by default, and hidden entirely unless the
        # loaded workflow is recognized MiniMax H3 (workflow_tools.analyze()
        # sets Analysis.minimax_mode). Type a rough idea, hit Rewrite, review
        # the result in the same box before running — never auto-fires.
        rewrite_row = QHBoxLayout()
        rewrite_row.setSpacing(6)
        self._rewriter_chk = QCheckBox("🪄 AI Rewriter")
        self._rewriter_chk.setToolTip(
            "Turn a rough scene idea into a full MiniMax H3 prompt using a local "
            "LM Studio model (configure the URL and model in Settings first)")
        self._rewriter_chk.toggled.connect(self._on_rewriter_toggled)
        rewrite_row.addWidget(self._rewriter_chk)
        self._rewriter_ref = QLineEdit()
        self._rewriter_ref.setPlaceholderText(
            "Describe the reference image, e.g. Picture 1: young woman, dark hair, blue jacket")
        self._rewriter_ref.setVisible(False)
        rewrite_row.addWidget(self._rewriter_ref, stretch=1)
        self._rewrite_btn = QPushButton("✨ Rewrite")
        self._rewrite_btn.setObjectName("secondary_btn")
        self._rewrite_btn.setVisible(False)
        self._rewrite_btn.clicked.connect(self._on_rewrite_clicked)
        rewrite_row.addWidget(self._rewrite_btn)
        pg.addLayout(rewrite_row)
        self._rewriter_chk.setVisible(False)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Text size:"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(7, 20)
        self._font_spin.setValue(int(config.get("prompt_font_size", 10) or 10))
        self._font_spin.setFixedWidth(60)
        self._font_spin.valueChanged.connect(self._apply_font_size)
        prow.addWidget(self._font_spin)
        prow.addStretch()
        self._history_btn = QPushButton("📜 History")
        self._history_btn.setObjectName("secondary_btn")
        self._history_btn.setToolTip("Every run is recorded with its prompt, LoRAs, seed and length — search and reload them here")
        self._history_btn.clicked.connect(self._open_history)
        prow.addWidget(self._history_btn)
        self._reload_btn = QPushButton("↺ Reload")
        self._reload_btn.setObjectName("secondary_btn")
        self._reload_btn.setToolTip("Discard edits and reload prompts and LoRAs from the workflow file")
        self._reload_btn.clicked.connect(self._reload_workflow)
        prow.addWidget(self._reload_btn)
        self._save_btn = QPushButton("💾 Save to workflow")
        self._save_btn.setObjectName("secondary_btn")
        self._save_btn.setToolTip("Write the prompts, LoRAs and length shown here back into the workflow JSON")
        self._save_btn.clicked.connect(self._save_to_workflow)
        prow.addWidget(self._save_btn)
        pg.addLayout(prow)
        self._split.addWidget(self._prompt_group)

        lower = QScrollArea()
        lower.setWidgetResizable(True)
        lower.setFrameShape(QScrollArea.Shape.NoFrame)
        lower.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lower_inner = QWidget()
        ll = QVBoxLayout(lower_inner)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(6)

        # ── Options ─────────────────────────────────────────────────────
        opt_group = QGroupBox("Options")
        og = QVBoxLayout(opt_group)
        og.setSpacing(5)
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Seed:"))
        self._seed_mode = NoScrollComboBox()
        self._seed_mode.addItems(["Random", "Fixed"])
        self._seed_mode.setFixedWidth(96)
        self._seed_mode.setToolTip("Random: a new seed every run. Fixed: use the seed on the right.")
        self._seed_mode.setCurrentIndex(1 if config.get("seed_mode", "random") == "fixed" else 0)
        self._seed_mode.currentIndexChanged.connect(self._on_seed_mode)
        seed_row.addWidget(self._seed_mode)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 2_147_483_647)
        self._seed_spin.setValue(int(config.get("seed_value", 0) or 0))
        self._seed_spin.setMinimumWidth(140)
        self._seed_spin.valueChanged.connect(self._on_seed_value)
        seed_row.addWidget(self._seed_spin)
        dice = QPushButton("🎲 Random")
        dice.setObjectName("small_btn")
        dice.setToolTip("Pick a new fixed seed")
        dice.clicked.connect(lambda: self._seed_spin.setValue(random.randint(0, 2_147_483_647)))
        seed_row.addWidget(dice)
        seed_row.addSpacing(14)
        self._steps_lbl = QLabel("Steps:")
        seed_row.addWidget(self._steps_lbl)
        self._steps_spin = QSpinBox()
        self._steps_spin.setRange(1, 200)
        self._steps_spin.setFixedWidth(70)
        self._steps_spin.setToolTip("Sampler steps — more = slower but usually cleaner; fewer for quick tests")
        self._steps_spin.valueChanged.connect(lambda _v: self._update_summary())
        seed_row.addWidget(self._steps_spin)
        seed_row.addStretch()
        og.addLayout(seed_row)

        size_row = QHBoxLayout()
        self._mp_lbl = QLabel("Megapixels:")
        size_row.addWidget(self._mp_lbl)
        self._mp_spin = QDoubleSpinBox()
        self._mp_spin.setRange(0.05, 8.0)
        self._mp_spin.setDecimals(2)
        self._mp_spin.setSingleStep(0.05)
        self._mp_spin.setFixedWidth(84)
        self._mp_spin.setToolTip(
            "Output size in megapixels — smaller for quick tests, larger for production.\n"
            "Ignored while 'Append the new clip' is ticked: the source video's size wins.")
        self._mp_spin.valueChanged.connect(lambda _v: self._update_summary())
        size_row.addWidget(self._mp_spin)
        size_row.addStretch()
        self._length_lbl = QLabel("Length:")
        size_row.addWidget(self._length_lbl)
        self._length_spin = QDoubleSpinBox()
        self._length_spin.setMinimumWidth(110)
        self._length_spin.valueChanged.connect(lambda _v: self._update_summary())
        size_row.addWidget(self._length_spin)
        og.addLayout(size_row)

        turbo_row = QHBoxLayout()
        self._turbo_chk = QCheckBox("⚡ Turbo LoRA + Sampler")
        self._turbo_chk.setToolTip(
            "Turbo LoRAs trade quality for speed at a very low step count. Turning this off runs "
            "the standard sampler instead — needs a much higher step count to look clean, but no "
            "turbo shortcut artifacts.")
        self._turbo_chk.toggled.connect(lambda _v: self._update_turbo_warning())
        turbo_row.addWidget(self._turbo_chk)
        self._turbo_warn = QLabel("⚠ Turbo is off and steps is below 15 — quality will likely be poor")
        self._turbo_warn.setStyleSheet(f"color: {COLORS['warning']};")
        self._turbo_warn.setVisible(False)
        turbo_row.addWidget(self._turbo_warn)
        turbo_row.addStretch()
        og.addLayout(turbo_row)
        self._steps_spin.valueChanged.connect(lambda _v: self._update_turbo_warning())

        self._on_seed_mode()

        if kind == "video":
            mode_row = QHBoxLayout()
            mode_row.addWidget(QLabel("Video input:"))
            self._input_mode = NoScrollComboBox()
            for key, label in VIDEO_INPUT_MODES:
                self._input_mode.addItem(label, key)
            current = config.get("video_input_mode", "auto")
            for i, (key, _) in enumerate(VIDEO_INPUT_MODES):
                if key == current:
                    self._input_mode.setCurrentIndex(i)
            self._input_mode.currentIndexChanged.connect(
                lambda _i: self._cfg.set("video_input_mode", self._input_mode.currentData()))
            mode_row.addWidget(self._input_mode, stretch=1)
            og.addLayout(mode_row)
            self._stitch_chk = QCheckBox(
                "Append the new clip to the source video "
                "(matches the source's frame size, saves <name>_extended.mp4 as well)")
            self._stitch_chk.setToolTip(
                "The new clip is generated at the source video's own resolution so the two join "
                "cleanly, and the joined file is written alongside the clip.")
            self._stitch_chk.setChecked(bool(config.get("extend_stitch", True)))
            self._stitch_chk.toggled.connect(lambda v: self._cfg.set("extend_stitch", bool(v)))
            self._stitch_chk.toggled.connect(lambda _v: self._update_summary())
            og.addWidget(self._stitch_chk)
        else:
            self._input_mode = None
            self._stitch_chk = None
        ll.addWidget(opt_group)

        # ── LoRAs ───────────────────────────────────────────────────────
        self._lora_group = QGroupBox("LoRAs")
        lg = QVBoxLayout(self._lora_group)
        lg.setSpacing(5)
        tool = QHBoxLayout()
        tool.addWidget(QLabel("LoRA list:"))
        folder_btn = QPushButton("↻ Folder")
        folder_btn.setObjectName("secondary_btn")
        folder_btn.setToolTip("Rescan the LoRAs folder set in Settings")
        folder_btn.clicked.connect(self.reload_loras_from_folder)
        tool.addWidget(folder_btn)
        self._server_btn = QPushButton("⇣ Server")
        self._server_btn.setObjectName("secondary_btn")
        self._server_btn.setToolTip("Ask the connected ComfyUI (local or RunPod) which LoRAs it has")
        self._server_btn.clicked.connect(self._fetch_loras_from_server)
        tool.addWidget(self._server_btn)
        self._lora_status = QLabel("")
        self._lora_status.setObjectName("status_dim")
        tool.addWidget(self._lora_status, stretch=1)
        lg.addLayout(tool)
        self._lora_grid = QGridLayout()
        self._lora_grid.setHorizontalSpacing(6)
        self._lora_grid.setVerticalSpacing(4)
        self._lora_grid.setColumnStretch(1, 1)
        lg.addLayout(self._lora_grid)
        ll.addWidget(self._lora_group)
        ll.addStretch()
        lower.setWidget(lower_inner)
        self._lower_inner = lower_inner
        self._split.addWidget(lower)
        self._split.setStretchFactor(0, 3)
        self._split.setStretchFactor(1, 2)
        self._split.splitterMoved.connect(self._on_split_moved)
        root.addWidget(self._split, stretch=1)

        # ── Run controls ────────────────────────────────────────────────
        run_row = QHBoxLayout()
        self._source_thumb = QLabel()
        self._source_thumb.setFixedSize(48, 48)
        self._source_thumb.setStyleSheet(
            f"border: 1px solid {COLORS['border']}; background: {COLORS['bg_light']};")
        self._source_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source_thumb.setVisible(False)
        run_row.addWidget(self._source_thumb)
        self._source_lbl = QLabel("No image selected" if kind == "image" else "No video selected")
        self._source_lbl.setObjectName("status_dim")
        self._source_lbl.setWordWrap(True)
        run_row.addWidget(self._source_lbl, stretch=1)
        if kind == "text":
            # Nothing to select on this tab — the prompt is the whole input —
            # so there's no source to name the file after. The box takes the
            # source label's place; blank falls back to a plain marker.
            self._source_thumb.setVisible(False)
            self._source_lbl.setVisible(False)
            run_row.addWidget(QLabel("Output name:"))
            self._name_edit = QLineEdit()
            self._name_edit.setPlaceholderText(
                f"blank = {TEXT_STEM}   ·   e.g. rain_walk  →  rain_walk_<workflow>_<timestamp>.mp4")
            self._name_edit.setToolTip(
                "There's no source image to name the clip after, so type a name here.\n"
                f"Saved as <name>_<workflow>_<timestamp>.mp4 in the Output folder; blank uses {TEXT_STEM}.")
            self._name_edit.setText(str(config.get("text_output_name", "") or ""))
            self._name_edit.textChanged.connect(lambda t: self._cfg.set("text_output_name", t.strip()))
            run_row.addWidget(self._name_edit, stretch=1)
        else:
            self._name_edit = None
        self._run_btn = QPushButton("▶  Extend Video" if kind == "video" else "▶  Create Video")
        self._run_btn.setObjectName("run_btn")
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)
        self._cancel_btn = QPushButton("✕ Cancel")
        self._cancel_btn.setObjectName("cancel_btn")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        run_row.addWidget(self._cancel_btn)
        root.addLayout(run_row)

        # Shown only while requests are waiting behind the current run —
        # right under the button being clicked, not tucked in the header,
        # since that's where a queued-up click actually needs to be seen.
        queue_row = QHBoxLayout()
        queue_row.setSpacing(8)
        self._queue_lbl = QLabel("")
        self._queue_lbl.setStyleSheet(f"color: {COLORS['warning']}; font-weight: bold;")
        queue_row.addWidget(self._queue_lbl)
        self._view_queue_btn = QPushButton("📋 View Queue…")
        self._view_queue_btn.setObjectName("secondary_btn")
        self._view_queue_btn.setToolTip("See every run waiting its turn — workflow, source, prompt and settings")
        self._view_queue_btn.clicked.connect(self.show_queue_requested.emit)
        queue_row.addWidget(self._view_queue_btn)
        self._clear_queue_btn = QPushButton("✕ Clear Queue")
        self._clear_queue_btn.setObjectName("secondary_btn")
        self._clear_queue_btn.clicked.connect(self.clear_queue_requested.emit)
        queue_row.addWidget(self._clear_queue_btn)
        queue_row.addStretch()
        root.addLayout(queue_row)
        self._queue_lbl.setVisible(False)
        self._view_queue_btn.setVisible(False)
        self._clear_queue_btn.setVisible(False)

        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("")
        self._progress.setFixedHeight(18)
        prog_row.addWidget(self._progress, stretch=1)
        self._progress_lbl = QLabel("Idle")
        self._progress_lbl.setObjectName("status_dim")
        self._progress_lbl.setMinimumWidth(220)
        self._progress_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self._progress_lbl)
        root.addLayout(prog_row)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick)

        # ── Log | Results ───────────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._log = QListWidget()
        self._log.setMinimumHeight(90)
        self._log.setMaximumHeight(130)
        self._log.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        bottom.addWidget(self._log, stretch=3)
        res_group = QGroupBox("Results")
        res_group.setMaximumHeight(130)
        rg = QVBoxLayout(res_group)
        rg.setSpacing(3)
        rg.setContentsMargins(6, 4, 6, 4)
        self._results_list = QListWidget()
        self._results_list.setStyleSheet("QListWidget { font-family: 'Segoe UI'; font-size: 9pt; }")
        self._results_list.itemDoubleClicked.connect(
            lambda it: self.play_requested.emit(it.data(Qt.ItemDataRole.UserRole)))
        rg.addWidget(self._results_list, stretch=1)
        rrow = QHBoxLayout()
        rrow.setSpacing(4)
        play_btn = QPushButton("▶ Play")
        play_btn.setObjectName("secondary_btn")
        play_btn.clicked.connect(self._play_selected)
        rrow.addWidget(play_btn)
        open_btn = QPushButton("📂 Folder")
        open_btn.setObjectName("secondary_btn")
        open_btn.clicked.connect(self._open_result_folder)
        rrow.addWidget(open_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("secondary_btn")
        clear_btn.clicked.connect(self._results_list.clear)
        rrow.addWidget(clear_btn)
        rrow.addStretch()
        rg.addLayout(rrow)
        bottom.addWidget(res_group, stretch=2)
        root.addLayout(bottom)

        self._split_restored = False
        self.reload_loras_from_folder(quiet=True)
        self.reload_workflows()
        self._update_run_enabled()

    # ------------------------------------------------------------------ #
    # Splitter persistence
    # ------------------------------------------------------------------ #

    def _split_key(self) -> str:
        return f"panel_split_{self.kind}"

    def showEvent(self, event):
        super().showEvent(event)
        if not self._split_restored:
            self._split_restored = True
            QTimer.singleShot(0, self._restore_split)

    def _restore_split(self):
        sizes = self._cfg.get(self._split_key(), []) or []
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(x, int) and x > 0 for x in sizes):
            self._split.setSizes(sizes)
            return
        # Default: give Options + LoRAs exactly what they need (up to half),
        # the prompts get the rest. The user can drag from there.
        total = sum(self._split.sizes()) or self._split.height()
        if total <= 0:
            return
        want_lower = min(self._lower_inner.sizeHint().height() + 12,
                         int(total * LOWER_PANE_MAX_FRACTION))
        self._split.setSizes([max(total - want_lower, 120), want_lower])

    def _on_split_moved(self, *_):
        self._cfg.set(self._split_key(), list(self._split.sizes()))

    # ------------------------------------------------------------------ #
    # Workflows
    # ------------------------------------------------------------------ #

    def _config_key(self) -> str:
        return {"image": "image_workflow", "video": "video_workflow", "text": "text_workflow"}[self.kind]

    def reload_workflows(self):
        wf_dir = Path((self._cfg.get("workflow_dir", "") or "").strip())
        rels = list_workflows(wf_dir) if str(wf_dir) else []
        remembered = self._cfg.get(self._config_key(), "") or self._workflow_rel
        self._wf_combo.blockSignals(True)
        self._wf_combo.clear()
        for rel in rels:
            self._wf_combo.addItem(rel, rel)
        self._wf_combo.blockSignals(False)
        if not rels:
            self._workflow_path = None
            self._analysis = None
            self._set_wf_status(
                "No workflow JSON files found — set the Workflows folder in Settings." if not wf_dir.is_dir()
                else f"No .json workflows in {wf_dir}", ok=False)
            self._rebuild_prompts()
            self._rebuild_loras()
            self._update_run_enabled()
            return
        idx = self._wf_combo.findData(remembered) if remembered else -1
        self._wf_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_workflow_changed(self._wf_combo.currentIndex())

    def rescan_workflows(self):
        """The ↻ button: a workflow renamed or added on disk shows up here and
        on the other tabs, which keep their own selection and edits."""
        self.reload_workflows()
        self.workflows_changed.emit()

    def refresh_workflow_list(self):
        """Repopulate the dropdown after a workflow file was added elsewhere,
        keeping this panel's selection and its unsaved edits."""
        wf_dir = Path((self._cfg.get("workflow_dir", "") or "").strip())
        rels = list_workflows(wf_dir) if str(wf_dir) else []
        if not (self._workflow_rel in rels and self._analysis is not None):
            self.reload_workflows()
            return
        self._wf_combo.blockSignals(True)
        self._wf_combo.clear()
        for rel in rels:
            self._wf_combo.addItem(rel, rel)
        self._wf_combo.setCurrentIndex(self._wf_combo.findData(self._workflow_rel))
        self._wf_combo.blockSignals(False)

    def _on_workflow_changed(self, _idx: int):
        rel = self._wf_combo.currentData()
        if not rel:
            return
        if not self._loading_reused:
            self._history_recording_suppressed = False
            self._reused_output_dir = None
        self._workflow_rel = rel
        self._cfg.set(self._config_key(), rel)
        self._workflow_path = Path(self._cfg.get("workflow_dir", "")) / rel
        self._load_analysis()
        self.workflow_selected.emit(rel)

    @property
    def workflow_rel(self) -> str:
        """The selected workflow, relative to the Workflows folder ("" before one is chosen)."""
        return self._workflow_rel or ""

    def _reload_workflow(self):
        if self._workflow_path is not None:
            self._load_analysis()

    def _load_analysis(self):
        try:
            wf = load_workflow(self._workflow_path)
            self._analysis = analyze(wf)
        except WorkflowError as e:
            self._analysis = None
            self._set_wf_status(str(e), ok=False)
            self._rebuild_prompts()
            self._rebuild_loras()
            self._update_run_enabled()
            return
        a = self._analysis
        problems = []
        if self.kind == "image" and not a.accepts_image:
            problems.append("no image input node (LoadImage) — pick an image-to-video workflow")
        if self.kind == "video" and not (a.accepts_image or a.accepts_video):
            problems.append("no video or image input node")
        if self.kind == "text":
            if a.accepts_image or a.accepts_video:
                problems.append("takes an image/video input — this tab runs prompt-only workflows "
                                "(no LoadImage / LoadVideo node); use Image → Video or Video → Extend for it")
            elif not a.prompts:
                problems.append("no prompt text to edit — nothing to generate from")
        if not a.output_nodes:
            problems.append("no SaveVideo / VHS_VideoCombine node — nothing will be downloaded")
        if problems:
            self._set_wf_status("⚠ " + "; ".join(problems) + f"\n{a.describe()}", ok=False)
        else:
            self._set_wf_status("✓ " + a.describe(), ok=True)
        self._rebuild_prompts()
        self._rebuild_loras()
        self._update_run_enabled()

    def _set_wf_status(self, text: str, ok: bool):
        self._wf_status.setObjectName("status_ok" if ok else "status_err")
        self._wf_status.setStyleSheet("")   # re-polish for the new objectName
        self._wf_status.setText(text)

    # ------------------------------------------------------------------ #
    # Prompts / length
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                RunPanel._clear_layout(item.layout())

    def _rebuild_prompts(self):
        self._clear_layout(self._prompt_box)
        self._prompt_edits = []
        a = self._analysis
        if a is None or not a.prompts:
            lbl = QLabel("This workflow exposes no editable prompt text." if a is not None else "")
            lbl.setObjectName("status_dim")
            self._prompt_box.addWidget(lbl)
            self._prompt_box.addStretch()
        else:
            for pf in a.prompts:
                # The negative prompt is boilerplate that is hardly ever
                # touched (WAN 2.2 and friends still need one), so it gets a
                # single row — label, one-line preview, ⤢ Edit — and its
                # editor is hidden. The whole pane goes to the positive
                # prompt, which is what gets rewritten every run.
                if pf.negative:
                    edit = self._negative_row(pf)
                else:
                    edit = self._positive_editor(pf)
                self._prompt_edits.append((pf, edit))
            if all(pf.negative for pf in a.prompts):
                self._prompt_box.addStretch()
        self._apply_font_size(self._font_spin.value())
        self._update_rewriter_visibility()

        fld = a.length_field if a is not None else None
        visible = fld is not None
        self._length_lbl.setVisible(visible)
        self._length_spin.setVisible(visible)
        if fld is not None:
            self._length_lbl.setText(fld.label + ":")
            self._length_spin.blockSignals(True)
            if fld.kind == "int":
                self._length_spin.setDecimals(0)
                self._length_spin.setRange(1, 100000)
                self._length_spin.setSingleStep(1)
            else:
                self._length_spin.setDecimals(1)
                self._length_spin.setRange(0.1, 600.0)
                self._length_spin.setSingleStep(0.5)
            self._length_spin.setValue(fld.value)
            self._length_spin.blockSignals(False)

        steps = a.steps_fields if a is not None else []
        self._steps_lbl.setVisible(bool(steps))
        self._steps_spin.setVisible(bool(steps))
        if steps:
            self._steps_spin.blockSignals(True)
            self._steps_spin.setValue(steps[0].value)
            self._steps_spin.blockSignals(False)
            names = ", ".join(f"{f.label} ({f.value})" for f in steps)
            self._steps_spin.setToolTip(
                f"Sampler steps applied to {len(steps)} node{'s' if len(steps) != 1 else ''}: {names}. "
                "WAN hi/lo pairs keep their split point proportional.")

        turbo = a.turbo if a is not None else None
        self._turbo_chk.setVisible(turbo is not None)
        if turbo is not None:
            self._turbo_chk.blockSignals(True)
            self._turbo_chk.setChecked(turbo.currently_on)
            self._turbo_chk.blockSignals(False)
        self._update_turbo_warning()

        mps = a.mp_fields if a is not None else []
        self._mp_lbl.setVisible(bool(mps))
        self._mp_spin.setVisible(bool(mps))
        if mps:
            self._mp_spin.blockSignals(True)
            self._mp_spin.setValue(mps[0].value)
            self._mp_spin.blockSignals(False)
            names = ", ".join(f"{f.label} ({f.value:g})" for f in mps)
            self._mp_spin.setToolTip(f"Megapixels applied to {len(mps)} node{'s' if len(mps) != 1 else ''}: {names}")
        self._update_summary()

    # ------------------------------------------------------------------ #
    # AI Prompt Rewriter
    # ------------------------------------------------------------------ #

    def _update_rewriter_visibility(self):
        mode = self._analysis.minimax_mode if self._analysis is not None else None
        self._rewriter_chk.setVisible(mode is not None)
        if mode is None:
            self._rewriter_chk.setChecked(False)
        self._on_rewriter_toggled(self._rewriter_chk.isChecked())

    def _on_rewriter_toggled(self, checked: bool):
        mode = self._analysis.minimax_mode if self._analysis is not None else None
        self._rewrite_btn.setVisible(checked and mode is not None)
        self._rewriter_ref.setVisible(checked and mode == "Ref2VA")
        if checked and mode is not None:
            self.refresh_rewriter_status()

    def refresh_rewriter_status(self):
        """Re-checks LM Studio and enables/grays the Rewrite button accordingly.
        Never a hard requirement to use the app - just off until it's reachable."""
        if not self._rewrite_btn.isVisible():
            return
        base_url = self._cfg.get("rewriter_base_url", "").strip()
        model = self._cfg.get("rewriter_model", "").strip()
        if not base_url or not model:
            self._rewrite_btn.setEnabled(False)
            self._rewrite_btn.setToolTip("Set the LM Studio URL and pick a model in Settings → AI Prompt Rewriter first.")
            return
        self._rewrite_btn.setEnabled(False)
        self._rewrite_btn.setToolTip(f"Checking {base_url} …")
        self._lm_check_thread = _LMStudioCheckThread(base_url)
        self._lm_check_thread.done.connect(self._on_lm_check_done)
        self._lm_check_thread.start()

    def _on_lm_check_done(self, reachable: bool, error: str):
        self._rewrite_btn.setEnabled(reachable)
        self._rewrite_btn.setToolTip(
            "" if reachable else f"LM Studio isn't reachable — the app works fine without it.\n{error}")

    def _first_positive_edit(self) -> QTextEdit | None:
        for pf, edit in self._prompt_edits:
            if not pf.negative:
                return edit
        return None

    def _on_rewrite_clicked(self):
        mode = self._analysis.minimax_mode if self._analysis is not None else None
        if mode is None:
            return
        edit = self._first_positive_edit()
        if edit is None:
            return
        rough = edit.toPlainText().strip()
        if not rough:
            QMessageBox.information(self, "Nothing to rewrite", "Type a rough scene idea in the prompt box first.")
            return
        base_url = self._cfg.get("rewriter_base_url", "")
        model = self._cfg.get("rewriter_model", "")
        if not base_url.strip() or not model.strip():
            QMessageBox.warning(self, "Not configured",
                                 "Set the LM Studio URL and pick a model in Settings → AI Prompt Rewriter first.")
            return
        duration = float(self._length_spin.value()) if self._analysis.length_field is not None else 10.0
        resolution = self._analysis.aspect_ratio
        references = self._rewriter_ref.text().strip()
        self._rewrite_btn.setEnabled(False)
        self._rewrite_btn.setText("Rewriting…")
        self._rewrite_thread = _RewriteThread(base_url, model, mode, rough, resolution, duration, references)
        self._rewrite_thread.done.connect(lambda text, err, edit=edit: self._on_rewrite_done(edit, text, err))
        self._rewrite_thread.start()

    def _on_rewrite_done(self, edit: QTextEdit, text: str, error: str):
        self._rewrite_btn.setEnabled(True)
        self._rewrite_btn.setText("✨ Rewrite")
        if error:
            QMessageBox.warning(self, "Rewrite failed", error)
            return
        edit.setPlainText(text)

    def _hidden_editor(self, pf) -> QTextEdit:
        """The real editor every prompt keeps — overrides, history, save to
        workflow and font size all read it. Added to the layout (hidden ones
        take no space) so a rebuild disposes of it with everything else."""
        edit = QTextEdit()
        edit.setAcceptRichText(False)
        edit.setPlainText(pf.text)
        self._prompt_box.addWidget(edit)
        return edit

    def _positive_editor(self, pf) -> QTextEdit:
        head = QHBoxLayout()
        lbl = QLabel(pf.label)
        lbl.setStyleSheet(f"color: {COLORS['fg_secondary']}; font-weight: bold;")
        head.addWidget(lbl)
        head.addStretch()
        expand = QPushButton("⤢ Expand")
        expand.setObjectName("small_btn")
        expand.setToolTip("Edit this prompt in a large separate window")
        head.addWidget(expand)
        self._prompt_box.addLayout(head)
        edit = self._hidden_editor(pf)
        edit.setVisible(True)
        edit.setMinimumHeight(POSITIVE_PROMPT_MIN_H)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._prompt_box.setStretchFactor(edit, 1)
        expand.clicked.connect(lambda _c, e=edit, t=pf.label: self._expand_prompt(e, t))
        return edit

    def _negative_row(self, pf) -> QTextEdit:
        row = QHBoxLayout()
        lbl = QLabel(pf.label)
        lbl.setStyleSheet(f"color: {COLORS['fg_secondary']}; font-weight: bold;")
        row.addWidget(lbl)
        preview = ElidedLabel("")
        preview.setObjectName("status_dim")
        row.addWidget(preview, stretch=1)
        edit_btn = QPushButton("⤢ Edit")
        edit_btn.setObjectName("small_btn")
        edit_btn.setToolTip("Edit the negative prompt in a large separate window")
        row.addWidget(edit_btn)
        self._prompt_box.addLayout(row)
        edit = self._hidden_editor(pf)
        edit.setVisible(False)
        # textChanged keeps the preview honest however the text arrives —
        # the pop-out, a history recall, or "Use prompt + settings".
        edit.textChanged.connect(
            lambda e=edit, p=preview: p.setFullText(" ".join(e.toPlainText().split())))
        preview.setFullText(" ".join(edit.toPlainText().split()))
        edit_btn.clicked.connect(lambda _c, e=edit, t=pf.label: self._expand_prompt(e, t))
        return edit

    def _expand_prompt(self, edit: QTextEdit, title: str):
        dlg = PromptExpandDialog(title, edit.toPlainText(), edit.font(), self)
        if dlg.exec() == PromptExpandDialog.DialogCode.Accepted:
            edit.setPlainText(dlg.text())

    def _apply_font_size(self, size: int):
        self._cfg.set("prompt_font_size", int(size))
        # The app stylesheet pins QWidget font-size, which beats setFont(), so
        # the size has to go in as a widget-level stylesheet rule to take effect.
        font = QFont("Segoe UI", int(size))
        for _pf, edit in self._prompt_edits:
            edit.setFont(font)
            edit.setStyleSheet(f"QTextEdit {{ font-size: {int(size)}pt; }}")

    def _prompt_overrides(self) -> dict[tuple[str, str], str]:
        return {(pf.node_id, pf.key): edit.toPlainText() for pf, edit in self._prompt_edits}

    def _prompt_tuples(self) -> list[tuple[str, str, str, bool, str]]:
        return [(pf.node_id, pf.key, pf.label, pf.negative, edit.toPlainText()) for pf, edit in self._prompt_edits]

    def _write_panel_edits(self, path: Path):
        """Write the prompts, LoRAs, steps, megapixels and length shown here into `path`."""
        wf = load_workflow(path)
        apply_inputs(wf, self._prompt_overrides())
        apply_inputs(wf, self._lora_edits())
        if self._analysis.length_field is not None:
            apply_value(wf, self._analysis.length_field, self._length_spin.value())
        fresh = analyze(wf)
        if fresh.steps_fields:
            apply_steps(wf, fresh.steps_fields, int(self._steps_spin.value()))
        if fresh.mp_fields:
            apply_megapixels(wf, fresh.mp_fields, float(self._mp_spin.value()))
        save_workflow(path, wf)

    def _save_to_workflow(self):
        if self._workflow_path is None or self._analysis is None:
            return
        try:
            self._write_panel_edits(self._workflow_path)
            append_entry(self._workflow_path, make_entry(self._prompt_tuples(), self._collect_settings(),
                                                         self._source.name if self._source else ""))
            self.append_log(f"Saved prompts, LoRAs, steps, megapixels and length to {self._workflow_path.name} (and to history)")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(e))

    # ------------------------------------------------------------------ #
    # Cloning
    # ------------------------------------------------------------------ #

    def _clone_workflow(self):
        """Copy the selected workflow to a new name and select the copy."""
        wf_dir = Path((self._cfg.get("workflow_dir", "") or "").strip())
        if self._workflow_path is None or not wf_dir.is_dir():
            QMessageBox.information(self, "Clone workflow",
                                    "Pick a workflow first (set the Workflows folder in Settings).")
            return
        if not self._workflow_path.exists():
            QMessageBox.warning(self, "Clone workflow",
                                f"{self._workflow_path.name} is no longer on disk — press ↻ to rescan.")
            return

        dlg = CloneWorkflowDialog(wf_dir, self._workflow_rel, self._analysis is not None, self)
        if dlg.exec() != CloneWorkflowDialog.DialogCode.Accepted:
            return
        target = dlg.result_path()
        if target is None:
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._workflow_path, target)
            if dlg.with_edits() and self._analysis is not None:
                self._write_panel_edits(target)
            if dlg.with_history():
                src_hist = history_path(self._workflow_path)
                if src_hist.exists():
                    shutil.copy2(src_hist, history_path(target))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Clone failed", f"Could not create {target.name}:\n{e}")
            return

        rel = target.relative_to(wf_dir).as_posix()
        source_name = self._workflow_path.name
        self._cfg.set(self._config_key(), rel)
        self.reload_workflows()
        detail = " with the edits shown here" if dlg.with_edits() and self._analysis is not None else ""
        self.append_log(f"Cloned {source_name} → {rel}{detail} — now editing the clone")
        self.workflows_changed.emit()

    def _new_blank_workflow(self):
        """Copy the Settings template for this tab under a new name, with every
        prompt emptied and every LoRA off, and select it."""
        wf_dir = Path((self._cfg.get("workflow_dir", "") or "").strip())
        tab = "Image → Video" if self.kind == "image" else "Text → Video"
        template_rel = (self._cfg.get(f"{self.kind}_blank_template", "") or "").strip()
        if not template_rel or not wf_dir.is_dir():
            QMessageBox.information(
                self, "New blank workflow",
                f"No blank template is set for the {tab} tab.\n\n"
                f"Pick one in Settings → Prompts → New blank workflow.")
            return
        template = wf_dir / template_rel
        if not template.exists():
            QMessageBox.warning(
                self, "New blank workflow",
                f"The {tab} blank template {template_rel} is no longer in the Workflows folder.\n\n"
                f"Pick another in Settings → Prompts → New blank workflow.")
            return

        dlg = CloneWorkflowDialog(wf_dir, template_rel, False, self, blank=True)
        if dlg.exec() != CloneWorkflowDialog.DialogCode.Accepted:
            return
        target = dlg.result_path()
        if target is None:
            return

        try:
            wf = load_workflow(template)
            prompts, loras = blank_workflow(wf)
            target.parent.mkdir(parents=True, exist_ok=True)
            save_workflow(target, wf)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "New workflow failed", f"Could not create {target.name}:\n{e}")
            return

        rel = target.relative_to(wf_dir).as_posix()
        self._cfg.set(self._config_key(), rel)
        self.reload_workflows()
        self.append_log(f"New workflow {rel} from template {template_rel} — "
                        f"{prompts} prompt(s) emptied, {loras} LoRA(s) switched off")
        self.workflows_changed.emit()

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #

    def _open_history(self):
        if self._workflow_path is None:
            return
        wf_dir = Path((self._cfg.get("workflow_dir", "") or "").strip())
        dlg = PromptHistoryDialog(self._workflow_path, self, workflow_dir=wf_dir if str(wf_dir) else None)
        dlg.use_prompt.connect(lambda e: self._apply_history(e, with_settings=False))
        dlg.use_all.connect(lambda e: self._apply_history(e, with_settings=True))
        dlg.exec()

    def load_reused_entry(self, workflow_rel: str, entry: dict, output_dir: Path | None = None) -> bool:
        """Library → Reuse Settings: select `workflow_rel` if it's still on
        disk, then apply the entry's prompt + settings on top of it. Runs
        made from here don't get logged to history until a workflow is
        picked normally again — see _history_recording_suppressed — and are
        saved back into `output_dir` (the Library folder the video came
        from) instead of whatever the global Output folder is right now."""
        self._loading_reused = True
        try:
            idx = self._wf_combo.findData(workflow_rel)
            if idx < 0:
                self.reload_workflows()
                idx = self._wf_combo.findData(workflow_rel)
            if idx >= 0 and idx != self._wf_combo.currentIndex():
                self._wf_combo.setCurrentIndex(idx)
        finally:
            self._loading_reused = False
        self._apply_history(entry, with_settings=True, record=False)
        self._reused_output_dir = output_dir
        return idx >= 0

    def _apply_history(self, entry: dict, with_settings: bool, record: bool = True):
        self._history_recording_suppressed = not record
        prompts = entry.get("prompts") or {}
        used_pos = used_neg = False
        for pf, edit in self._prompt_edits:
            rec = prompts.get(f"{pf.node_id}|{pf.key}")
            if rec is not None:
                edit.setPlainText(rec.get("text", ""))
            elif pf.negative and not used_neg and entry.get("negative") is not None:
                edit.setPlainText(entry.get("negative", ""))
                used_neg = True
            elif not pf.negative and not used_pos and entry.get("positive") is not None:
                edit.setPlainText(entry.get("positive", ""))
                used_pos = True
        if not with_settings:
            self.append_log("Loaded prompt from history")
            return
        s = entry.get("settings") or {}
        by_node = {(l.get("node"), l.get("key")): l for l in s.get("loras", [])}
        for slot, combo, spins in self._lora_rows:
            rec = by_node.get((slot.node_id, slot.name_key))
            if rec is None:
                continue
            self._set_combo_text(combo, rec.get("name", ""))
            for key, spin in spins.items():
                if key in (rec.get("strengths") or {}):
                    spin.setValue(float(rec["strengths"][key]))
        if s.get("seed") is not None:
            self._seed_mode.setCurrentIndex(1)
            self._seed_spin.setValue(int(s["seed"]))
        else:
            self._seed_mode.setCurrentIndex(0)
        if s.get("length") and self._length_spin.isVisible():
            try:
                self._length_spin.setValue(float(s["length"].get("value")))
            except (TypeError, ValueError):
                pass
        if s.get("steps") is not None and self._steps_spin.isVisible():
            try:
                self._steps_spin.setValue(int(s["steps"]))
            except (TypeError, ValueError):
                pass
        if s.get("megapixels") is not None and self._mp_spin.isVisible():
            try:
                self._mp_spin.setValue(float(s["megapixels"]))
            except (TypeError, ValueError):
                pass
        self._update_summary()
        self.append_log("Loaded prompt + settings from history")

    # ------------------------------------------------------------------ #
    # LoRAs
    # ------------------------------------------------------------------ #

    def _lora_names(self) -> list[str]:
        return _LORA_LIST.get("names", [])

    def _refresh_lora_status_label(self):
        parts = [p for p in (self._lora_folder_info, self._lora_server_info) if p]
        self._lora_status.setText("   ·   ".join(parts))

    def reload_loras_from_folder(self, quiet: bool = False):
        folder = Path((self._cfg.get("loras_dir", "") or "").strip())
        sep = "/" if self._cfg.get("mode", "local") == "runpod" else "\\"
        names = list_loras(folder, sep) if str(folder) else []
        _LORA_LIST["names"] = names
        _LORA_LIST["source"] = f"folder ({len(names)})" if names else "none"
        if names:
            self._lora_folder_info = f"{len(names)} from folder"
        elif not quiet:
            self._lora_folder_info = "No LoRAs folder set (Settings > Folders > LoRAs)"
        self._refresh_lora_status_label()
        self._refill_lora_combos()
        self.loras_changed.emit(self._lora_folder_info, self._lora_server_info)

    def apply_shared_loras(self, folder_info: str, server_info: str):
        """Another tab reloaded the shared LoRA list: show the same status and
        refill this tab's dropdowns, keeping what each one has selected."""
        self._lora_folder_info = folder_info
        self._lora_server_info = server_info
        self._refresh_lora_status_label()
        self._refill_lora_combos()

    def _fetch_loras_from_server(self):
        url = self._cfg.server_url()
        if not url:
            self._lora_server_info = "No server URL for the selected mode — see Settings"
            self._refresh_lora_status_label()
            return
        if self._lora_thread is not None and self._lora_thread.isRunning():
            return
        self._lora_server_info = f"Asking {url} …"
        self._refresh_lora_status_label()
        self._server_btn.setEnabled(False)
        self._lora_thread = _LoraFetchThread(url)
        self._lora_thread.done.connect(self._on_server_loras)
        self._lora_thread.start()

    def _on_server_loras(self, names: list, error: str):
        self._server_btn.setEnabled(True)
        if error:
            self._lora_server_info = f"Server list failed: {error}"
            self._refresh_lora_status_label()
            return
        _LORA_LIST["names"] = sorted(names, key=str.lower)
        _LORA_LIST["source"] = f"server ({len(names)})"
        self._lora_server_info = f"{len(names)} from server"
        self._refresh_lora_status_label()
        self._refill_lora_combos()
        self.loras_changed.emit(self._lora_folder_info, self._lora_server_info)

    def _rebuild_loras(self):
        self._clear_layout(self._lora_grid)
        self._lora_rows = []
        a = self._analysis
        if a is None or not a.loras:
            lbl = QLabel("This workflow has no LoRA loader nodes.")
            lbl.setObjectName("status_dim")
            self._lora_grid.addWidget(lbl, 0, 0, 1, 3)
            self._update_summary()
            return
        for row, slot in enumerate(a.loras):
            lbl = QLabel(slot.label)
            lbl.setToolTip(f"node {slot.node_id} · {slot.name_key}")
            lbl.setStyleSheet(f"color: {COLORS['fg_secondary']}; font-weight: bold;")
            lbl.setMinimumWidth(90)
            lbl.setMaximumWidth(150)
            self._lora_grid.addWidget(lbl, row, 0)
            combo = FilterComboBox(strict=False, placeholder="Type to filter…")
            combo.setMinimumWidth(140)
            combo.setToolTip(
                "LoRA file name as ComfyUI lists it (subfolders included). Type any part of a name "
                "to filter the list; a name that isn't in the list is kept as typed.")
            self._lora_grid.addWidget(combo, row, 1)
            spins: dict[str, QDoubleSpinBox] = {}
            sbox = QHBoxLayout()
            sbox.setSpacing(4)
            for key, value in slot.strengths.items():
                text = slot.strength_label(key)
                if text:
                    sbox.addWidget(QLabel(text + ":"))
                spin = QDoubleSpinBox()
                spin.setRange(-10.0, 10.0)
                spin.setDecimals(2)
                spin.setSingleStep(0.05)
                spin.setValue(value)
                spin.setFixedWidth(78)
                spin.setToolTip(f"{key}")
                spin.valueChanged.connect(lambda _v: self._update_summary())
                sbox.addWidget(spin)
                spins[key] = spin
            self._lora_grid.addLayout(sbox, row, 2)
            self._lora_rows.append((slot, combo, spins))
            self._fill_lora_combo(combo, slot)
            combo.currentTextChanged.connect(lambda _t: self._update_summary())
            combo.currentTextChanged.connect(
                lambda t, c=combo: self._mark_lora_missing(c, t.strip(), self._lora_names()))
        self._update_summary()

    def _fill_lora_combo(self, combo: QComboBox, slot: LoraSlot):
        current = combo.currentText() if combo.count() else slot.name
        names = self._lora_names()
        combo.blockSignals(True)
        combo.clear()
        if slot.allow_none:
            combo.addItem("None")
        if current and current not in names and current != "None":
            combo.addItem(current)
        combo.addItems(names)
        self._set_combo_text(combo, current)
        combo.blockSignals(False)
        self._mark_lora_missing(combo, current, names)

    @staticmethod
    def _mark_lora_missing(combo: QComboBox, name: str, names: list[str]):
        """A selected name the list doesn't have any more — the file was renamed
        or removed since the workflow was saved — gets a red edge and says so,
        instead of failing at run time."""
        missing = bool(name) and name != "None" and bool(names) and name not in names
        combo.setStyleSheet(f"QComboBox {{ border: 1px solid {COLORS['error']}; }}" if missing else "")
        combo.setToolTip(
            f"\u26a0 \"{name}\" is not in the LoRA list — renamed or removed? Pick its new name."
            if missing else
            "LoRA file name as ComfyUI lists it (subfolders included). Type any part of a name "
            "to filter the list; a name that isn't in the list is kept as typed.")

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str):
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(text)
        if combo.lineEdit() is not None:
            combo.lineEdit().setCursorPosition(0)   # show the start of long names

    def _refill_lora_combos(self):
        for slot, combo, _spins in self._lora_rows:
            self._fill_lora_combo(combo, slot)
        self._update_summary()

    def _lora_edits(self) -> dict[tuple[str, str], object]:
        edits: dict[tuple[str, str], object] = {}
        for slot, combo, spins in self._lora_rows:
            edits[(slot.node_id, slot.name_key)] = combo.currentText().strip() or ("None" if slot.allow_none else slot.name)
            for key, spin in spins.items():
                edits[(slot.node_id, key)] = float(spin.value())
        return edits

    def _lora_records(self) -> list[dict]:
        out = []
        for slot, combo, spins in self._lora_rows:
            out.append({
                "node": slot.node_id, "key": slot.name_key, "label": slot.label,
                "name": combo.currentText().strip(),
                "strengths": {k: float(sp.value()) for k, sp in spins.items()},
            })
        return out

    # ------------------------------------------------------------------ #
    # Seed / summary
    # ------------------------------------------------------------------ #

    def _on_seed_mode(self, *_):
        fixed = self._seed_mode.currentIndex() == 1
        self._seed_spin.setEnabled(fixed)
        self._cfg.set("seed_mode", "fixed" if fixed else "random")
        self._update_summary()

    def _on_seed_value(self, v: int):
        self._cfg.set("seed_value", int(v))
        self._update_summary()

    def _update_turbo_warning(self):
        low_quality_risk = (
            self._turbo_chk.isVisible() and not self._turbo_chk.isChecked()
            and self._steps_spin.isVisible() and self._steps_spin.value() < 15
        )
        self._turbo_warn.setVisible(low_quality_risk)

    def _collect_settings(self) -> dict:
        fld = self._analysis.length_field if self._analysis is not None else None
        return {
            "workflow": self._workflow_rel,
            "mode": self._cfg.get("mode", "local"),
            "seed": int(self._seed_spin.value()) if self._seed_mode.currentIndex() == 1 else None,
            "length": {"label": fld.label, "value": float(self._length_spin.value())} if fld is not None else None,
            "steps": int(self._steps_spin.value()) if (self._analysis is not None and self._analysis.steps_fields) else None,
            "megapixels": float(self._mp_spin.value()) if (self._analysis is not None and self._analysis.mp_fields) else None,
            "loras": self._lora_records(),
            "video_input_mode": self._input_mode.currentData() if self._input_mode is not None else None,
            "extend_stitch": bool(self._stitch_chk.isChecked()) if self._stitch_chk is not None else None,
            # Library → Reuse Settings tells the tabs apart by these keys: a
            # video_input_mode means Extend, text_to_video means this tab.
            "text_to_video": self.kind == "text",
        }

    def _update_summary(self):
        bits = self._summary_bits()
        self._summary.setFullText("Next run → " + "   |   ".join(bits) if bits else "")

    def _summary_bits(self) -> list[str]:
        """The settings that decide what this run produces, as short bits —
        shown under the panel and again in the queue view."""
        bits = []
        loras = [(slot, combo, spins) for slot, combo, spins in self._lora_rows
                 if combo.currentText().strip() and combo.currentText().strip() != "None"]
        if loras:
            bits.append("LoRAs: " + " · ".join(
                f"{Path(combo.currentText().strip()).stem} ({', '.join(f'{sp.value():g}' for sp in spins.values()) or '-'})"
                for _s, combo, spins in loras))
        elif self._lora_rows:
            bits.append("LoRAs: none")
        bits.append(f"Seed: {int(self._seed_spin.value())}" if self._seed_mode.currentIndex() == 1 else "Seed: random")
        if self._analysis is not None and self._analysis.steps_fields:
            bits.append(f"Steps: {int(self._steps_spin.value())}")
        if self._analysis is not None and self._analysis.mp_fields:
            if self._stitch_chk is not None and self._stitch_chk.isChecked():
                bits.append("MP: source video's size")
            else:
                bits.append(f"MP: {self._mp_spin.value():g}")
        if self._length_spin.isVisible() or (self._analysis and self._analysis.length_field):
            bits.append(f"{self._length_lbl.text().rstrip(':')}: {self._length_spin.value():g}")
        return bits

    def _start_frame_path(self, source: Path | None = None) -> Path | None:
        """The frame this run actually starts from, for the queue view. An
        image source is that frame; a video source starts from its LAST frame,
        which the Extend grid has already extracted and cached for the tile
        it's showing — reused here rather than shelling out to ffmpeg on a
        button click. Missing cache just means no preview, never a stall."""
        source = source or self._source
        if source is None:
            return None
        if self.kind == "image":
            return source if source.exists() else None
        cached = source.parent / "thumbnails" / (source.stem + "_last.jpg")
        return cached if cached.exists() else None

    def _positive_prompt_preview(self) -> str:
        """First non-empty positive prompt — enough to tell two queued runs
        on the same source/workflow apart in the queue view."""
        for pf, edit in self._prompt_edits:
            if pf.negative:
                continue
            text = edit.toPlainText().strip()
            if text:
                return text
        return ""

    # ------------------------------------------------------------------ #
    # Source / run
    # ------------------------------------------------------------------ #

    def set_sources(self, paths: list):
        """The browser's whole selection. One image is the ordinary case;
        several means Create queues one run per image, in this order, with
        the same prompt and settings — as if each were picked and Created
        by hand. The first is shown as the source preview."""
        sources = [Path(p) for p in paths]
        self.set_source(sources[0] if sources else None)
        self._sources = sources         # after set_source, which resets it to the one file
        n = len(self._sources)
        noun = "image" if self.kind == "image" else "video"
        if n > 1:
            names = ", ".join(p.name for p in self._sources[:4]) + (", …" if n > 4 else "")
            self._source_lbl.setText(f"Selected: {n} {noun}s — {names}   (one run each, in this order)")
            self._run_btn.setText(f"▶  {'Extend' if self.kind == 'video' else 'Create'} {n} Videos")
        else:
            self._run_btn.setText("▶  Extend Video" if self.kind == "video" else "▶  Create Video")

    def set_source(self, path: Path | None):
        # A single source set directly (Send to Extend, Reuse Settings) must
        # not leave an older multi-selection behind for Create to queue.
        self._sources = [path] if path is not None else []
        self._run_btn.setText("▶  Extend Video" if self.kind == "video" else "▶  Create Video")
        self._source = path
        if path is None:
            self._source_lbl.setText("No image selected" if self.kind == "image" else "No video selected")
            self._source_thumb.setVisible(False)
        else:
            self._source_lbl.setText(f"Selected: {path.name}")
            pix = QPixmap(str(path)) if self.kind == "image" else QPixmap()
            if not pix.isNull():
                self._source_thumb.setPixmap(pix.scaled(
                    48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self._source_thumb.setVisible(True)
            else:
                self._source_thumb.setVisible(False)
        self._update_run_enabled()

    def _update_run_enabled(self):
        # Stays enabled while a job is running — clicking it then just adds
        # another request to the shared queue (ComfyUI runs one at a time).
        ok = self._workflow_path is not None and self._analysis is not None
        if ok and self.kind == "text":
            ok = bool(self._analysis.prompts) and not (self._analysis.accepts_image or self._analysis.accepts_video)
        elif ok:
            ok = self._source is not None
        if ok and self.kind == "image":
            ok = self._analysis.accepts_image
        if ok and self.kind == "video":
            ok = self._analysis.accepts_image or self._analysis.accepts_video
        self._run_btn.setEnabled(bool(ok))

    def _on_run(self):
        if self._workflow_path is None or self._analysis is None:
            return
        if self._source is None and self.kind != "text":
            return
        sources = self._sources if len(self._sources) > 1 else [self._source]
        queued = 0
        for source in sources:
            if self._queue_one(source):
                queued += 1
        if len(sources) > 1:
            noun = "images" if self.kind == "image" else "videos"
            self.append_log(f"Queued {queued} of {len(sources)} selected {noun} as separate runs")

    def _queue_one(self, source: Path | None) -> bool:
        """Build, guard, record and emit one run for one source. Returns
        whether it was queued (the repeat guard can decline it)."""
        rel = Path(self._workflow_rel)
        label = rel.parts[0] if len(rel.parts) > 1 else rel.stem
        seed = int(self._seed_spin.value()) if self._seed_mode.currentIndex() == 1 else None
        fld = self._analysis.length_field
        req = RunRequest(
            workflow_path=self._workflow_path,
            workflow_label=label,
            source_path=source,
            source_kind=self.kind,
            prompts=self._prompt_overrides(),
            lora_edits=self._lora_edits(),
            seed=seed,
            length_field=fld,
            length_value=float(self._length_spin.value()) if fld is not None else None,
            steps=int(self._steps_spin.value()) if self._analysis.steps_fields else None,
            megapixels=float(self._mp_spin.value()) if self._analysis.mp_fields else None,
            video_input_mode=self._input_mode.currentData() if self._input_mode is not None else "auto",
            extend_stitch=bool(self._stitch_chk.isChecked()) if self._stitch_chk is not None else False,
            turbo_enabled=bool(self._turbo_chk.isChecked()) if self._analysis.turbo is not None else None,
            output_dir_override=self._reused_output_dir,
            prompt_preview=self._positive_prompt_preview(),
            settings_summary="   |   ".join(self._summary_bits()),
            thumb_path=self._start_frame_path(source),
            output_name=self._name_edit.text().strip() if self._name_edit is not None else "",
        )
        if not self._confirm_not_a_repeat(req):
            return False
        # Record what this run uses before it starts; the result file name is
        # attached to the same entry when the run finishes. Stored on the
        # request itself (not on self) so queuing several runs in a row -
        # each with its own workflow/prompt snapshot - can't cross-attach
        # one run's results to another's history entry.
        if not self._history_recording_suppressed:
            try:
                req.history_index = append_entry(
                    self._workflow_path,
                    make_entry(self._prompt_tuples(), self._collect_settings(),
                               source.name if source else ""))
            except Exception:  # noqa: BLE001
                req.history_index = None
        self.run_requested.emit(req)
        return True

    def _confirm_not_a_repeat(self, req: RunRequest) -> bool:
        """Asks before queuing a run that matches one already queued or
        running — generating the same video twice costs the full render
        time (and RunPod minutes) for nothing. Checked before the history
        entry is written so backing out leaves no trace."""
        match = self._queue_probe(req) if self._queue_probe else ""
        if not match:
            return True
        note = RANDOM_SEED_NOTE if req.seed is None else FIXED_SEED_NOTE
        ans = QMessageBox.question(
            self, "Already in the queue",
            f"""This looks like a repeat of {match}

{req.describe()}
{note}

Queue it anyway?""",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            self.append_log(f"Not queued — already a repeat of {match}")
            return False
        return True

    def set_queue_probe(self, probe):
        self._queue_probe = probe

    def set_queue_status(self, count: int, tooltip: str = "", next_up: str = ""):
        """Reflects the app-wide queue (shared across both tabs — ComfyUI
        only runs one prompt at a time regardless of which tab queued it)."""
        for w in (self._queue_lbl, self._view_queue_btn, self._clear_queue_btn):
            w.setVisible(count > 0)
        if count:
            text = f"⏳ {count} queued behind this run"
            if next_up:
                text += f"  —  next: {next_up}"
            self._queue_lbl.setText(text)
            self._queue_lbl.setToolTip(tooltip)

    def set_running(self, running: bool, active: bool = True):
        """running: a job is in progress somewhere; active: this panel owns it."""
        self._cancel_btn.setEnabled(running and active)
        if running and active:
            self._log.clear()
            self._progress.setStyleSheet("")   # clear the "DONE" yellow from a previous run
            self._progress.setRange(0, 0)
            self._progress.setFormat("")
            self._progress_lbl.setText("Starting…")
            self._run_started = time.time()
            self._sampler_total = self._phases_total = self._phases_seen = 0
            self._phase_label = ""
            self._offset = self._last_value = self._last_max = 0
            self._elapsed_timer.start()
        elif not running:
            self._elapsed_timer.stop()

    # ------------------------------------------------------------------ #
    # Worker feedback
    # ------------------------------------------------------------------ #

    def append_log(self, message: str):
        self._log.addItem(QListWidgetItem(f"[{time.strftime('%H:%M:%S')}] {message}"))
        while self._log.count() > MAX_LOG_LINES:
            self._log.takeItem(0)
        self._log.scrollToBottom()

    def on_plan(self, total_steps: int, phases: int):
        self._sampler_total = max(0, total_steps)
        self._phases_total = max(0, phases)
        self._phases_seen = 0
        self._phase_label = ""
        self._offset = self._last_value = self._last_max = 0
        total = self._sampler_total + self._phases_total
        if total > 0:
            # Sub-units per step so a post-sampling node's own progress can
            # fill its slice smoothly instead of jumping a whole unit.
            self._progress.setRange(0, total * PROGRESS_SUBUNITS)
            self._progress.setValue(0)
            self._progress.setFormat("%p%")
        else:
            self._progress.setRange(0, 0)

    def _advance(self, units: float):
        """Move the bar forward only. Post-sampling nodes emit step counts of
        their own (frames, tiles) and those must never rewind the bar."""
        if self._progress.maximum() > 0:
            # Stop one sub-unit short: 100% belongs to on_done, after the
            # finished file has been pulled off the server.
            value = min(int(units * PROGRESS_SUBUNITS), self._progress.maximum() - 1)
            self._progress.setValue(max(self._progress.value(), value))

    def _in_post_phase(self) -> bool:
        """True once a post-sampling node is running and the sampler has no
        steps left — anything ComfyUI reports now belongs to that node."""
        return bool(self._phases_seen) and (
            not self._sampler_total or self._offset + self._last_value >= self._sampler_total)

    def on_step(self, value: int, vmax: int):
        if self._in_post_phase():
            # VAE decode / video save report their own value/max; show them
            # inside the current phase rather than restarting the step count.
            base = self._sampler_total + self._phases_seen - 1
            frac = min(value / vmax, 1.0) if vmax > 0 else 0.0
            self._advance(base + frac)
            self._progress_lbl.setText(
                f"{self._phase_label} {value}/{vmax} · {self._elapsed()}".lstrip())
            return
        if value < self._last_value:
            self._offset += self._last_max
        self._last_value, self._last_max = value, vmax
        cum = min(self._offset + value, self._sampler_total) if self._sampler_total else self._offset + value
        self._advance(cum)
        shown_total = self._sampler_total or vmax
        self._progress_lbl.setText(f"Step {cum}/{shown_total} · {self._elapsed()}")

    def on_phase(self, label: str):
        self._phases_seen += 1
        self._phase_label = label
        self._advance(self._sampler_total + self._phases_seen - 1)
        self._progress_lbl.setText(f"{label} · {self._elapsed()}")

    def on_done(self, paths: list[str], req: RunRequest | None = None, timing: dict | None = None):
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setFormat("DONE")
        self._progress.setStyleSheet(
            f"QProgressBar {{ color: {COLORS['bg_dark']}; font-weight: bold; }}"
            f"QProgressBar::chunk {{ background-color: {COLORS['warning']}; }}"
        )
        self._progress_lbl.setText(f"Finished in {self._elapsed()}")
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:  # noqa: BLE001 — never let a notification sound break a finished run
            pass
        for p in paths:
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._results_list.addItem(item)
        if paths:
            self._results_list.setCurrentRow(self._results_list.count() - 1)
        # Use the request's own workflow/history snapshot, not the panel's
        # CURRENT selection - by the time this run finishes, the user may
        # have already switched workflows to queue a different one.
        if req is not None and req.history_index is not None:
            add_results(req.workflow_path, req.history_index, [Path(p).name for p in paths], timing,
                        source=req.source_path.name if req.source_path is not None else "")

    def on_failed(self, message: str):
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("")
        self._progress_lbl.setText(("Cancelled" if message == "Cancelled" else "Failed") + f" after {self._elapsed()}")
        self.append_log(("✕ " + message) if message != "Cancelled" else "Cancelled by user")

    def _tick(self):
        text = self._progress_lbl.text()
        if "·" in text:
            head = text.split("·", 1)[0].strip()
            self._progress_lbl.setText(f"{head} · {self._elapsed()}")
        else:
            self._progress_lbl.setText(f"{text.split(' (', 1)[0]} ({self._elapsed()})")

    def _elapsed(self) -> str:
        m, s = divmod(int(time.time() - self._run_started), 60)
        return f"{m:02d}m {s:02d}s"

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #

    def _selected_result(self) -> str | None:
        items = self._results_list.selectedItems()
        if items:
            return items[0].data(Qt.ItemDataRole.UserRole)
        if self._results_list.count():
            return self._results_list.item(self._results_list.count() - 1).data(Qt.ItemDataRole.UserRole)
        return None

    def _play_selected(self):
        p = self._selected_result()
        if p:
            self.play_requested.emit(p)

    def _open_result_folder(self):
        p = self._selected_result()
        folder = Path(p).parent if p else Path((self._cfg.get("output_dir", "") or "").strip())
        if folder and folder.is_dir():
            os.startfile(str(folder))
