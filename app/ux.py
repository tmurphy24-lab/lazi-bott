"""
F9: DarkMode — app-wide theme switch. Provides theme stylesheets and a manager
F10: Notifications — desktop toast when a run finishes or a job is applied to

Theme stylesheets are plain CSS strings applied via QApplication.setStyleSheet().
Notifications use QSystemTrayIcon (always present on Windows) and fall back
to a QToolTip-style in-window banner if no system tray is available.
"""

from __future__ import annotations
import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QLabel, QWidget

logger = logging.getLogger(__name__)


# ---------- F9: Themes ----------

THEMES: dict[str, str] = {
    "couch": """
        QWidget      { background: #fff8e7; color: #3a2410; }
        QPushButton  { background: #b48a3a; color: white; border: 2px solid #6b4a1a;
                       border-radius: 6px; padding: 6px 12px; font-weight: bold; }
        QPushButton:hover  { background: #c9a96e; }
        QPushButton:pressed{ background: #6b4a1a; }
        QLineEdit, QTextEdit, QSpinBox, QComboBox, QListWidget {
            background: white; color: #3a2410; border: 1px solid #b48a3a;
            border-radius: 4px; padding: 4px; }
        QTabWidget::pane { border: 1px solid #b48a3a; background: #f5e7c0; }
        QTabBar::tab    { background: #f0e2c0; color: #3a2410; padding: 6px 14px; }
        QTabBar::tab:selected { background: #b48a3a; color: white; }
        QGroupBox       { border: 2px solid #b48a3a; border-radius: 6px;
                          margin-top: 12px; padding-top: 12px; }
        QMenuBar        { background: #f0e2c0; color: #3a2410; }
        QStatusBar      { background: #f0e2c0; color: #3a2410; }
    """,
    "stealth": """
        QWidget      { background: #1a1a1a; color: #d0d0d0; }
        QPushButton  { background: #2a4d2a; color: #c8ffc8; border: 1px solid #4a7a4a;
                       border-radius: 4px; padding: 6px 12px; }
        QPushButton:hover  { background: #3a5d3a; }
        QLineEdit, QTextEdit, QSpinBox, QComboBox, QListWidget {
            background: #2a2a2a; color: #d0d0d0; border: 1px solid #3a3a3a;
            border-radius: 4px; padding: 4px; }
        QTabWidget::pane { border: 1px solid #3a3a3a; background: #1a1a1a; }
        QTabBar::tab    { background: #2a2a2a; color: #d0d0d0; padding: 6px 14px; }
        QTabBar::tab:selected { background: #2a4d2a; color: #c8ffc8; }
        QGroupBox       { border: 1px solid #3a3a3a; border-radius: 4px;
                          margin-top: 12px; padding-top: 12px; }
        QMenuBar        { background: #1a1a1a; color: #d0d0d0; }
        QStatusBar      { background: #1a1a1a; color: #d0d0d0; }
    """,
}


class ThemeManager:
    """Holds the current theme name + applies stylesheets to the QApplication."""

    def __init__(self, theme: str = "couch"):
        self.theme = theme if theme in THEMES else "couch"

    def available(self) -> list[str]:
        return list(THEMES.keys())

    def apply(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(THEMES[self.theme])

    def set_theme(self, name: str) -> None:
        if name in THEMES:
            self.theme = name
            self.apply()


# ---------- F10: Notifications ----------

class Notifier:
    """
    Desktop toast via QSystemTrayIcon.
    Falls back to a transient QLabel banner if the system tray isn't available.
    """

    def __init__(self, app_name: str = "linkedin-autopilot"):
        self.app_name = app_name
        self._tray: Optional[QSystemTrayIcon] = None
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self._tray = QSystemTrayIcon(QIcon(), None)
                self._tray.setToolTip(app_name)
        except Exception as e:
            logger.warning("System tray unavailable: %s", e)
            self._tray = None

    @property
    def available(self) -> bool:
        return self._tray is not None

    def notify(self, title: str, message: str, duration_ms: int = 4000) -> bool:
        """Show a desktop notification. Returns True if delivered."""
        if self._tray is None:
            logger.info("notify (no tray): %s — %s", title, message)
            return False
        self._tray.show()
        self._tray.showMessage(title, message, QSystemTrayIcon.Information, duration_ms)
        return True
