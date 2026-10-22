"""Theme styles for File Copy Move Manager — gold (copy) and red (move) themes"""

COLORS = {
    'background':      '#1a1a1a',
    'bg_mid':          '#2d2d2d',
    'bg_light':        '#3a3a3a',
    'foreground':      '#FFD700',
    'input_bg':        '#2d2d2d',
    'input_fg':        '#FFFF00',
    'button_bg':       '#FFD700',
    'button_fg':       '#000000',
    'button_active':   '#FFA500',
    'button_hover':    '#FFED4E',
    'select_bg':       '#FFD700',
    'select_fg':       '#000000',
    'scrollbar_bg':    '#333333',
    'accent':          '#FFD700',
    'accent_hover':    '#FFED4E',
    'border':          '#444444',
    'error':           '#ff6b6b',
    'success':         '#7ddc7d',
    'fg_dim':          '#888888',
    'fg_secondary':    '#ccaa00',
}

RED_COLORS = {
    'background':      '#1a1a1a',
    'bg_mid':          '#2d2d2d',
    'bg_light':        '#3a3a3a',
    'foreground':      '#FF4444',
    'input_bg':        '#2d2d2d',
    'input_fg':        '#FF6666',
    'button_bg':       '#FF4444',
    'button_fg':       '#FFFFFF',
    'button_active':   '#CC0000',
    'button_hover':    '#FF6666',
    'select_bg':       '#FF4444',
    'select_fg':       '#FFFFFF',
    'scrollbar_bg':    '#333333',
    'accent':          '#FF4444',
    'accent_hover':    '#FF6666',
    'border':          '#444444',
    'error':           '#ff6b6b',
    'success':         '#7ddc7d',
    'fg_dim':          '#888888',
    'fg_secondary':    '#CC3333',
}


def get_stylesheet(mode: str = 'copy') -> str:
    C = RED_COLORS if mode == 'move' else COLORS
    return f"""
QMainWindow, QWidget {{
    background-color: {C['background']};
    color: {C['foreground']};
    font-family: Arial;
    font-size: 10pt;
}}
QLabel {{
    background-color: transparent;
    color: {C['foreground']};
}}
QLabel#title_label {{
    font-size: 14pt;
    font-weight: bold;
}}
QLabel#subtitle_label {{
    font-size: 9pt;
    font-style: italic;
    color: {C['fg_secondary']};
}}
QLabel#section_label {{
    font-size: 12pt;
    font-weight: bold;
}}
QLabel#dim_label {{
    color: {C['fg_dim']};
    font-size: 9pt;
    font-style: italic;
}}
QGroupBox {{
    border: 1px solid {C['border']};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
    color: {C['foreground']};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QLineEdit {{
    background-color: {C['input_bg']};
    color: {C['input_fg']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    padding: 4px 6px;
}}
QLineEdit:focus {{
    border: 1px solid {C['accent']};
}}
QCheckBox {{
    color: {C['foreground']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {C['border']};
    border-radius: 2px;
    background-color: {C['input_bg']};
}}
QCheckBox::indicator:checked {{
    background-color: {C['accent']};
    border-color: {C['accent']};
}}
QComboBox {{
    background-color: {C['input_bg']};
    color: {C['foreground']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    padding: 4px 6px;
    selection-background-color: {C['accent']};
    selection-color: {C['button_fg']};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {C['input_bg']};
    color: {C['foreground']};
    selection-background-color: {C['accent']};
    selection-color: {C['button_fg']};
    border: 1px solid {C['border']};
}}
QPushButton {{
    background-color: {C['button_bg']};
    color: {C['button_fg']};
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 12pt;
}}
QPushButton:hover {{
    background-color: {C['button_hover']};
}}
QPushButton:disabled {{
    background-color: {C['bg_light']};
    color: {C['fg_dim']};
}}
QPushButton#cancel_btn {{
    background-color: #8B0000;
    color: {C['foreground']};
}}
QPushButton#cancel_btn:hover {{
    background-color: #a00000;
}}
QPushButton#preview_btn {{
    background-color: {C['bg_light']};
    color: {C['foreground']};
}}
QPushButton#preview_btn:hover {{
    background-color: #555555;
}}
QPushButton#preview_btn:disabled {{
    background-color: {C['bg_mid']};
    color: {C['fg_dim']};
}}
QPushButton#mode_copy_btn, QPushButton#mode_move_btn {{
    font-size: 10pt;
    padding: 5px 14px;
}}
QProgressBar {{
    border: 1px solid {C['border']};
    border-radius: 3px;
    background-color: {C['bg_light']};
    height: 20px;
    text-align: center;
    color: {C['background']};
}}
QProgressBar::chunk {{
    background-color: {C['accent']};
    border-radius: 2px;
}}
QListWidget {{
    background-color: {C['input_bg']};
    color: {C['input_fg']};
    border: 1px solid {C['border']};
    border-radius: 2px;
}}
QListWidget::item:selected {{
    background-color: {C['select_bg']};
    color: {C['select_fg']};
}}
QScrollBar:vertical {{
    background-color: {C['background']};
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {C['scrollbar_bg']};
    border-radius: 6px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: {C['background']};
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {C['scrollbar_bg']};
    border-radius: 6px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QLabel#clear_label {{
    color: {C['accent']};
    text-decoration: underline;
    font-size: 11px;
}}
QLabel#clear_label:hover {{
    color: {C['accent_hover']};
}}
QTabWidget::pane {{
    border: 1px solid {C['border']};
    background-color: {C['background']};
}}
QTabBar::tab {{
    background-color: {C['bg_mid']};
    color: {C['foreground']};
    padding: 8px 22px;
    font-size: 11pt;
    font-weight: bold;
    border: 1px solid {C['border']};
    border-bottom: none;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {C['accent']};
    color: {C['button_fg']};
    border-color: {C['accent']};
}}
QTabBar::tab:hover:!selected {{
    background-color: {C['bg_light']};
}}
QTableView {{
    background-color: {C['input_bg']};
    color: {C['foreground']};
    border: 1px solid {C['border']};
    gridline-color: {C['border']};
    alternate-background-color: {C['bg_mid']};
}}
QTableView::item {{
    padding: 4px 8px;
}}
QTableView::item:selected {{
    background-color: {C['select_bg']};
    color: {C['select_fg']};
}}
QHeaderView::section {{
    background-color: {C['bg_light']};
    color: {C['foreground']};
    border: 1px solid {C['border']};
    padding: 4px 8px;
    font-weight: bold;
}}
"""


# Backward-compatible alias
STYLESHEET = get_stylesheet('copy')
