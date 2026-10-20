"""Theme and styling management for Image Dedupe Search application"""

from typing import Dict


class Theme:
    """Base theme class"""

    def __init__(self):
        self.colors: Dict[str, str] = {}
        self.fonts: Dict[str, tuple] = {}

    def get_stylesheet(self) -> str:
        """Get QSS stylesheet for this theme"""
        raise NotImplementedError


class DarkBlueTheme(Theme):
    """Dark theme with blue accents"""

    def __init__(self):
        super().__init__()
        self.colors = {
            'background': '#1e1e2e',
            'foreground': '#89b4fa',
            'input_bg': '#313244',
            'input_fg': '#cdd6f4',
            'button_bg': '#89b4fa',
            'button_fg': '#1e1e2e',
            'button_active': '#7aa2f7',
            'button_hover': '#b4befe',
            'accent': '#45475a',
            'insert_cursor': '#89b4fa',
            'select_bg': '#89b4fa',
            'select_fg': '#1e1e2e',
            'scrollbar_bg': '#45475a',
            'scrollbar_trough': '#1e1e2e',
            'border': '#585b70',
            'disabled_bg': '#313244',
            'disabled_fg': '#6c7086',
            'success': '#a6e3a1',
            'danger': '#f38ba8',
            'warning': '#f9e2af',
            'thumbnail_bg': '#313244',
            'thumbnail_border': '#585b70',
            'thumbnail_selected': '#89b4fa',
            'similarity_high': '#a6e3a1',
            'similarity_medium': '#f9e2af',
            'similarity_low': '#f38ba8'
        }

        self.fonts = {
            'default': ('Segoe UI', 10),
            'bold': ('Segoe UI', 12, 'bold'),
            'title': ('Segoe UI', 14, 'bold'),
            'italic': ('Segoe UI', 9, 'italic'),
            'button': ('Segoe UI', 11, 'bold'),
            'small': ('Segoe UI', 9)
        }

    def get_stylesheet(self) -> str:
        """Get QSS stylesheet for dark blue theme"""
        return f"""
            /* Main Window and Widgets */
            QMainWindow, QWidget {{
                background-color: {self.colors['background']};
                color: {self.colors['foreground']};
                font-family: Segoe UI, Arial;
                font-size: 10pt;
            }}

            /* Labels */
            QLabel {{
                color: {self.colors['foreground']};
                background-color: transparent;
            }}

            QLabel[cssClass="title"] {{
                font-size: 14pt;
                font-weight: bold;
            }}

            QLabel[cssClass="section-title"] {{
                font-size: 12pt;
                font-weight: bold;
            }}

            QLabel[cssClass="status"] {{
                color: {self.colors['input_fg']};
            }}

            QLabel[cssClass="similarity-high"] {{
                color: {self.colors['success']};
                font-weight: bold;
            }}

            QLabel[cssClass="similarity-medium"] {{
                color: {self.colors['warning']};
                font-weight: bold;
            }}

            QLabel[cssClass="similarity-low"] {{
                color: {self.colors['danger']};
                font-weight: bold;
            }}

            /* Line Edit (Text Input) */
            QLineEdit {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {self.colors['select_bg']};
                selection-color: {self.colors['select_fg']};
            }}

            QLineEdit:focus {{
                border: 1px solid {self.colors['foreground']};
            }}

            QLineEdit:disabled {{
                background-color: {self.colors['disabled_bg']};
                color: {self.colors['disabled_fg']};
            }}

            /* Push Button */
            QPushButton {{
                background-color: {self.colors['button_bg']};
                color: {self.colors['button_fg']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 11pt;
            }}

            QPushButton:hover {{
                background-color: {self.colors['button_hover']};
            }}

            QPushButton:pressed {{
                background-color: {self.colors['button_active']};
            }}

            QPushButton:disabled {{
                background-color: {self.colors['disabled_bg']};
                color: {self.colors['disabled_fg']};
            }}

            QPushButton[cssClass="browse"] {{
                padding: 6px 12px;
                min-width: 30px;
                font-weight: normal;
                font-size: 10pt;
            }}

            QPushButton[cssClass="danger"] {{
                background-color: {self.colors['danger']};
                color: {self.colors['background']};
            }}

            QPushButton[cssClass="danger"]:hover {{
                background-color: #f5a3b8;
            }}

            QPushButton[cssClass="success"] {{
                background-color: {self.colors['success']};
                color: {self.colors['background']};
            }}

            QPushButton[cssClass="success"]:hover {{
                background-color: #b8edb3;
            }}

            QPushButton[cssClass="warning"] {{
                background-color: {self.colors['warning']};
                color: {self.colors['background']};
            }}

            QPushButton[cssClass="warning"]:hover {{
                background-color: #faecc0;
            }}

            /* Slider */
            QSlider::groove:horizontal {{
                border: 1px solid {self.colors['border']};
                height: 8px;
                background: {self.colors['input_bg']};
                border-radius: 4px;
            }}

            QSlider::handle:horizontal {{
                background: {self.colors['foreground']};
                border: none;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }}

            QSlider::handle:horizontal:hover {{
                background: {self.colors['button_hover']};
            }}

            QSlider::sub-page:horizontal {{
                background: {self.colors['foreground']};
                border-radius: 4px;
            }}

            /* Progress Bar */
            QProgressBar {{
                border: 1px solid {self.colors['border']};
                border-radius: 4px;
                text-align: center;
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
            }}

            QProgressBar::chunk {{
                background-color: {self.colors['foreground']};
                border-radius: 3px;
            }}

            /* List Widget (for thumbnails) */
            QListWidget {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 4px;
                selection-background-color: {self.colors['select_bg']};
                selection-color: {self.colors['select_fg']};
            }}

            QListWidget::item {{
                padding: 4px;
                border-radius: 4px;
            }}

            QListWidget::item:selected {{
                background-color: {self.colors['select_bg']};
                color: {self.colors['select_fg']};
            }}

            QListWidget::item:hover {{
                background-color: {self.colors['accent']};
            }}

            /* Scroll Bar */
            QScrollBar:vertical {{
                background-color: {self.colors['scrollbar_trough']};
                width: 12px;
                margin: 0;
            }}

            QScrollBar::handle:vertical {{
                background-color: {self.colors['scrollbar_bg']};
                min-height: 20px;
                border-radius: 6px;
                margin: 2px;
            }}

            QScrollBar::handle:vertical:hover {{
                background-color: {self.colors['foreground']};
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            QScrollBar:horizontal {{
                background-color: {self.colors['scrollbar_trough']};
                height: 12px;
                margin: 0;
            }}

            QScrollBar::handle:horizontal {{
                background-color: {self.colors['scrollbar_bg']};
                min-width: 20px;
                border-radius: 6px;
                margin: 2px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background-color: {self.colors['foreground']};
            }}

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
            }}

            /* Scroll Area */
            QScrollArea {{
                background-color: {self.colors['background']};
                border: none;
            }}

            /* Spin Box */
            QSpinBox, QDoubleSpinBox {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 4px;
                padding: 4px;
            }}

            QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {self.colors['foreground']};
            }}

            QPushButton[cssClass="spinbutton"] {{
                font-size: 14pt;
                font-weight: bold;
                padding: 0px;
                min-width: 30px;
                min-height: 30px;
            }}

            /* Combo Box */
            QComboBox {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 4px;
                padding: 4px 8px;
                padding-right: 22px;
            }}

            QComboBox:focus {{
                border: 1px solid {self.colors['foreground']};
            }}

            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 20px;
                border: none;
            }}

            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {self.colors['foreground']};
                width: 0px;
                height: 0px;
            }}

            QComboBox QAbstractItemView {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                selection-background-color: {self.colors['select_bg']};
                selection-color: {self.colors['select_fg']};
            }}

            /* Check Box */
            QCheckBox {{
                color: {self.colors['foreground']};
                spacing: 8px;
            }}

            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1px solid {self.colors['border']};
                border-radius: 4px;
                background-color: {self.colors['input_bg']};
            }}

            QCheckBox::indicator:checked {{
                background-color: {self.colors['foreground']};
                border-color: {self.colors['foreground']};
            }}

            QCheckBox::indicator:hover {{
                border-color: {self.colors['foreground']};
            }}

            /* Dialog */
            QDialog {{
                background-color: {self.colors['background']};
            }}

            /* Message Box */
            QMessageBox {{
                background-color: {self.colors['background']};
            }}

            QMessageBox QLabel {{
                color: {self.colors['input_fg']};
            }}

            /* Tool Tip */
            QToolTip {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                padding: 5px;
                border-radius: 4px;
            }}

            /* Splitter */
            QSplitter::handle {{
                background-color: {self.colors['border']};
            }}

            QSplitter::handle:horizontal {{
                width: 2px;
            }}

            QSplitter::handle:vertical {{
                height: 2px;
            }}

            /* Frame */
            QFrame {{
                background-color: transparent;
            }}

            QFrame[frameShape="4"], QFrame[frameShape="5"] {{
                background-color: {self.colors['border']};
                color: {self.colors['border']};
            }}

            QFrame[cssClass="card"] {{
                background-color: {self.colors['input_bg']};
                border: 1px solid {self.colors['border']};
                border-radius: 8px;
                padding: 8px;
            }}

            /* Group Box */
            QGroupBox {{
                color: {self.colors['foreground']};
                border: 1px solid {self.colors['border']};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """


class ThemeManager:
    """Manages application themes"""

    THEMES = {
        'dark_blue': DarkBlueTheme,
    }

    def __init__(self, theme_name: str = 'dark_blue'):
        """
        Initialize theme manager

        Args:
            theme_name: Name of theme to use
        """
        self.current_theme = None
        self.set_theme(theme_name)

    def set_theme(self, theme_name: str) -> None:
        """
        Set the current theme

        Args:
            theme_name: Name of theme to apply

        Raises:
            ValueError: If theme doesn't exist
        """
        if theme_name not in self.THEMES:
            raise ValueError(f"Theme '{theme_name}' not found")

        theme_class = self.THEMES[theme_name]
        self.current_theme = theme_class()

    def get_stylesheet(self) -> str:
        """Get the current theme's stylesheet"""
        return self.current_theme.get_stylesheet()

    def get_color(self, color_name: str) -> str:
        """
        Get a color value from current theme

        Args:
            color_name: Name of color

        Returns:
            Color hex code
        """
        return self.current_theme.colors.get(color_name, '#000000')

    def get_font(self, font_name: str) -> tuple:
        """
        Get a font tuple from current theme

        Args:
            font_name: Name of font

        Returns:
            Font tuple (family, size, style)
        """
        return self.current_theme.fonts.get(font_name, ('Segoe UI', 10))

    def get_all_colors(self) -> Dict[str, str]:
        """Get all colors from current theme"""
        return self.current_theme.colors.copy()

    def get_all_fonts(self) -> Dict[str, tuple]:
        """Get all fonts from current theme"""
        return self.current_theme.fonts.copy()
