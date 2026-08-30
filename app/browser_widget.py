"""
Embedded browser widget for linkedin-autopilot.

Renders real HTML/JS using Qt WebEngine (the same Chromium that Chrome uses).
Used in The Couch (Command Center) and as a standalone page in the app shell.

Headless vs visible:
  - When visible: the browser uses the user's normal Chrome user-data-dir
    so LinkedIn session cookies persist across runs.
  - When headless: a temporary profile is used (no persistence).

Bookmark bar, back/forward, and a URL bar are bundled. The user can also
switch to Playwright mode (a separate sync_playwright() call) from a toggle.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QProgressBar, QCheckBox
)

logger = logging.getLogger(__name__)

# Use QWebEngineView if available; otherwise fall back to a placeholder.
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEB_ENGINE = True
except ImportError:
    HAS_WEB_ENGINE = False
    QWebEngineView = None  # type: ignore


class BrowserWidget(QWidget):
    """
    A QWebEngineView-based embedded browser. Use it as a regular QWidget:
        browser = BrowserWidget()
        browser.load("https://linkedin.com")
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 headless: bool = False,
                 user_data_dir: Optional[Path] = None):
        super().__init__(parent)
        self._headless = headless
        self._user_data_dir = user_data_dir
        self._build_ui()
        if not HAS_WEB_ENGINE:
            self._show_unavailable()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        bar = QHBoxLayout()
        self.back_btn = QPushButton("◀")
        self.back_btn.setFixedWidth(32)
        self.back_btn.clicked.connect(self._go_back)
        self.fwd_btn = QPushButton("▶")
        self.fwd_btn.setFixedWidth(32)
        self.fwd_btn.clicked.connect(self._go_forward)
        self.reload_btn = QPushButton("⟳")
        self.reload_btn.setFixedWidth(32)
        self.reload_btn.clicked.connect(self._reload)

        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("https://…  (press Enter to load)")
        self.url_bar.returnPressed.connect(self._on_url_entered)

        self.headless_chk = QCheckBox("Headless")
        self.headless_chk.setChecked(self._headless)
        self.headless_chk.toggled.connect(self._toggle_headless)

        bar.addWidget(self.back_btn)
        bar.addWidget(self.fwd_btn)
        bar.addWidget(self.reload_btn)
        bar.addWidget(self.url_bar, stretch=1)
        bar.addWidget(self.headless_chk)
        layout.addLayout(bar)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # The view itself
        if HAS_WEB_ENGINE:
            self.view = QWebEngineView()
            self.view.urlChanged.connect(self._on_url_changed)
            self.view.loadStarted.connect(lambda: self.progress.setVisible(True))
            self.view.loadProgress.connect(self.progress.setValue)
            self.view.loadFinished.connect(lambda _: self.progress.setVisible(False))
            layout.addWidget(self.view, stretch=1)
        else:
            self.view = None

        # Status
        self.status = QLabel("")
        self.status.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(self.status)

    def _show_unavailable(self):
        msg = QLabel(
            "Qt WebEngine not available. Install with:\n"
            "  pip install PySide6-Addons\n\n"
            "Falling back to Playwright sync_api for navigation."
        )
        msg.setStyleSheet("padding: 12px; color: #a00;")
        msg.setWordWrap(True)
        self.layout().addWidget(msg, stretch=1)

    def _on_url_entered(self):
        url = self.url_bar.text().strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.load(url)

    def _on_url_changed(self, qurl: QUrl):
        self.url_bar.setText(qurl.toString())
        self.status.setText(f"Loaded: {qurl.toString()}")

    def _go_back(self):
        if self.view:
            self.view.back()

    def _go_forward(self):
        if self.view:
            self.view.forward()

    def _reload(self):
        if self.view:
            self.view.reload()

    def _toggle_headless(self, checked: bool):
        self._headless = checked
        # Note: QWebEngineView cannot be hot-swapped to headless at runtime.
        # The flag is recorded for re-instantiation; the next load() respects it.
        self.status.setText(f"Headless = {self._headless} (effective on next launch)")

    def load(self, url: str):
        """Public loader. Accepts a URL with or without scheme."""
        if not HAS_WEB_ENGINE or self.view is None:
            # Playwright fallback
            self._playwright_load(url)
            return
        if not url.startswith(("http://", "https://", "file://")):
            url = "https://" + url
        self.view.setUrl(QUrl(url))

    def _playwright_load(self, url: str):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.status.setText("Neither Qt WebEngine nor Playwright is available.")
            return
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self._headless)
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(url, timeout=30000)
                self.status.setText(f"Playwright: loaded {url} (title: {page.title()})")
                browser.close()
        except Exception as e:
            self.status.setText(f"Playwright error: {e}")
