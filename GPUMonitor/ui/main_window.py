"""GPU Monitor main window: live tiles + graphs on the left, tuning controls on the right."""

from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

import config
import elevation
from nvml_backend import GpuReader, describe_reasons
from ui import theme

SAMPLE_MS = 1000
MAX_SAMPLES = 900                      # 15 min at 1 Hz
HISTORY_CHOICES = [("1 min", 60), ("5 min", 300), ("15 min", 900)]
POWER_STEP_W = 5
# (button label, fraction of the stock limit)
POWER_PRESETS = [("Stock", 1.0), ("Efficient", 0.75), ("Quiet", 0.60)]
SEVERITY_COLOR = {0: theme.GOOD, 1: theme.WARN, 2: theme.BAD}


def dot_label(color, text):
    """Status readout rule: solid light text with a coloured dot in front."""
    return f'<span style="color:{color}">●</span>&nbsp; {text}'


class Tile(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)
        t = QLabel(title)
        t.setObjectName("tileTitle")
        self.value = QLabel("—")
        self.value.setObjectName("tileValue")
        self.sub = QLabel(" ")
        self.sub.setObjectName("muted")
        for w in (t, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value, sub=" "):
        self.value.setText(value)
        self.sub.setText(sub)


class ApplyWorker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, power_w, clock_max, reset_clocks):
        super().__init__()
        self.args = (power_w, clock_max, reset_clocks)

    def run(self):
        self.done.emit(elevation.run_apply(*self.args))


class MainWindow(QMainWindow):
    def __init__(self, version):
        super().__init__()
        self.setWindowTitle(f"GPU Monitor v{version}")
        self.cfg = config.load()
        self.gpu = GpuReader()
        self.worker = None
        self.data = {k: deque(maxlen=MAX_SAMPLES) for k in
                     ("t", "power", "limit", "temp", "util", "vram", "clock")}

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(self._build_header())
        left.addLayout(self._build_tiles())
        left.addWidget(self._build_graphs(), 1)
        outer.addLayout(left, 1)
        outer.addWidget(self._build_controls())

        g = self.cfg.get("geometry")
        if g:
            self.setGeometry(*g)
        else:
            self.resize(1280, 900)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(SAMPLE_MS)
        self.tick()

    # ---------- layout ----------
    def _build_header(self):
        row = QHBoxLayout()
        title = QLabel(f"{self.gpu.name}")
        title.setObjectName("heading")
        sub = QLabel(f"Driver {self.gpu.driver}  ·  {self.gpu.vram_total_mb / 1024:.0f} GB VRAM")
        sub.setObjectName("muted")
        self.throttle = QLabel()
        self.history = QComboBox()
        for label, secs in HISTORY_CHOICES:
            self.history.addItem(label, secs)
        idx = self.history.findData(self.cfg.get("history_s", 300))
        self.history.setCurrentIndex(max(idx, 0))
        self.history.currentIndexChanged.connect(self._apply_history)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(title)
        names.addWidget(sub)
        row.addLayout(names)
        row.addStretch(1)
        row.addWidget(self.throttle)
        row.addSpacing(16)
        row.addWidget(QLabel("Graph window"))
        row.addWidget(self.history)
        return row

    def _build_tiles(self):
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = {k: Tile(t) for k, t in (
            ("power", "POWER"), ("temp", "TEMPERATURE"), ("fan", "FAN"),
            ("util", "GPU LOAD"), ("vram", "VRAM"), ("clock", "CORE CLOCK"))}
        for i, tile in enumerate(self.tiles.values()):
            grid.addWidget(tile, i // 3, i % 3)
            grid.setColumnStretch(i % 3, 1)
        return grid

    def _build_graphs(self):
        pg.setConfigOptions(antialias=True, background=theme.PANEL, foreground=theme.MUTED)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.ci.layout.setSpacing(4)
        specs = [
            ("Power (W)", (0, self.gpu.limit_default_w * 1.1)),
            ("Temp (°C)", (20, 100)),
            ("Load / VRAM (%)", (0, 100)),
            ("Core clock (MHz)", (0, self.gpu.sm_max_mhz * 1.05)),
        ]
        self.plots = []
        for row, (label, yrange) in enumerate(specs):
            p = self.glw.addPlot(row=row, col=0)
            p.showGrid(x=True, y=True, alpha=0.15)
            p.setMouseEnabled(False, False)
            p.hideButtons()
            p.setMenuEnabled(False)
            p.setYRange(*yrange, padding=0)
            p.setLabel("left", label)
            p.getAxis("left").setWidth(70)
            last = row == len(specs) - 1
            p.getAxis("bottom").setStyle(showValues=last)
            if last:
                p.setLabel("bottom", "seconds ago")
            if self.plots:
                p.setXLink(self.plots[0])
            self.plots.append(p)
        pw, pt, pu, pc = self.plots
        pw.addLegend(offset=(10, 5))
        pu.addLegend(offset=(10, 5))
        self.c_power = pw.plot(pen=pg.mkPen(theme.C_POWER, width=2), name="Draw")
        self.c_limit = pw.plot(pen=pg.mkPen(theme.C_LIMIT, width=1.5, style=Qt.PenStyle.DashLine), name="Limit")
        self.c_temp = pt.plot(pen=pg.mkPen(theme.C_TEMP, width=2))
        self.c_util = pu.plot(pen=pg.mkPen(theme.C_UTIL, width=2), name="GPU load")
        self.c_vram = pu.plot(pen=pg.mkPen(theme.C_VRAM, width=2), name="VRAM")
        self.c_clock = pc.plot(pen=pg.mkPen(theme.C_CLOCK, width=2))
        self._apply_history()
        return self.glw

    def _build_controls(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(340)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # --- power limit
        h = QLabel("Power limit")
        h.setObjectName("heading")
        lay.addWidget(h)
        self.power_readout = QLabel()
        self.power_readout.setObjectName("readout")
        lay.addWidget(self.power_readout)
        lo = int(self.gpu.limit_min_w // POWER_STEP_W)
        hi = int(self.gpu.limit_max_w // POWER_STEP_W)
        self.power_slider = QSlider(Qt.Orientation.Horizontal)
        self.power_slider.setRange(lo, hi)
        self.power_slider.valueChanged.connect(self._power_changed)
        lay.addWidget(self.power_slider)
        presets = QHBoxLayout()
        for label, frac in POWER_PRESETS:
            watts = self._clamp_power(self.gpu.limit_default_w * frac)
            b = QPushButton(f"{label}\n{watts:.0f} W")
            b.clicked.connect(lambda _=False, w=watts: self.power_slider.setValue(int(w // POWER_STEP_W)))
            presets.addWidget(b)
        lay.addLayout(presets)
        self.power_info = QLabel(
            f"Stock {self.gpu.limit_default_w:.0f} W  ·  range "
            f"{self.gpu.limit_min_w:.0f}–{self.gpu.limit_max_w:.0f} W")
        self.power_info.setObjectName("muted")
        lay.addWidget(self.power_info)

        lay.addSpacing(10)

        # --- clock cap
        h2 = QLabel("Flat voltage ceiling")
        h2.setObjectName("heading")
        lay.addWidget(h2)
        self.cap_check = QCheckBox("Cap max core clock")
        self.cap_check.setChecked(bool(self.cfg.get("clock_cap_on")))
        self.cap_check.toggled.connect(self._cap_toggled)
        lay.addWidget(self.cap_check)
        self.cap_readout = QLabel()
        self.cap_readout.setObjectName("readout")
        lay.addWidget(self.cap_readout)
        self.cap_slider = QSlider(Qt.Orientation.Horizontal)
        clocks = self.gpu.supported_clocks
        self.cap_slider.setRange(0, max(len(clocks) - 1, 0))
        self.cap_slider.valueChanged.connect(self._cap_changed)
        # actionTriggered fires only for user input, so programmatic setValue never ticks the box
        self.cap_slider.actionTriggered.connect(lambda _a: self.cap_check.setChecked(True))
        lay.addWidget(self.cap_slider)
        hint = QLabel("The GPU will never boost past this clock, so voltage never climbs above "
                      "that point on the V/F curve — the same effect as a flat curve in Afterburner.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addStretch(1)

        # --- apply
        self.status = QLabel(dot_label(theme.MUTED, "Nothing applied yet"))
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply)
        lay.addWidget(self.apply_btn)
        self.restore_btn = QPushButton("Restore stock")
        self.restore_btn.clicked.connect(self.restore_stock)
        lay.addWidget(self.restore_btn)
        note = QLabel("Windows will ask for permission when you press Apply. Settings reset on "
                      "reboot. MSI Afterburner can overwrite them when it applies a profile.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        # initial values: power from the live card, clock from saved config
        self.power_slider.setValue(int(round((self._current_limit() or self.gpu.limit_default_w) / POWER_STEP_W)))
        saved = self.cfg.get("clock_cap_mhz")
        idx = len(clocks) - 1
        if saved and clocks:
            idx = min(range(len(clocks)), key=lambda i: abs(clocks[i] - saved))
        self.cap_slider.setValue(max(idx, 0))
        self._power_changed()
        self._cap_toggled(self.cap_check.isChecked())
        return panel

    # ---------- helpers ----------
    def _clamp_power(self, watts):
        step = POWER_STEP_W
        return max(self.gpu.limit_min_w, min(self.gpu.limit_max_w, round(watts / step) * step))

    def _current_limit(self):
        return self.gpu.sample()["limit_w"]

    def _power_changed(self, *_):
        w = self.power_slider.value() * POWER_STEP_W
        over = "  ⚠ above stock" if w > self.gpu.limit_default_w else ""
        self.power_readout.setText(f"{w} W{over}")

    def _cap_clock(self):
        clocks = self.gpu.supported_clocks
        return clocks[self.cap_slider.value()] if clocks else None

    def _cap_changed(self, *_):
        mhz = self._cap_clock()
        if not mhz:
            self.cap_readout.setText("n/a")
            return
        off = "" if self.cap_check.isChecked() else "  (cap off)"
        self.cap_readout.setText(f"{mhz} MHz{off}")

    def _cap_toggled(self, on):
        self._cap_changed()

    def _apply_history(self):
        secs = self.history.currentData()
        self.plots[0].setXRange(-secs, 0, padding=0)
        self.cfg["history_s"] = secs

    # ---------- sampling ----------
    def tick(self):
        s = self.gpu.sample()
        d = self.data
        d["t"].append(s["t"])
        d["power"].append(s["power_w"] if s["power_w"] is not None else np.nan)
        d["limit"].append(s["limit_w"] if s["limit_w"] is not None else np.nan)
        d["temp"].append(s["temp_c"] if s["temp_c"] is not None else np.nan)
        d["util"].append(s["util_gpu"] if s["util_gpu"] is not None else np.nan)
        vram_pct = None if s["vram_used_mb"] is None else 100.0 * s["vram_used_mb"] / self.gpu.vram_total_mb
        d["vram"].append(vram_pct if vram_pct is not None else np.nan)
        d["clock"].append(s["sm_mhz"] if s["sm_mhz"] is not None else np.nan)
        self._update_tiles(s, vram_pct)
        self._update_graphs()

    def _update_tiles(self, s, vram_pct):
        T = self.tiles
        if s["power_w"] is not None:
            lim = f"of {s['limit_w']:.0f} W limit" if s["limit_w"] else " "
            T["power"].set(f"{s['power_w']:.0f} W", lim)
        if s["temp_c"] is not None:
            T["temp"].set(f"{s['temp_c']} °C")
        if s["fan_pct"] is not None:
            T["fan"].set(f"{s['fan_pct']} %")
        if s["util_gpu"] is not None:
            T["util"].set(f"{s['util_gpu']} %", f"memory bus {s['util_mem']} %")
        if s["vram_used_mb"] is not None:
            T["vram"].set(f"{s['vram_used_mb'] / 1024:.1f} GB",
                          f"of {self.gpu.vram_total_mb / 1024:.0f} GB  ({vram_pct:.0f} %)")
        if s["sm_mhz"] is not None:
            eff = f"{s['sm_mhz'] / s['power_w']:.1f} MHz/W" if s["power_w"] else " "
            T["clock"].set(f"{s['sm_mhz']} MHz", eff)
        text, sev = describe_reasons(s["reasons"])
        self.throttle.setText(dot_label(SEVERITY_COLOR[sev], f"Throttle: {text}"))

    def _update_graphs(self):
        d = self.data
        t = np.array(d["t"])
        x = t - t[-1]
        for curve, key in ((self.c_power, "power"), (self.c_limit, "limit"), (self.c_temp, "temp"),
                           (self.c_util, "util"), (self.c_vram, "vram"), (self.c_clock, "clock")):
            curve.setData(x, np.array(d[key], dtype=float), connect="finite")

    # ---------- apply ----------
    def apply(self):
        power = self.power_slider.value() * POWER_STEP_W
        cap = self._cap_clock() if self.cap_check.isChecked() else None
        self.cfg["clock_cap_on"] = self.cap_check.isChecked()
        self.cfg["clock_cap_mhz"] = self._cap_clock()
        self._run_worker(power, cap, reset_clocks=cap is None)

    def restore_stock(self):
        self.power_slider.setValue(int(self.gpu.limit_default_w // POWER_STEP_W))
        self.cap_check.setChecked(False)
        self.cfg["clock_cap_on"] = False
        self._run_worker(self.gpu.limit_default_w, None, reset_clocks=True)

    def _run_worker(self, power, cap, reset_clocks):
        if self.worker and self.worker.isRunning():
            return
        self.apply_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)
        self.status.setText(dot_label(theme.WARN, "Waiting for Windows permission…"))
        self.worker = ApplyWorker(power, cap, reset_clocks)
        self.worker.done.connect(self._apply_done)
        self.worker.start()

    def _apply_done(self, result):
        self.apply_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        color = theme.GOOD if result["ok"] else (theme.MUTED if result.get("cancelled") else theme.BAD)
        self.status.setText(dot_label(color, "<br>".join(result["messages"])))
        self.tick()

    def closeEvent(self, e):
        g = self.geometry()
        self.cfg["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        config.save(self.cfg)
        self.timer.stop()
        self.gpu.close()
        super().closeEvent(e)
