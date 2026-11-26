import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QLabel, QPushButton, QSpinBox, QTextEdit,
    QGridLayout, QVBoxLayout, QHBoxLayout, QFrame, QMessageBox,
)
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtCore import Qt, QTimer


def _base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


COLORS = {
    "bg":           "#1a1a2e",
    "bg_mid":       "#16213e",
    "fg":           "#e0d7ff",
    "accent1":      "#7b2fff",
    "accent2":      "#c77dff",
    "button_bg":    "#7b2fff",
    "button_fg":    "#ffffff",
    "button_hover": "#9d4edd",
    "input_bg":     "#0f3460",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['fg']};
    font-family: Helvetica;
}}
QTabWidget::pane {{
    border: 1px solid {COLORS['accent1']};
    background-color: {COLORS['bg']};
}}
QTabBar::tab {{
    background-color: {COLORS['bg_mid']};
    color: {COLORS['fg']};
    font-size: 11pt;
    font-weight: bold;
    padding: 6px 16px;
    border: 1px solid {COLORS['accent1']};
}}
QTabBar::tab:selected {{
    background-color: {COLORS['accent1']};
    color: #ffffff;
}}
QPushButton {{
    background-color: {COLORS['button_bg']};
    color: {COLORS['button_fg']};
    font-size: 12pt;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    min-width: 90px;
}}
QPushButton:hover {{
    background-color: {COLORS['button_hover']};
}}
QPushButton:disabled {{
    background-color: #333355;
    color: #666688;
}}
QTextEdit {{
    background-color: {COLORS['input_bg']};
    color: {COLORS['fg']};
    font-family: Consolas;
    font-size: 11pt;
    border: 1px solid {COLORS['accent1']};
    border-radius: 3px;
}}
QSpinBox {{
    background-color: {COLORS['input_bg']};
    color: {COLORS['fg']};
    font-size: 14pt;
    font-family: Helvetica;
    padding: 4px;
    min-width: 50px;
    border: 1px solid {COLORS['accent1']};
    border-radius: 3px;
}}
QLabel#display {{
    font-size: 40pt;
    font-weight: bold;
    color: {COLORS['accent2']};
}}
QLabel#display_alarm {{
    font-size: 40pt;
    font-weight: bold;
    color: red;
}}
QLabel#section_title {{
    font-size: 12pt;
    font-weight: bold;
    color: {COLORS['accent2']};
}}
QLabel#spin_label {{
    font-size: 10pt;
    font-weight: bold;
    color: {COLORS['accent2']};
}}
"""


class StopwatchTimerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stopwatch & Timer v1.1.2")
        self.setMinimumSize(400, 600)
        self.resize(450, 650)
        self.setStyleSheet(STYLESHEET)

        # Audio
        try:
            pygame.mixer.init()
            self.sound_loaded = True
        except Exception as e:
            print(f"Failed to initialize pygame mixer: {e}")
            self.sound_loaded = False
        self.chime_file = os.path.join(_base_path(), "TimerChime.mp3")
        self.channel = None
        self.is_ringing = False

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._build_stopwatch_tab(), "Stopwatch")
        self.tabs.addTab(self._build_timer_tab(), "Timer")

        # Timers
        self._sw_timer = QTimer()
        self._sw_timer.setInterval(50)
        self._sw_timer.timeout.connect(self._update_stopwatch)

        self._tmr_timer = QTimer()
        self._tmr_timer.setInterval(100)
        self._tmr_timer.timeout.connect(self._update_timer)

    # ── Stopwatch tab ─────────────────────────────────────────────────────

    def _build_stopwatch_tab(self):
        self.sw_running = False
        self.sw_start_time = 0.0
        self.sw_elapsed = 0.0
        self.sw_laps = []
        self.MAX_LAPS = 50

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self.sw_display = QLabel("00:00:00.00")
        self.sw_display.setObjectName("display")
        self.sw_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sw_display)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(8)
        self.sw_btn_start = QPushButton("Start")
        self.sw_btn_stop  = QPushButton("Stop")
        self.sw_btn_lap   = QPushButton("Lap")
        self.sw_btn_reset = QPushButton("Reset")
        self.sw_btn_stop.setEnabled(False)
        self.sw_btn_lap.setEnabled(False)
        self.sw_btn_start.clicked.connect(self.sw_start)
        self.sw_btn_stop.clicked.connect(self.sw_stop)
        self.sw_btn_lap.clicked.connect(self.sw_lap)
        self.sw_btn_reset.clicked.connect(self.sw_reset)
        btn_grid.addWidget(self.sw_btn_start, 0, 0)
        btn_grid.addWidget(self.sw_btn_stop,  0, 1)
        btn_grid.addWidget(self.sw_btn_lap,   1, 0)
        btn_grid.addWidget(self.sw_btn_reset, 1, 1)
        layout.addLayout(btn_grid)

        lbl = QLabel("Laps & Status")
        lbl.setObjectName("section_title")
        layout.addWidget(lbl)

        self.sw_status_box = QTextEdit()
        self.sw_status_box.setReadOnly(True)
        layout.addWidget(self.sw_status_box)

        self._log_sw("Stopwatch initialized. Ready.")
        return w

    def _log_sw(self, message: str):
        self.sw_status_box.append(message)

    def format_time(self, t: float) -> str:
        mins, secs = divmod(t, 60)
        hours, mins = divmod(mins, 60)
        ms = int((t % 1) * 100)
        return f"{int(hours):02d}:{int(mins):02d}:{int(secs):02d}.{ms:02d}"

    def sw_start(self):
        if not self.sw_running:
            self.sw_start_time = time.time() - self.sw_elapsed
            self.sw_running = True
            self._sw_timer.start()
            self.sw_btn_start.setEnabled(False)
            self.sw_btn_stop.setEnabled(True)
            if len(self.sw_laps) < self.MAX_LAPS:
                self.sw_btn_lap.setEnabled(True)
            if self.sw_elapsed == 0:
                self._log_sw(f"Session Started: {datetime.now().strftime('%I:%M:%S %p')}")
                self._log_sw("-" * 35)

    def _update_stopwatch(self):
        self.sw_elapsed = time.time() - self.sw_start_time
        self.sw_display.setText(self.format_time(self.sw_elapsed))

    def sw_stop(self):
        if self.sw_running:
            self.sw_running = False
            self._sw_timer.stop()
            self.sw_btn_start.setEnabled(True)
            self.sw_btn_stop.setEnabled(False)
            self.sw_btn_lap.setEnabled(False)

    def sw_lap(self):
        if self.sw_running and len(self.sw_laps) < self.MAX_LAPS:
            lap_time = self.sw_elapsed
            self.sw_laps.append(lap_time)
            split = lap_time if len(self.sw_laps) == 1 else lap_time - self.sw_laps[-2]
            n = len(self.sw_laps)
            self._log_sw(f"Lap {n:02d}: {self.format_time(lap_time)}  (Split: {self.format_time(split)})")
            if n >= self.MAX_LAPS:
                self.sw_btn_lap.setEnabled(False)
                self._log_sw("Maximum 50 laps reached.")

    def sw_reset(self):
        self.sw_running = False
        self._sw_timer.stop()
        self.sw_elapsed = 0.0
        self.sw_laps = []
        self.sw_display.setText("00:00:00.00")
        self.sw_btn_start.setEnabled(True)
        self.sw_btn_stop.setEnabled(False)
        self.sw_btn_lap.setEnabled(False)
        self.sw_status_box.clear()
        self._log_sw("Stopwatch reset. Ready.")

    # ── Timer tab ─────────────────────────────────────────────────────────

    def _build_timer_tab(self):
        self.tmr_running = False
        self.tmr_paused = False
        self.tmr_remaining = 0.0
        self.tmr_end_time = 0.0

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self.tmr_display = QLabel("00:00:00")
        self.tmr_display.setObjectName("display")
        self.tmr_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.tmr_display)

        # Spinbox row
        spin_layout = QHBoxLayout()
        spin_layout.setSpacing(10)
        for text, attr, max_val in [("Hours=HH", "tmr_hh", 99), ("Minutes=MM", "tmr_mm", 59), ("Seconds=SS", "tmr_ss", 59)]:
            col = QVBoxLayout()
            lbl = QLabel(text)
            lbl.setObjectName("spin_label")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin = QSpinBox()
            spin.setRange(0, max_val)
            spin.setValue(0)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            setattr(self, attr, spin)
            col.addWidget(lbl)
            col.addWidget(spin)
            spin_layout.addLayout(col)
        layout.addLayout(spin_layout)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(8)
        self.tmr_btn_start = QPushButton("Start")
        self.tmr_btn_pause = QPushButton("Pause")
        self.tmr_btn_reset = QPushButton("Reset")
        self.tmr_btn_pause.setEnabled(False)
        self.tmr_btn_start.clicked.connect(self.tmr_start)
        self.tmr_btn_pause.clicked.connect(self.tmr_pause)
        self.tmr_btn_reset.clicked.connect(self.tmr_reset)
        btn_grid.addWidget(self.tmr_btn_start, 0, 0)
        btn_grid.addWidget(self.tmr_btn_pause, 0, 1)
        btn_grid.addWidget(self.tmr_btn_reset, 1, 0, 1, 2)
        layout.addLayout(btn_grid)
        layout.addStretch()

        return w

    def format_timer(self, seconds: float) -> str:
        seconds = max(0, seconds)
        mins, secs = divmod(int(seconds), 60)
        hours, mins = divmod(mins, 60)
        return f"{hours:02d}:{mins:02d}:{secs:02d}"

    def _get_input_seconds(self) -> int:
        return self.tmr_hh.value() * 3600 + self.tmr_mm.value() * 60 + self.tmr_ss.value()

    def tmr_start(self):
        if self.is_ringing:
            self.stop_ringing()
            return
        if not self.tmr_running:
            if not self.tmr_paused:
                self.tmr_remaining = self._get_input_seconds()
            if self.tmr_remaining <= 0:
                QMessageBox.warning(self, "Invalid Time", "Please enter a time greater than zero.")
                return
            self.tmr_running = True
            self.tmr_paused = False
            self.tmr_end_time = time.time() + self.tmr_remaining
            self.tmr_hh.setEnabled(False)
            self.tmr_mm.setEnabled(False)
            self.tmr_ss.setEnabled(False)
            self.tmr_btn_start.setEnabled(False)
            self.tmr_btn_pause.setEnabled(True)
            self._tmr_timer.start()

    def _update_timer(self):
        if self.tmr_running:
            self.tmr_remaining = self.tmr_end_time - time.time()
            if self.tmr_remaining <= 0:
                self.tmr_remaining = 0
                self.tmr_display.setText("00:00:00")
                self._tmr_timer.stop()
                self.play_chime()
                self._reset_timer_state()
            else:
                self.tmr_display.setText(self.format_timer(self.tmr_remaining))

    def tmr_pause(self):
        if self.tmr_running:
            self.tmr_running = False
            self._tmr_timer.stop()
            self.tmr_paused = True
            self.tmr_btn_start.setEnabled(True)
            self.tmr_btn_pause.setEnabled(False)

    def tmr_reset(self):
        if self.is_ringing:
            self.stop_ringing()
        self._tmr_timer.stop()
        self._reset_timer_state()
        self.tmr_display.setText("00:00:00")

    def _reset_timer_state(self):
        self.tmr_running = False
        self.tmr_paused = False
        self.tmr_remaining = 0.0
        self.tmr_hh.setEnabled(True)
        self.tmr_mm.setEnabled(True)
        self.tmr_ss.setEnabled(True)
        self.tmr_btn_start.setEnabled(True)
        self.tmr_btn_pause.setEnabled(False)

    def play_chime(self):
        if self.sound_loaded and os.path.exists(self.chime_file):
            try:
                sound = pygame.mixer.Sound(self.chime_file)
                self.channel = sound.play(loops=-1)
                self.is_ringing = True
                self.tmr_btn_start.setObjectName("alarm_btn")
                self.tmr_btn_start.setStyleSheet("background-color: red; color: white;")
                self.tmr_btn_start.setText("STOP ALARM")
                self.tmr_btn_start.setEnabled(True)
                self.tmr_display.setObjectName("display_alarm")
                self.tmr_display.setStyleSheet("font-size: 40pt; font-weight: bold; color: red;")
                return
            except Exception as e:
                print(f"Error playing sound: {e}")
        self.fallback_alert()

    def stop_ringing(self):
        if self.channel:
            self.channel.stop()
        self.is_ringing = False
        self.tmr_btn_start.setText("Start")
        self.tmr_btn_start.setStyleSheet("")
        self.tmr_display.setStyleSheet("")

    def keyPressEvent(self, event):
        key = event.key()
        on_stopwatch = self.tabs.currentIndex() == 0
        on_timer = self.tabs.currentIndex() == 1

        if key == Qt.Key.Key_Space:
            if on_stopwatch:
                if self.sw_running:
                    self.sw_stop()
                else:
                    self.sw_start()
            elif on_timer:
                if self.is_ringing:
                    self.stop_ringing()
                elif self.tmr_running:
                    self.tmr_pause()
                else:
                    self.tmr_start()
        elif key == Qt.Key.Key_L and on_stopwatch:
            self.sw_lap()
        elif key == Qt.Key.Key_R:
            if on_stopwatch:
                self.sw_reset()
            elif on_timer:
                self.tmr_reset()
        else:
            super().keyPressEvent(event)

    def fallback_alert(self):
        QApplication.beep()
        QMessageBox.information(self, "Time's Up!", "The timer has finished!")


def main():
    app = QApplication(sys.argv)
    window = StopwatchTimerApp()
    icon_path = Path(_base_path()) / "app_icon.ico"
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
