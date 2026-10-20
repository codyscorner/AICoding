"""Navy palette (the default for new apps) + the app stylesheet."""

BG = "#0b1426"
PANEL = "#121f38"
PANEL_ALT = "#18294a"
BORDER = "#25395f"
TEXT = "#e8eef9"
MUTED = "#8fa3c4"
ACCENT = "#4da3ff"
ACCENT_HOVER = "#74b8ff"
GOOD = "#3ddc97"
WARN = "#ffb84d"
BAD = "#ff6b6b"

# graph series colours
C_POWER = "#4da3ff"
C_LIMIT = "#ffb84d"
C_TEMP = "#ff7a59"
C_UTIL = "#3ddc97"
C_VRAM = "#b48cff"
C_CLOCK = "#5ce1e6"

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Segoe UI'; font-size: 10pt; }}
QFrame#tile, QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#tile QLabel, QFrame#panel QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#tileTitle {{ color: {MUTED}; font-size: 9pt; }}
QLabel#tileValue {{ font-size: 20pt; font-weight: 600; }}
QLabel#heading {{ font-size: 11pt; font-weight: 600; }}
QLabel#readout {{ font-size: 18pt; font-weight: 600; color: {ACCENT}; }}
QPushButton {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT}; color: #07101f; border: none; font-weight: 600; padding: 8px 14px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {MUTED}; }}
QComboBox {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: {ACCENT}; selection-color: #07101f; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {MUTED}; border-radius: 4px; background: {PANEL_ALT}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 6px; background: {BORDER}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; background: {TEXT}; }}
QSlider::handle:horizontal:disabled {{ background: {MUTED}; }}
"""
