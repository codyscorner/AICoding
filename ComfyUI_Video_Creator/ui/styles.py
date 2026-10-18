"""Dark red theme."""

import sys
from pathlib import Path


def _icon_path(name: str) -> str:
    # The spec bundles ui/icons/ verbatim into the frozen extraction root
    # (see the spec's `datas` entry); running from source it's just the
    # sibling icons/ folder next to this file.
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) / "ui" / "icons"
    else:
        base = Path(__file__).parent / "icons"
    return str(base / name).replace("\\", "/")


COLORS = {
    'bg_dark':      '#140505',
    'bg_medium':    '#200909',
    'bg_light':     '#2e1010',
    'bg_input':     '#1a0707',
    'fg_primary':   '#f4e6e6',
    'fg_secondary': '#d09a9a',
    'fg_dim':       '#7d4a4a',
    'accent':       '#b3122b',
    'accent_hover': '#dc2b48',
    'accent_dark':  '#7a0c1e',
    'border':       '#4a1a1a',
    'success':      '#5fcf9a',
    'error':        '#ff6b6b',
    'warning':      '#ffb74d',
    'progress_bg':  '#200909',
    'progress_fg':  '#c8142f',
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['fg_primary']};
    font-family: "Segoe UI";
    font-size: 10pt;
}}
QToolTip {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['accent']};
    padding: 4px;
}}
QLabel {{
    background-color: transparent;
    color: {COLORS['fg_primary']};
}}
QLabel#header {{
    color: {COLORS['accent_hover']};
    font-size: 17pt;
    font-weight: bold;
}}
QLabel#subtitle {{
    color: {COLORS['fg_secondary']};
    font-size: 9pt;
}}
QLabel#status_ok {{
    color: {COLORS['success']};
    font-size: 9pt;
}}
QLabel#status_err {{
    color: {COLORS['error']};
    font-size: 9pt;
}}
QLabel#status_dim {{
    color: {COLORS['fg_secondary']};
    font-size: 9pt;
}}
QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 5px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    color: {COLORS['accent_hover']};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {COLORS['bg_medium']};
    color: {COLORS['fg_secondary']};
    border: 1px solid {COLORS['border']};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 9px 26px;
    font-size: 11pt;
    font-weight: bold;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {COLORS['accent']};
    color: white;
}}
QTabBar::tab:hover:!selected {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
}}
QRadioButton, QCheckBox {{
    color: {COLORS['fg_primary']};
    spacing: 8px;
    padding: 2px 4px;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid {COLORS['border']};
    background-color: {COLORS['bg_light']};
}}
QRadioButton::indicator:checked {{
    background-color: {COLORS['accent']};
    border: 2px solid {COLORS['accent_hover']};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 2px solid {COLORS['border']};
    background-color: {COLORS['bg_light']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['accent']};
    border: 2px solid {COLORS['accent_hover']};
}}
QComboBox {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 5px 10px;
    font-size: 10pt;
}}
QComboBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: url({_icon_path('chevron_down.png')});
    width: 12px;
    height: 8px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_medium']};
    color: {COLORS['fg_primary']};
    selection-background-color: {COLORS['accent']};
    border: 1px solid {COLORS['border']};
}}
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {COLORS['accent']};
}}
QLineEdit:read-only {{
    color: {COLORS['fg_secondary']};
}}
QPushButton {{
    background-color: {COLORS['accent']};
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 10.5pt;
}}
QPushButton:hover {{
    background-color: {COLORS['accent_hover']};
}}
QPushButton:pressed {{
    background-color: {COLORS['accent_dark']};
}}
QPushButton:disabled {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_dim']};
}}
QPushButton#small_btn {{
    padding: 5px 10px;
    font-size: 10pt;
    font-weight: normal;
}}
QPushButton#secondary_btn {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    padding: 5px 12px;
    font-size: 10pt;
}}
QPushButton#secondary_btn:hover {{
    background-color: {COLORS['accent_dark']};
    border: 1px solid {COLORS['accent']};
}}
QPushButton#run_btn {{
    font-size: 13pt;
    padding: 12px 28px;
}}
QPushButton#cancel_btn {{
    background-color: {COLORS['accent_dark']};
    color: {COLORS['fg_primary']};
}}
QPushButton#cancel_btn:hover {{
    background-color: {COLORS['error']};
    color: white;
}}
QProgressBar {{
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background-color: {COLORS['progress_bg']};
    height: 20px;
    text-align: center;
    color: {COLORS['fg_primary']};
}}
QProgressBar::chunk {{
    background-color: {COLORS['progress_fg']};
    border-radius: 2px;
}}
QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 3px 6px;
    font-size: 10pt;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {COLORS['bg_medium']};
    border: none;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {COLORS['accent']};
}}
QListWidget {{
    background-color: {COLORS['bg_medium']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    font-family: Consolas;
    font-size: 9pt;
}}
QListWidget::item {{
    padding: 1px 4px;
}}
QListWidget::item:selected {{
    background-color: {COLORS['accent_dark']};
    color: white;
}}
QSplitter::handle {{
    background-color: {COLORS['border']};
    width: 3px;
}}
QScrollBar:vertical {{
    background-color: {COLORS['bg_dark']};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['accent_dark']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: {COLORS['bg_dark']};
    height: 10px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {COLORS['border']};
    border-radius: 5px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QMessageBox, QDialog {{
    background-color: {COLORS['bg_dark']};
}}
QScrollArea {{
    border: none;
}}
"""
