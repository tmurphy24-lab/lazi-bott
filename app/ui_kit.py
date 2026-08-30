"""
Design system / shared UI kit for linkedin-autopilot.

Provides:
  - LaziColors: central color tokens (Lazi palette)
  - Font: app-wide font choice
  - Toast: non-blocking notification in the corner (replaces QMessageBox spam)
  - Card: a styled rounded-rectangle container (used for persona cards, game cards, etc.)
  - SectionHeader: a QLabel with the app's section-header style
  - EmptyState: a centered icon + title + body + action button
  - StatusBadge: a small colored pill (OK/Warn/Error/Info)
  - Spacer: a thin helper
  - apply_app_theme(app, theme_name): one source of truth for app-wide stylesheet

All widgets support light ("couch") and dark ("stealth") themes via `repolish()`.
"""

from __future__ import annotations
import logging
from typing import Optional, List, Callable

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGraphicsDropShadowEffect,
)

logger = logging.getLogger(__name__)


# === Color tokens (single source of truth) ===

class LaziColors:
    # Couch (light)
    COUCH_BG          = "#fff8e7"
    COUCH_PANEL       = "#f0e2c0"
    COUCH_PANEL_2     = "#f5e7c0"
    COUCH_CUSHION     = "#c9a96e"
    COUCH_CUSHION_DK  = "#a07a3a"
    COUCH_ACCENT      = "#b48a3a"
    COUCH_ACCENT_DK   = "#6b4a1a"
    COUCH_TEXT        = "#3a2410"
    COUCH_TEXT_MUTED  = "#7a5a2a"
    COUCH_DANGER       = "#a02a2a"
    COUCH_SUCCESS     = "#2a7a2a"
    COUCH_INFO        = "#1a4d8a"

    # Stealth (dark)
    STEALTH_BG        = "#1a1a1a"
    STEALTH_PANEL     = "#2a2a2a"
    STEALTH_PANEL_2   = "#222222"
    STEALTH_CUSHION   = "#2a4d2a"
    STEALTH_CUSHION_DK= "#1a3d1a"
    STEALTH_ACCENT    = "#3a5d3a"
    STEALTH_ACCENT_DK = "#4a7a4a"
    STEALTH_TEXT      = "#d0d0d0"
    STEALTH_TEXT_MUTED= "#888888"
    STEALTH_DANGER    = "#ff6b6b"
    STEALTH_SUCCESS   = "#7ad27a"
    STEALTH_INFO      = "#6ba4ff"


# === Theme application (one source of truth) ===

THEME_QSS = {
    "couch": f"""
        QWidget      {{ background: {LaziColors.COUCH_BG}; color: {LaziColors.COUCH_TEXT}; }}
        QMainWindow  {{ background: {LaziColors.COUCH_BG}; }}
        QPushButton  {{ background: {LaziColors.COUCH_ACCENT}; color: white; border: 2px solid {LaziColors.COUCH_ACCENT_DK};
                        border-radius: 6px; padding: 6px 12px; font-weight: bold; }}
        QPushButton:hover  {{ background: {LaziColors.COUCH_CUSHION}; }}
        QPushButton:pressed{{ background: {LaziColors.COUCH_ACCENT_DK}; }}
        QPushButton:disabled {{ background: #999; color: #ddd; border: 2px solid #777; }}
        QLineEdit, QTextEdit, QSpinBox, QComboBox, QListWidget, QPlainTextEdit {{
            background: white; color: {LaziColors.COUCH_TEXT}; border: 1px solid {LaziColors.COUCH_ACCENT};
            border-radius: 4px; padding: 4px; }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border: 2px solid {LaziColors.COUCH_ACCENT_DK}; }}
        QTabWidget::pane {{ border: 1px solid {LaziColors.COUCH_ACCENT}; background: {LaziColors.COUCH_PANEL_2}; }}
        QTabBar::tab    {{ background: {LaziColors.COUCH_PANEL}; color: {LaziColors.COUCH_TEXT};
                          padding: 8px 16px; border-top-left-radius: 4px; border-top-right-radius: 4px; }}
        QTabBar::tab:selected {{ background: {LaziColors.COUCH_ACCENT}; color: white; font-weight: bold; }}
        QTabBar::tab:hover:!selected {{ background: {LaziColors.COUCH_CUSHION}; color: {LaziColors.COUCH_TEXT}; }}
        QGroupBox       {{ border: 2px solid {LaziColors.COUCH_ACCENT}; border-radius: 8px;
                           margin-top: 14px; padding-top: 12px; font-weight: bold; color: {LaziColors.COUCH_TEXT}; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
        QMenuBar        {{ background: {LaziColors.COUCH_PANEL}; color: {LaziColors.COUCH_TEXT}; }}
        QStatusBar      {{ background: {LaziColors.COUCH_PANEL}; color: {LaziColors.COUCH_TEXT}; }}
        QProgressBar    {{ background: white; color: {LaziColors.COUCH_TEXT};
                           border: 1px solid {LaziColors.COUCH_ACCENT}; border-radius: 4px;
                           text-align: center; }}
        QProgressBar::chunk {{ background: {LaziColors.COUCH_ACCENT}; }}
        QCheckBox        {{ spacing: 6px; }}
        QTableWidget      {{ gridline-color: {LaziColors.COUCH_CUSHION}; background: white; }}
        QHeaderView::section {{ background: {LaziColors.COUCH_PANEL}; padding: 4px;
                                 border: 1px solid {LaziColors.COUCH_ACCENT}; font-weight: bold; }}
    """,
    "stealth": f"""
        QWidget      {{ background: {LaziColors.STEALTH_BG}; color: {LaziColors.STEALTH_TEXT}; }}
        QMainWindow  {{ background: {LaziColors.STEALTH_BG}; }}
        QPushButton  {{ background: {LaziColors.STEALTH_ACCENT}; color: {LaziColors.STEALTH_TEXT};
                        border: 1px solid {LaziColors.STEALTH_ACCENT_DK};
                        border-radius: 4px; padding: 6px 12px; }}
        QPushButton:hover  {{ background: {LaziColors.STEALTH_CUSHION}; }}
        QPushButton:disabled {{ background: #444; color: #888; }}
        QLineEdit, QTextEdit, QSpinBox, QComboBox, QListWidget, QPlainTextEdit {{
            background: {LaziColors.STEALTH_PANEL}; color: {LaziColors.STEALTH_TEXT};
            border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px; }}
        QTabWidget::pane {{ border: 1px solid #3a3a3a; background: {LaziColors.STEALTH_BG}; }}
        QTabBar::tab    {{ background: {LaziColors.STEALTH_PANEL}; color: {LaziColors.STEALTH_TEXT}; padding: 8px 16px; }}
        QTabBar::tab:selected {{ background: {LaziColors.STEALTH_ACCENT}; color: #c8ffc8; font-weight: bold; }}
        QGroupBox       {{ border: 1px solid #3a3a3a; border-radius: 4px;
                           margin-top: 14px; padding-top: 12px; color: {LaziColors.STEALTH_TEXT}; }}
        QStatusBar      {{ background: #1a1a1a; color: {LaziColors.STEALTH_TEXT}; }}
        QProgressBar    {{ background: #2a2a2a; color: {LaziColors.STEALTH_TEXT};
                           border: 1px solid #3a3a3a; border-radius: 4px; text-align: center; }}
        QProgressBar::chunk {{ background: {LaziColors.STEALTH_ACCENT}; }}
        QTableWidget      {{ gridline-color: #3a3a3a; background: {LaziColors.STEALTH_PANEL}; }}
        QHeaderView::section {{ background: {LaziColors.STEALTH_PANEL_2}; padding: 4px;
                                 border: 1px solid #3a3a3a; color: {LaziColors.STEALTH_TEXT}; }}
    """,
}


def apply_app_theme(app: QApplication, theme_name: str = "couch") -> None:
    if theme_name in THEME_QSS:
        app.setStyleSheet(THEME_QSS[theme_name])
    else:
        app.setStyleSheet(THEME_QSS["couch"])


# === Toast: non-blocking corner notification ===

class Toast(QWidget):
    """
    A small floating notification that appears in the bottom-right of a parent
    QMainWindow, persists for `duration_ms`, then fades out.
    Replaces QMessageBox.information() for non-critical feedback.
    """
    LEVELS = {
        "info":    ("ℹ", "#1a4d8a", "#cfe4ff"),
        "success": ("✓", "#2a7a2a", "#d4f4d4"),
        "warn":    ("!", "#a07a2a", "#f4e4b8"),
        "error":   ("✗", "#a02a2a", "#f4c8c8"),
    }

    def __init__(self, parent: QWidget, message: str, level: str = "info",
                  duration_ms: int = 3500):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        icon, fg, bg = self.LEVELS.get(level, self.LEVELS["info"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: white; font-size: 16px; font-weight: bold;")
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("color: white; font-size: 13px;")
        msg_lbl.setWordWrap(True)
        msg_lbl.setMaximumWidth(360)
        layout.addWidget(icon_lbl)
        layout.addWidget(msg_lbl, stretch=1)
        self.setStyleSheet(
            f"background: {fg}; color: white; border-radius: 8px; padding: 4px;"
        )
        # shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)
        self.adjustSize()
        # position bottom-right of parent
        self._position_in_parent(parent)
        # fade animation (simple opacity)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(300)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.start()
        # auto-dismiss
        QTimer.singleShot(duration_ms, self._fade_out)

    def _position_in_parent(self, parent: QWidget):
        if parent is None:
            return
        parent_geo = parent.geometry()
        x = parent_geo.x() + parent_geo.width() - self.width() - 24
        y = parent_geo.y() + parent_geo.height() - self.height() - 24
        self.move(QPoint(x, y))
        self.show()

    def _fade_out(self):
        try:
            self._opacity_anim.setStartValue(1.0)
            self._opacity_anim.setEndValue(0.0)
            self._opacity_anim.finished.connect(self.deleteLater)
            self._opacity_anim.start()
        except RuntimeError:
            self.deleteLater()


class ToastManager:
    """Singleton helper: ToastManager.show(parent, msg, level='info')."""

    @staticmethod
    def show(parent: QWidget, message: str, level: str = "info",
              duration_ms: int = 3500) -> Toast:
        return Toast(parent, message, level=level, duration_ms=duration_ms)


# === Card: a styled rounded rectangle container ===

class Card(QFrame):
    """A rounded-rectangle card with title + content. Use as a container."""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            "QFrame { background: white; border: 2px solid #b48a3a; border-radius: 10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        if title:
            h = QLabel(title)
            h.setStyleSheet("font-size: 16px; font-weight: bold; color: #3a2410;")
            layout.addWidget(h)
        self.body = QVBoxLayout()
        layout.addLayout(self.body)

    def add_widget(self, w: QWidget) -> None:
        self.body.addWidget(w)


# === EmptyState: centered icon + title + body + action ===

class EmptyState(QWidget):
    """Friendly empty-state with icon, title, body text, and an action button."""

    def __init__(self, icon: str = "👋", title: str = "Nothing here yet",
                  body: str = "", action_text: str = "",
                  on_action: Optional[Callable] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 48px;")
        ic.setAlignment(Qt.AlignCenter)
        layout.addWidget(ic)
        ti = QLabel(title)
        ti.setStyleSheet("font-size: 18px; font-weight: bold; color: #3a2410;")
        ti.setAlignment(Qt.AlignCenter)
        ti.setWordWrap(True)
        layout.addWidget(ti)
        if body:
            bd = QLabel(body)
            bd.setStyleSheet("color: #7a5a2a; font-size: 13px;")
            bd.setAlignment(Qt.AlignCenter)
            bd.setWordWrap(True)
            layout.addWidget(bd)
        if action_text:
            btn = QPushButton(action_text)
            btn.setStyleSheet(
                "background: #b48a3a; color: white; padding: 8px 18px; "
                "border-radius: 6px; font-weight: bold;"
            )
            if on_action:
                btn.clicked.connect(on_action)
            layout.addWidget(btn, alignment=Qt.AlignCenter)
        layout.addStretch()


# === StatusBadge: small colored pill ===

class StatusBadge(QLabel):
    """A small colored pill. e.g. 'ON', 'OFF', 'OK', 'ERR'."""

    def __init__(self, text: str = "", level: str = "info", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.set_level(level)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(self.styleSheet() + "font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 8px;")
        self.setMargin(0)
        self.setMinimumWidth(36)

    def set_level(self, level: str) -> None:
        colors = {
            "info":    ("#1a4d8a", "#cfe4ff"),
            "success": ("#2a7a2a", "#d4f4d4"),
            "warn":    ("#a07a2a", "#f4e4b8"),
            "error":   ("#a02a2a", "#f4c8c8"),
        }
        fg, bg = colors.get(level, colors["info"])
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; padding: 2px 8px; "
            f"border-radius: 8px; font-weight: bold; font-size: 11px; }}"
        )
        self._level = level

    def set_text(self, text: str, level: Optional[str] = None) -> None:
        self.setText(text)
        if level:
            self.set_level(level)


# === Section header ===

class SectionHeader(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #6b4a1a; padding: 8px;"
        )
