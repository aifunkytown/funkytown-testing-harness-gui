"""Light/dark theme switching for the whole app - a Fusion QPalette swap, so
it looks consistent across Windows/Mac/Linux rather than relying on each
platform's own (inconsistent) native dark mode support.
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

_DARK_COLORS = {
    QPalette.Window: QColor(53, 53, 53),
    QPalette.WindowText: QColor(220, 220, 220),
    QPalette.Base: QColor(35, 35, 35),
    QPalette.AlternateBase: QColor(53, 53, 53),
    QPalette.ToolTipBase: QColor(220, 220, 220),
    QPalette.ToolTipText: QColor(220, 220, 220),
    QPalette.Text: QColor(220, 220, 220),
    QPalette.Button: QColor(53, 53, 53),
    QPalette.ButtonText: QColor(220, 220, 220),
    QPalette.BrightText: QColor(255, 60, 60),
    QPalette.Link: QColor(42, 130, 218),
    QPalette.Highlight: QColor(42, 130, 218),
    QPalette.HighlightedText: QColor(35, 35, 35),
    QPalette.PlaceholderText: QColor(150, 150, 150),
}

_DISABLED_DARK_COLORS = {
    QPalette.WindowText: QColor(127, 127, 127),
    QPalette.Text: QColor(127, 127, 127),
    QPalette.ButtonText: QColor(127, 127, 127),
    QPalette.Highlight: QColor(80, 80, 80),
    QPalette.HighlightedText: QColor(127, 127, 127),
}


def apply_theme(app: QApplication, dark: bool):
    app.setStyle(QStyleFactory.create("Fusion"))

    if not dark:
        app.setPalette(app.style().standardPalette())
        return

    palette = QPalette()
    for role, color in _DARK_COLORS.items():
        palette.setColor(QPalette.Active, role, color)
        palette.setColor(QPalette.Inactive, role, color)
    for role, color in _DISABLED_DARK_COLORS.items():
        palette.setColor(QPalette.Disabled, role, color)
    app.setPalette(palette)
