"""Dark red theme for File Hash Dedupe"""

COLORS = {
    'bg_dark':       '#1f0d0d',
    'bg_medium':     '#3a1a1a',
    'bg_light':      '#4a2a2a',
    'fg_primary':    '#f0e0e0',
    'fg_secondary':  '#c09090',
    'fg_dim':        '#806060',
    'accent':        '#c0392b',
    'accent_hover':  '#e74c3c',
    'accent_dark':   '#7b241c',
    'border':        '#5a2a2a',
    'error':         '#ff6b6b',
    'success':       '#a8d5a2',
    'progress_bg':   '#3a1a1a',
    'progress_fg':   '#c0392b',
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['fg_primary']};
    font-family: "Segoe UI";
    font-size: 10pt;
}}
QLabel {{
    background-color: transparent;
    color: {COLORS['fg_primary']};
}}
QLabel#subtitle {{
    color: {COLORS['fg_secondary']};
    font-size: 9pt;
}}
QLabel#header {{
    color: {COLORS['accent_hover']};
    font-size: 18pt;
    font-weight: bold;
}}
QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    margin-top: 8px;
    padding: 8px 8px 8px 8px;
    color: {COLORS['accent_hover']};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QLineEdit {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 6px;
    font-size: 10pt;
}}
QLineEdit:focus {{
    border: 1px solid {COLORS['accent']};
}}
QCheckBox {{
    color: {COLORS['fg_primary']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {COLORS['border']};
    border-radius: 2px;
    background-color: {COLORS['bg_light']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}
QSpinBox {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 4px;
    min-height: 22px;
}}
QPushButton#small_btn {{
    padding: 4px 14px;
    font-size: 9pt;
}}
QComboBox {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 22px;
    min-width: 140px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_primary']};
    selection-background-color: {COLORS['accent']};
}}
QPushButton {{
    background-color: {COLORS['accent']};
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 10px 30px;
    font-size: 11pt;
}}
QPushButton:hover {{
    background-color: {COLORS['accent_hover']};
}}
QPushButton:disabled {{
    background-color: {COLORS['bg_light']};
    color: {COLORS['fg_dim']};
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
    height: 22px;
    text-align: center;
    color: {COLORS['fg_primary']};
}}
QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 2px;
}}
QListWidget {{
    background-color: {COLORS['bg_medium']};
    color: {COLORS['fg_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    font-family: Consolas;
    font-size: 9pt;
}}
QListWidget::item:selected {{
    background-color: {COLORS['accent']};
    color: white;
}}
QScrollBar:vertical {{
    background-color: {COLORS['bg_dark']};
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    border-radius: 6px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
