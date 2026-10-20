"""Theme and styling management for File Rename Mover application (PySide6 version)"""

from typing import Dict


class Theme:
    """Base theme class"""

    def __init__(self):
        self.colors: Dict[str, str] = {}
        self.fonts: Dict[str, tuple] = {}

    def get_stylesheet(self) -> str:
        """Get QSS stylesheet for this theme"""
        raise NotImplementedError


class DarkRedTheme(Theme):
    """Dark theme with red accents"""

    def __init__(self):
        super().__init__()
        self.colors = {
            'background': '#1a1a1a',
            'foreground': '#ff4444',
            'input_bg': '#2d2d2d',
            'input_fg': '#ffffff',
            'button_bg': '#ff4444',
            'button_fg': '#ffffff',
            'button_active': '#cc3333',
            'button_hover': '#ff6666',
            'accent': '#333333',
            'insert_cursor': '#ff4444',
            'select_bg': '#ff4444',
            'select_fg': '#ffffff',
            'scrollbar_bg': '#333333',
            'scrollbar_trough': '#1a1a1a',
            'border': '#444444',
            'disabled_bg': '#1f1f1f',
            'disabled_fg': '#666666'
        }

        self.fonts = {
            'default': ('Arial', 10),
            'bold': ('Arial', 12, 'bold'),
            'title': ('Arial', 14, 'bold'),
            'italic': ('Arial', 9, 'italic'),
            'button': ('Arial', 12, 'bold')
        }

    def get_stylesheet(self) -> str:
        """Get QSS stylesheet for dark red theme"""
        return f"""
            /* Main Window and Widgets */
            QMainWindow, QWidget {{
                background-color: {self.colors['background']};
                color: {self.colors['foreground']};
                font-family: Arial;
                font-size: 10pt;
            }}

            /* Labels */
            QLabel {{
                color: {self.colors['foreground']};
                background-color: transparent;
            }}

            /* Line Edit (Text Input) */
            QLineEdit {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 3px;
                padding: 5px;
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
                border-radius: 3px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12pt;
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

            /* Small buttons (browse buttons) */
            QPushButton[cssClass="browse"] {{
                padding: 5px 10px;
                min-width: 30px;
                font-weight: normal;
                font-size: 10pt;
            }}

            /* Combo Box */
            QComboBox {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 3px;
                padding: 5px;
                min-height: 20px;
            }}

            QComboBox:hover {{
                border: 1px solid {self.colors['foreground']};
            }}

            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}

            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {self.colors['foreground']};
                margin-right: 5px;
            }}

            QComboBox QAbstractItemView {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                selection-background-color: {self.colors['select_bg']};
                selection-color: {self.colors['select_fg']};
                border: 1px solid {self.colors['border']};
            }}

            /* Check Box */
            QCheckBox {{
                color: {self.colors['foreground']};
                spacing: 8px;
            }}

            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {self.colors['border']};
                border-radius: 3px;
                background-color: {self.colors['input_bg']};
            }}

            QCheckBox::indicator:checked {{
                background-color: {self.colors['foreground']};
                border-color: {self.colors['foreground']};
            }}

            QCheckBox::indicator:hover {{
                border-color: {self.colors['foreground']};
            }}

            /* List Widget */
            QListWidget {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 3px;
                selection-background-color: {self.colors['select_bg']};
                selection-color: {self.colors['select_fg']};
            }}

            QListWidget::item {{
                padding: 3px;
            }}

            QListWidget::item:selected {{
                background-color: {self.colors['select_bg']};
                color: {self.colors['select_fg']};
            }}

            QListWidget::item:hover {{
                background-color: {self.colors['accent']};
            }}

            /* Text Edit */
            QTextEdit {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                border-radius: 3px;
                selection-background-color: {self.colors['select_bg']};
                selection-color: {self.colors['select_fg']};
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

            /* Group Box */
            QGroupBox {{
                color: {self.colors['foreground']};
                border: 1px solid {self.colors['border']};
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
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

            /* Input Dialog */
            QInputDialog {{
                background-color: {self.colors['background']};
            }}

            /* Tool Tip */
            QToolTip {{
                background-color: {self.colors['input_bg']};
                color: {self.colors['input_fg']};
                border: 1px solid {self.colors['border']};
                padding: 5px;
            }}

            /* Frame */
            QFrame {{
                background-color: transparent;
            }}

            /* Section title style */
            QLabel[cssClass="title"] {{
                font-size: 14pt;
                font-weight: bold;
            }}

            QLabel[cssClass="section-title"] {{
                font-size: 12pt;
                font-weight: bold;
            }}

            QLabel[cssClass="italic"] {{
                font-style: italic;
                font-size: 9pt;
            }}
        """


class ThemeManager:
    """Manages application themes"""

    THEMES = {
        'dark_red': DarkRedTheme,
    }

    def __init__(self, theme_name: str = 'dark_red'):
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
        return self.current_theme.fonts.get(font_name, ('Arial', 10))

    def get_all_colors(self) -> Dict[str, str]:
        """Get all colors from current theme"""
        return self.current_theme.colors.copy()

    def get_all_fonts(self) -> Dict[str, tuple]:
        """Get all fonts from current theme"""
        return self.current_theme.fonts.copy()
