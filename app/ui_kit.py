"""
Design system / shared UI kit for linkedin-autopilot.

v3.1 (refactor 2026-08-30): full Refactoring UI redesign

Principles applied (from /refactoring-ui):
  1. Grayscale first, color last — LaziColors builds a 9-shade gray + a single warm accent
  2. Constrained spacing scale: 4, 8, 12, 16, 24, 32, 48, 64 (no arbitrary px)
  3. Modular type scale: 12, 13, 14, 16, 18, 20, 24, 30, 36
  4. Shadow scale (sm/md/lg/xl) — each shadow is two layers: tight dark + soft spread
  5. Hierarchy via size + weight + color (not all three at once on the same element)
  6. Cards group related content; sections separated by 24-32px
  7. Empty states use an illustration + title + body + CTA, not just a sad message

Public API (everything else in the app uses these):
  SPACING             — dict of named sizes (xs..xxxl)
  TYPE                — dict of named font sizes + weights
  SHADOWS             — dict of named drop-shadow strings
  LaziColors          — full color palette (couch + stealth)
  apply_app_theme     — applies one QSS to the whole app
  Toast / ToastManager— non-blocking corner notification
  Card                — rounded-rectangle container
  EmptyState          — centered icon + title + body + action
  StatusBadge         — small colored pill
  SectionHeader       — standard section heading
  StatBlock           — large number + small label (dashboards)
  IconLabel           — icon + text tightly-coupled pair
  Divider             — 1px subtle separator
  Toolbar             — left/center/right horizontal bar
"""

from __future__ import annotations
import logging
from typing import Optional, Callable, Dict, Any

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGraphicsDropShadowEffect, QSizePolicy,
)

logger = logging.getLogger(__name__)


# === SPACING SCALE (4-based) ===
# Use these everywhere instead of raw px. The smallest unit is 4px.

SPACING = {
    "xs":   4,
    "sm":   8,
    "md":  12,
    "lg":  16,
    "xl":  24,
    "xxl": 32,
    "xxxl":48,
    "huge":64,
}


# === TYPE SCALE ===
# 1.25 modular scale. Body 16/1.6 (relaxed). Headings 1.2-1.4 (tight).

TYPE = {
    "xs":   {"size": 12, "weight": 500, "line_height": 1.4},
    "sm":   {"size": 13, "weight": 500, "line_height": 1.4},
    "base": {"size": 14, "weight": 400, "line_height": 1.6},
    "md":   {"size": 16, "weight": 400, "line_height": 1.6},
    "lg":   {"size": 18, "weight": 500, "line_height": 1.4},
    "xl":   {"size": 22, "weight": 600, "line_height": 1.3},
    "2xl":  {"size": 28, "weight": 700, "line_height": 1.2},
    "3xl":  {"size": 36, "weight": 700, "line_height": 1.1},
}


# === SHADOW SCALE ===
# Each shadow is a CSS-style blur+spread. The first part is the tight dark
# drop (crispness), the second is the soft spread (atmosphere). The "couch" theme
# uses warm-tinted shadows, the "stealth" theme uses cool-tinted ones.

SHADOWS = {
    "none": "none",
    "sm":   "0 1px 2px rgba(60, 30, 0, 0.08), 0 1px 3px rgba(60, 30, 0, 0.06)",
    "md":   "0 2px 4px rgba(60, 30, 0, 0.07), 0 4px 8px rgba(60, 30, 0, 0.08)",
    "lg":   "0 4px 6px rgba(60, 30, 0, 0.07), 0 10px 20px rgba(60, 30, 0, 0.10)",
    "xl":   "0 8px 12px rgba(60, 30, 0, 0.10), 0 20px 40px rgba(60, 30, 0, 0.14)",
}


# === COLOR TOKENS (cool-tinted grays + warm couch accent) ===
# All 9 shades per color. Grays have a subtle blue tint to feel modern.
# Body text minimum 4.5:1 contrast on background.

class LaziColors:
    # Couch theme — warm caramel / coffee
    COUCH_BG          = "#fdf8ee"   # page surface
    COUCH_BG_RAISED   = "#ffffff"   # card surface
    COUCH_BG_SUNKEN   = "#f0e2c0"   # sunken panel (sidebar)
    COUCH_BG_HEADER   = "#e8d8a8"   # header strip
    COUCH_CUSHION     = "#c9a96e"   # warm tan
    COUCH_CUSHION_DK  = "#a07a3a"   # warm tan dark
    COUCH_ACCENT      = "#b48a3a"   # primary action
    COUCH_ACCENT_DK   = "#6b4a1a"   # pressed / hover-dk
    COUCH_TEXT        = "#3a2410"   # 12.5:1 on COUCH_BG (AA+)
    COUCH_TEXT_MED    = "#6b4a1a"   # 5.2:1
    COUCH_TEXT_MUTED  = "#9c7a3a"   # 3.4:1 (large text only)
    COUCH_BORDER      = "#d4b878"   # subtle border
    COUCH_BORDER_STR  = "#a07a3a"   # stronger border
    COUCH_DANGER       = "#a02a2a"
    COUCH_SUCCESS     = "#2a7a2a"
    COUCH_INFO        = "#1a4d8a"
    COUCH_WARN        = "#a07a2a"

    # Stealth theme — dark, with a deep green accent
    STEALTH_BG          = "#0e0e0e"
    STEALTH_BG_RAISED   = "#1a1a1a"
    STEALTH_BG_SUNKEN   = "#141414"
    STEALTH_BG_HEADER   = "#1f1f1f"
    STEALTH_CUSHION     = "#2a4d2a"
    STEALTH_CUSHION_DK  = "#1a3d1a"
    STEALTH_ACCENT      = "#3a5d3a"
    STEALTH_ACCENT_DK   = "#4a7a4a"
    STEALTH_TEXT        = "#e8e8e8"   # 14.5:1
    STEALTH_TEXT_MED    = "#b8b8b8"   # 8.5:1
    STEALTH_TEXT_MUTED  = "#707070"   # 3.6:1 (large only)
    STEALTH_BORDER      = "#2a2a2a"
    STEALTH_BORDER_STR  = "#404040"
    STEALTH_DANGER    = "#ff6b6b"
    STEALTH_SUCCESS   = "#7ad27a"
    STEALTH_INFO      = "#6ba4ff"
    STEALTH_WARN      = "#e0c060"


# === THEME QSS (one source of truth) ===

THEME_QSS = {
    "couch": f"""
        /* base */
        QWidget, QMainWindow, QDialog {{
            background: {LaziColors.COUCH_BG}; color: {LaziColors.COUCH_TEXT};
            font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
            font-size: 14px;
        }}
        QLabel {{ background: transparent; }}

        /* text variants */
        QLabel[type="muted"]   {{ color: {LaziColors.COUCH_TEXT_MUTED}; font-size: 12px; }}
        QLabel[type="med"]     {{ color: {LaziColors.COUCH_TEXT_MED}; }}
        QLabel[type="h1"]      {{ font-size: 28px; font-weight: 700; color: {LaziColors.COUCH_TEXT}; padding: 4px 0; }}
        QLabel[type="h2"]      {{ font-size: 22px; font-weight: 600; color: {LaziColors.COUCH_TEXT}; padding: 2px 0; }}
        QLabel[type="h3"]      {{ font-size: 18px; font-weight: 600; color: {LaziColors.COUCH_TEXT}; padding: 2px 0; }}
        QLabel[type="caption"] {{ font-size: 12px; color: {LaziColors.COUCH_TEXT_MED}; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}

        /* buttons */
        QPushButton {{
            background: {LaziColors.COUCH_ACCENT}; color: white;
            border: none; border-radius: 6px;
            padding: 8px 16px; font-weight: 600; font-size: 14px;
            min-height: 16px;
        }}
        QPushButton:hover  {{ background: {LaziColors.COUCH_CUSHION}; }}
        QPushButton:pressed{{ background: {LaziColors.COUCH_ACCENT_DK}; padding: 9px 16px 7px 16px; }}
        QPushButton:disabled{{ background: #c9b88a; color: #f5ebd0; }}
        QPushButton[variant="primary"] {{
            background: {LaziColors.COUCH_SUCCESS};
        }}
        QPushButton[variant="primary"]:hover  {{ background: #3a8a3a; }}
        QPushButton[variant="primary"]:pressed{{ background: #1a5a1a; padding: 9px 16px 7px 16px; }}
        QPushButton[variant="danger"] {{
            background: {LaziColors.COUCH_DANGER};
        }}
        QPushButton[variant="danger"]:hover  {{ background: #c03838; }}
        QPushButton[variant="danger"]:pressed{{ background: #7a1a1a; padding: 9px 16px 7px 16px; }}
        QPushButton[variant="ghost"] {{
            background: transparent; color: {LaziColors.COUCH_TEXT};
            border: 1px solid {LaziColors.COUCH_BORDER};
        }}
        QPushButton[variant="ghost"]:hover {{
            background: {LaziColors.COUCH_BG_SUNKEN};
            border-color: {LaziColors.COUCH_BORDER_STR};
        }}
        QPushButton[variant="ghost"]:pressed {{
            background: {LaziColors.COUCH_CUSHION};
        }}
        QPushButton:focus {{
            outline: 2px solid {LaziColors.COUCH_ACCENT_DK};
            outline-offset: 2px;
        }}

        /* inputs */
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QListWidget {{
            background: {LaziColors.COUCH_BG_RAISED}; color: {LaziColors.COUCH_TEXT};
            border: 1px solid {LaziColors.COUCH_BORDER};
            border-radius: 6px; padding: 6px 8px; selection-background-color: {LaziColors.COUCH_ACCENT};
        }}
        QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QComboBox:hover {{
            border-color: {LaziColors.COUCH_BORDER_STR};
        }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border: 2px solid {LaziColors.COUCH_ACCENT}; padding: 5px 7px;
        }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox::down-arrow {{ width: 12px; height: 12px; }}
        QComboBox QAbstractItemView {{
            background: {LaziColors.COUCH_BG_RAISED};
            color: {LaziColors.COUCH_TEXT};
            border: 1px solid {LaziColors.COUCH_BORDER};
            selection-background-color: {LaziColors.COUCH_ACCENT};
            selection-color: white;
            padding: 4px;
        }}
        QTextEdit, QPlainTextEdit {{ line-height: 1.6; }}

        /* tabs */
        QTabWidget::pane {{ border: 1px solid {LaziColors.COUCH_BORDER}; background: {LaziColors.COUCH_BG_SUNKEN}; border-radius: 0 6px 6px 6px; }}
        QTabBar::tab {{
            background: {LaziColors.COUCH_BG_SUNKEN}; color: {LaziColors.COUCH_TEXT_MED};
            padding: 8px 16px; border: 1px solid transparent;
            border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 1px;
        }}
        QTabBar::tab:selected {{
            background: {LaziColors.COUCH_BG}; color: {LaziColors.COUCH_TEXT}; font-weight: 600;
            border: 1px solid {LaziColors.COUCH_BORDER};
            border-bottom-color: {LaziColors.COUCH_BG}; border-bottom-width: 0;
        }}
        QTabBar::tab:hover:!selected {{ background: {LaziColors.COUCH_CUSHION}; color: {LaziColors.COUCH_TEXT}; }}

        /* groupbox */
        QGroupBox {{
            background: {LaziColors.COUCH_BG_RAISED};
            border: 1px solid {LaziColors.COUCH_BORDER}; border-radius: 8px;
            margin-top: 16px; padding: 16px 12px 12px 12px; font-weight: 600;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {LaziColors.COUCH_TEXT}; }}

        /* status & menu */
        QStatusBar {{ background: {LaziColors.COUCH_BG_HEADER}; color: {LaziColors.COUCH_TEXT_MED}; }}
        QMenuBar  {{ background: {LaziColors.COUCH_BG_HEADER}; color: {LaziColors.COUCH_TEXT}; }}
        QMenu     {{ background: {LaziColors.COUCH_BG_RAISED}; border: 1px solid {LaziColors.COUCH_BORDER}; }}

        /* progress */
        QProgressBar {{
            background: {LaziColors.COUCH_BG_RAISED}; color: {LaziColors.COUCH_TEXT};
            border: 1px solid {LaziColors.COUCH_BORDER}; border-radius: 4px; text-align: center;
        }}
        QProgressBar::chunk {{ background: {LaziColors.COUCH_ACCENT}; border-radius: 3px; }}

        /* tables */
        QTableWidget, QTableView {{
            background: {LaziColors.COUCH_BG_RAISED}; color: {LaziColors.COUCH_TEXT}; gridline-color: {LaziColors.COUCH_BORDER};
            selection-background-color: {LaziColors.COUCH_ACCENT}; selection-color: white;
            border: 1px solid {LaziColors.COUCH_BORDER}; border-radius: 6px;
        }}
        QHeaderView::section {{
            background: {LaziColors.COUCH_BG_SUNKEN}; color: {LaziColors.COUCH_TEXT_MED};
            padding: 6px 8px; border: none;
            border-right: 1px solid {LaziColors.COUCH_BORDER};
            border-bottom: 1px solid {LaziColors.COUCH_BORDER};
            font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
        }}

        /* checkboxes */
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; border-radius: 3px;
            border: 1.5px solid {LaziColors.COUCH_BORDER_STR}; background: {LaziColors.COUCH_BG_RAISED};
        }}
        QCheckBox::indicator:checked {{
            background: {LaziColors.COUCH_ACCENT}; border-color: {LaziColors.COUCH_ACCENT_DK};
        }}
        QCheckBox::indicator:hover {{ border-color: {LaziColors.COUCH_ACCENT}; }}

        /* sidebar + nav buttons */
        QWidget#sidebar {{
            background: {LaziColors.COUCH_BG_SUNKEN};
            border-right: 1px solid {LaziColors.COUCH_BORDER};
        }}
        QPushButton[nav="true"] {{
            background: transparent; color: {LaziColors.COUCH_TEXT_MED};
            border: none; border-left: 3px solid transparent;
            text-align: left; padding: 10px 12px; font-size: 14px; font-weight: 500;
        }}
        QPushButton[nav="true"]:hover {{
            background: {LaziColors.COUCH_BG_RAISED};
            color: {LaziColors.COUCH_TEXT};
            border-left-color: {LaziColors.COUCH_CUSHION};
        }}
        QPushButton[nav="true"]:pressed {{
            background: {LaziColors.COUCH_BG_SUNKEN};
            padding: 11px 12px 9px 12px;
        }}
        QPushButton[nav="true"]:checked {{
            background: {LaziColors.COUCH_BG};
            color: {LaziColors.COUCH_TEXT}; font-weight: 700;
            border-left: 3px solid {LaziColors.COUCH_ACCENT};
        }}
        QPushButton[nav="true"]:checked:hover {{
            background: {LaziColors.COUCH_BG};
            border-left-color: {LaziColors.COUCH_ACCENT_DK};
        }}
        QPushButton[nav="true"]:focus {{
            outline: none;
            border-left: 3px solid {LaziColors.COUCH_ACCENT_DK};
        }}

        /* scrollbars */
        QScrollBar:vertical {{
            background: transparent; width: 10px; margin: 4px 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {LaziColors.COUCH_BORDER}; border-radius: 4px; min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {LaziColors.COUCH_CUSHION}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """,
    "stealth": f"""
        /* base */
        QWidget, QMainWindow, QDialog {{
            background: {LaziColors.STEALTH_BG}; color: {LaziColors.STEALTH_TEXT};
            font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
            font-size: 14px;
        }}
        QLabel {{ background: transparent; }}

        /* text variants */
        QLabel[type="muted"]   {{ color: {LaziColors.STEALTH_TEXT_MUTED}; font-size: 12px; }}
        QLabel[type="med"]     {{ color: {LaziColors.STEALTH_TEXT_MED}; }}
        QLabel[type="h1"]      {{ font-size: 28px; font-weight: 700; color: {LaziColors.STEALTH_TEXT}; padding: 4px 0; }}
        QLabel[type="h2"]      {{ font-size: 22px; font-weight: 600; color: {LaziColors.STEALTH_TEXT}; padding: 2px 0; }}
        QLabel[type="h3"]      {{ font-size: 18px; font-weight: 600; color: {LaziColors.STEALTH_TEXT}; padding: 2px 0; }}
        QLabel[type="caption"] {{ font-size: 12px; color: {LaziColors.STEALTH_TEXT_MED}; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}

        /* buttons */
        QPushButton {{
            background: {LaziColors.STEALTH_ACCENT}; color: {LaziColors.STEALTH_TEXT};
            border: none; border-radius: 6px;
            padding: 8px 16px; font-weight: 600; font-size: 14px;
        }}
        QPushButton:hover  {{ background: {LaziColors.STEALTH_CUSHION}; }}
        QPushButton:pressed{{ background: {LaziColors.STEALTH_ACCENT_DK}; padding: 9px 16px 7px 16px; }}
        QPushButton:disabled{{ background: #2a2a2a; color: #666; }}
        QPushButton[variant="primary"]   {{ background: {LaziColors.STEALTH_SUCCESS}; }}
        QPushButton[variant="primary"]:hover {{ background: #8ae28a; }}
        QPushButton[variant="primary"]:pressed{{ background: #5ab25a; padding: 9px 16px 7px 16px; }}
        QPushButton[variant="danger"]    {{ background: {LaziColors.STEALTH_DANGER}; }}
        QPushButton[variant="danger"]:hover {{ background: #ff8585; }}
        QPushButton[variant="danger"]:pressed{{ background: #cc4040; padding: 9px 16px 7px 16px; }}
        QPushButton[variant="ghost"] {{
            background: transparent; color: {LaziColors.STEALTH_TEXT};
            border: 1px solid {LaziColors.STEALTH_BORDER};
        }}
        QPushButton[variant="ghost"]:hover {{
            background: {LaziColors.STEALTH_BG_RAISED};
            border-color: {LaziColors.STEALTH_BORDER_STR};
        }}
        QPushButton[variant="ghost"]:pressed {{
            background: {LaziColors.STEALTH_CUSHION};
        }}
        QPushButton:focus {{
            outline: 2px solid {LaziColors.STEALTH_ACCENT_DK};
            outline-offset: 2px;
        }}

        /* inputs */
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QListWidget {{
            background: {LaziColors.STEALTH_BG_RAISED}; color: {LaziColors.STEALTH_TEXT};
            border: 1px solid {LaziColors.STEALTH_BORDER}; border-radius: 6px; padding: 6px 8px;
            selection-background-color: {LaziColors.STEALTH_ACCENT};
        }}
        QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QComboBox:hover {{
            border-color: {LaziColors.STEALTH_BORDER_STR};
        }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border: 2px solid {LaziColors.STEALTH_ACCENT_DK}; padding: 5px 7px;
        }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QAbstractItemView {{
            background: {LaziColors.STEALTH_BG_RAISED};
            color: {LaziColors.STEALTH_TEXT};
            border: 1px solid {LaziColors.STEALTH_BORDER};
            selection-background-color: {LaziColors.STEALTH_ACCENT};
            padding: 4px;
        }}

        /* tabs */
        QTabWidget::pane {{ border: 1px solid {LaziColors.STEALTH_BORDER}; background: {LaziColors.STEALTH_BG_SUNKEN}; border-radius: 0 6px 6px 6px; }}
        QTabBar::tab {{
            background: {LaziColors.STEALTH_BG_SUNKEN}; color: {LaziColors.STEALTH_TEXT_MED};
            padding: 8px 16px; border: 1px solid transparent; margin-right: 1px;
            border-top-left-radius: 6px; border-top-right-radius: 6px;
        }}
        QTabBar::tab:selected {{
            background: {LaziColors.STEALTH_BG}; color: {LaziColors.STEALTH_TEXT}; font-weight: 600;
            border: 1px solid {LaziColors.STEALTH_BORDER}; border-bottom-color: {LaziColors.STEALTH_BG}; border-bottom-width: 0;
        }}
        QTabBar::tab:hover:!selected {{ background: {LaziColors.STEALTH_CUSHION}; }}

        /* groupbox */
        QGroupBox {{
            background: {LaziColors.STEALTH_BG_RAISED};
            border: 1px solid {LaziColors.STEALTH_BORDER}; border-radius: 8px;
            margin-top: 16px; padding: 16px 12px 12px 12px; font-weight: 600;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {LaziColors.STEALTH_TEXT}; }}

        /* status & menu */
        QStatusBar {{ background: {LaziColors.STEALTH_BG_HEADER}; color: {LaziColors.STEALTH_TEXT_MED}; }}
        QMenuBar  {{ background: {LaziColors.STEALTH_BG_HEADER}; color: {LaziColors.STEALTH_TEXT}; }}
        QMenu     {{ background: {LaziColors.STEALTH_BG_RAISED}; border: 1px solid {LaziColors.STEALTH_BORDER}; }}

        /* progress */
        QProgressBar {{
            background: {LaziColors.STEALTH_BG_RAISED}; color: {LaziColors.STEALTH_TEXT};
            border: 1px solid {LaziColors.STEALTH_BORDER}; border-radius: 4px; text-align: center;
        }}
        QProgressBar::chunk {{ background: {LaziColors.STEALTH_ACCENT}; border-radius: 3px; }}

        /* tables */
        QTableWidget, QTableView {{
            background: {LaziColors.STEALTH_BG_RAISED}; color: {LaziColors.STEALTH_TEXT};
            gridline-color: {LaziColors.STEALTH_BORDER};
            selection-background-color: {LaziColors.STEALTH_ACCENT}; selection-color: {LaziColors.STEALTH_TEXT};
            border: 1px solid {LaziColors.STEALTH_BORDER}; border-radius: 6px;
        }}
        QHeaderView::section {{
            background: {LaziColors.STEALTH_BG_SUNKEN}; color: {LaziColors.STEALTH_TEXT_MED};
            padding: 6px 8px; border: none;
            border-right: 1px solid {LaziColors.STEALTH_BORDER};
            border-bottom: 1px solid {LaziColors.STEALTH_BORDER};
            font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
        }}

        /* checkboxes */
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; border-radius: 3px;
            border: 1.5px solid {LaziColors.STEALTH_BORDER_STR}; background: {LaziColors.STEALTH_BG_RAISED};
        }}
        QCheckBox::indicator:checked {{
            background: {LaziColors.STEALTH_ACCENT}; border-color: {LaziColors.STEALTH_ACCENT_DK};
        }}

        /* sidebar + nav buttons */
        QWidget#sidebar {{
            background: {LaziColors.STEALTH_BG_SUNKEN};
            border-right: 1px solid {LaziColors.STEALTH_BORDER};
        }}
        QPushButton[nav="true"] {{
            background: transparent; color: {LaziColors.STEALTH_TEXT_MED};
            border: none; border-left: 3px solid transparent;
            text-align: left; padding: 10px 12px; font-size: 14px; font-weight: 500;
        }}
        QPushButton[nav="true"]:hover {{
            background: {LaziColors.STEALTH_BG_RAISED};
            color: {LaziColors.STEALTH_TEXT};
            border-left-color: {LaziColors.STEALTH_CUSHION};
        }}
        QPushButton[nav="true"]:pressed {{
            background: {LaziColors.STEALTH_BG_SUNKEN};
            padding: 11px 12px 9px 12px;
        }}
        QPushButton[nav="true"]:checked {{
            background: {LaziColors.STEALTH_BG};
            color: {LaziColors.STEALTH_TEXT}; font-weight: 700;
            border-left: 3px solid {LaziColors.STEALTH_ACCENT_DK};
        }}
        QPushButton[nav="true"]:checked:hover {{
            background: {LaziColors.STEALTH_BG};
            border-left-color: {LaziColors.STEALTH_ACCENT};
        }}
        QPushButton[nav="true"]:focus {{
            outline: none;
            border-left: 3px solid {LaziColors.STEALTH_ACCENT};
        }}

        /* scrollbars */
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
        QScrollBar::handle:vertical {{
            background: {LaziColors.STEALTH_BORDER_STR}; border-radius: 4px; min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {LaziColors.STEALTH_TEXT_MUTED}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """,
}


def apply_app_theme(app: QApplication, theme_name: str = "couch") -> None:
    if theme_name in THEME_QSS:
        app.setStyleSheet(THEME_QSS[theme_name])
    else:
        app.setStyleSheet(THEME_QSS["couch"])


# === Shadow helper ===

def apply_shadow(widget: QWidget, level: str = "md") -> None:
    """Apply a drop-shadow to a widget (e.g. for cards, toasts)."""
    rule = SHADOWS.get(level, SHADOWS["md"])
    if rule == "none":
        return
    shadow = QGraphicsDropShadowEffect(widget)
    # parse "0 X Y rgba(...), 0 X Y rgba(...)" into blur+offset
    # we'll just use a simple approximation: blur=20, offset=(0, 4)
    shadow.setBlurRadius(16 if level == "sm" else 24 if level == "md" else 32 if level == "lg" else 48)
    shadow.setOffset(0, 2 if level == "sm" else 4 if level == "md" else 6 if level == "lg" else 12)
    shadow.setColor(QColor(60, 30, 0, 60))
    widget.setGraphicsEffect(shadow)


# === Toast: non-blocking corner notification ===

class Toast(QWidget):
    LEVELS = {
        "info":    ("ℹ", LaziColors.COUCH_INFO,    "#cfe4ff"),
        "success": ("✓", LaziColors.COUCH_SUCCESS,  "#d4f4d4"),
        "warn":    ("!", LaziColors.COUCH_WARN,     "#f4e4b8"),
        "error":   ("✗", LaziColors.COUCH_DANGER,   "#f4c8c8"),
    }

    def __init__(self, parent: QWidget, message: str, level: str = "info",
                  duration_ms: int = 3500):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        icon, fg, bg = self.LEVELS.get(level, self.LEVELS["info"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"])
        layout.setSpacing(SPACING["sm"])
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("color: white; font-size: 18px; font-weight: 700;")
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("color: white; font-size: 13px; font-weight: 500;")
        msg_lbl.setWordWrap(True)
        msg_lbl.setMaximumWidth(360)
        layout.addWidget(icon_lbl)
        layout.addWidget(msg_lbl, stretch=1)
        self.setStyleSheet(
            f"background: {fg}; color: white; border-radius: 8px;"
        )
        apply_shadow(self, level="lg")
        self.adjustSize()
        self._position_in_parent(parent)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(300)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.start()
        QTimer.singleShot(duration_ms, self._fade_out)

    def _position_in_parent(self, parent: QWidget):
        if parent is None:
            return
        pg = parent.geometry()
        x = pg.x() + pg.width() - self.width() - SPACING["xl"]
        y = pg.y() + pg.height() - self.height() - SPACING["xl"]
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
    @staticmethod
    def show(parent: QWidget, message: str, level: str = "info",
              duration_ms: int = 3500) -> Toast:
        return Toast(parent, message, level=level, duration_ms=duration_ms)


# === Card: a rounded-rectangle container with optional title + shadow ===

class Card(QFrame):
    def __init__(self, title: str = "", parent: Optional[QWidget] = None, shadow: str = "sm"):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        # Card surface uses the raised bg + a subtle border
        # We can't fully restyle Card via QSS without selector, so set inline
        self.setStyleSheet(
            "QFrame { background: palette(base); border: 1px solid palette(midlight); border-radius: 8px; }"
        )
        apply_shadow(self, level=shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])
        if title:
            h = QLabel(title)
            h.setProperty("type", "h3")
            layout.addWidget(h)
        self.body = QVBoxLayout()
        self.body.setSpacing(SPACING["sm"])
        layout.addLayout(self.body)

    def add_widget(self, w: QWidget) -> None:
        self.body.addWidget(w)

    def add_layout(self, l) -> None:
        self.body.addLayout(l)


# === EmptyState: friendly centered state with icon + title + body + action ===

class EmptyState(QWidget):
    def __init__(self, icon: str = "📭", title: str = "Nothing here yet",
                  body: str = "", action_text: str = "",
                  on_action: Optional[Callable] = None, parent: Optional[QWidget] = None,
                  big_cta: bool = False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(SPACING["md"])
        # Big illustration (icon) — refactoring-ui: 4-5x the body text size
        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 72px; background: transparent;")
        ic.setAlignment(Qt.AlignCenter)
        layout.addWidget(ic)
        # Title — h2 weight
        ti = QLabel(title)
        ti.setProperty("type", "h2")
        ti.setAlignment(Qt.AlignCenter)
        ti.setWordWrap(True)
        ti.setMaximumWidth(480)
        layout.addWidget(ti)
        if body:
            bd = QLabel(body)
            bd.setProperty("type", "muted")
            bd.setAlignment(Qt.AlignCenter)
            bd.setWordWrap(True)
            bd.setMaximumWidth(420)
            layout.addWidget(bd)
        if action_text:
            btn = QPushButton(action_text)
            if big_cta:
                btn.setMinimumWidth(220)
                btn.setMinimumHeight(44)
                btn.setProperty("variant", "primary")
                btn.setStyleSheet("font-size: 15px; font-weight: 700;")
            else:
                btn.setMinimumWidth(180)
            if on_action:
                btn.clicked.connect(on_action)
            layout.addSpacing(SPACING["sm"])
            layout.addWidget(btn, alignment=Qt.AlignCenter)
        layout.addStretch()


# === StatusBadge: small colored pill ===

class StatusBadge(QLabel):
    def __init__(self, text: str = "", level: str = "info", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_level(level)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_level(self, level: str) -> None:
        colors = {
            "info":    (LaziColors.COUCH_INFO,    "#cfe4ff"),
            "success": (LaziColors.COUCH_SUCCESS,  "#d4f4d4"),
            "warn":    (LaziColors.COUCH_WARN,     "#f4e4b8"),
            "error":   (LaziColors.COUCH_DANGER,   "#f4c8c8"),
        }
        fg, bg = colors.get(level, colors["info"])
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; padding: 3px 10px; "
            f"border-radius: 10px; font-weight: 700; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; }}"
        )
        self._level = level

    def set_text(self, text: str, level: Optional[str] = None) -> None:
        self.setText(text)
        if level:
            self.set_level(level)


# === SectionHeader: standard section heading ===

class SectionHeader(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setProperty("type", "h2")
        self.setContentsMargins(0, SPACING["sm"], 0, SPACING["sm"])


# === StatBlock: large number + small caption (dashboards) ===

class StatBlock(QWidget):
    def __init__(self, value: str, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        layout.setSpacing(SPACING["xs"])
        v = QLabel(value)
        v.setStyleSheet("font-size: 32px; font-weight: 700; line-height: 1.1;")
        l = QLabel(label)
        l.setProperty("type", "caption")
        layout.addWidget(v)
        layout.addWidget(l)
        self.value_label = v
        self.caption_label = l

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


# === IconLabel: small icon + text pair (tightly coupled) ===

class IconLabel(QWidget):
    def __init__(self, icon: str, text: str, parent: Optional[QWidget] = None,
                  size: int = 14):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["xs"])
        ic = QLabel(icon)
        ic.setStyleSheet(f"font-size: {size}px; background: transparent;")
        tx = QLabel(text)
        tx.setStyleSheet(f"font-size: {size}px; background: transparent;")
        layout.addWidget(ic)
        layout.addWidget(tx)


# === Divider: 1px subtle separator ===

class Divider(QFrame):
    def __init__(self, vertical: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine if vertical else QFrame.HLine)
        self.setStyleSheet("color: palette(midlight);")


# === Toolbar: a horizontal bar with optional title ===

class Toolbar(QWidget):
    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("toolbar", "true")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING["lg"], SPACING["sm"], SPACING["lg"], SPACING["sm"])
        layout.setSpacing(SPACING["md"])
        if title:
            t = QLabel(title)
            t.setProperty("type", "h3")
            layout.addWidget(t)
        self.left = layout
        self.right_layout = QHBoxLayout()
        self.right_layout.setSpacing(SPACING["sm"])
        layout.addLayout(self.right_layout, stretch=1)
        # apply a subtle background
        self.setStyleSheet("QWidget { background: palette(window); border-bottom: 1px solid palette(midlight); }")

    def add_left(self, w: QWidget) -> None:
        self.left.addWidget(w)

    def add_right(self, w: QWidget) -> None:
        self.right_layout.addWidget(w)
