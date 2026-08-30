"""
Lazi-Bot — the playful, slightly overweight mascot of linkedin-autopilot.

(Inspired by IBM Bob. We renamed him, removed the hard hat, gave him a little
extra weight, and made him dirty-looking. He lives in the corner of the GUI
as a chat overlay.)

Features:
  - ChatOverlay: floating circular widget in the bottom-right of any window
  - talks to the active LLM (Poolside/OpenAI/Google) using the persona config
  - can set parameters, change resume, and apply changes
  - "The Couch" onboarding: first-run welcome that walks through profile setup
  - Couch (Command Center): the page where you set up job + profile info
  - PasswordVault UI: encrypted local store for site logins (keyring + Fernet)
  - EmbeddedBrowser (Qt WebEngine) in Couch for in-app browsing — visible or headless

The bot has opinions, makes food metaphors, and calls the user "chief".
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QSize, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QDialog, QListWidget, QListWidgetItem, QFrame, QSizePolicy, QComboBox,
    QTabWidget, QFormLayout, QMessageBox, QInputDialog
)

logger = logging.getLogger(__name__)


# --- ASCII art for the dirty little mascot (drawn in the overlay) ---
LAZI_ART_LINES = [
    "   ____   ",
    "  /    \\  ",
    " | o  o | ",   # bloodshot eyes
    " |  __  | ",   # double chin
    "  \\____/  ",
    "  /||||\\  ",   # stained shirt
]


# === The LLM bridge ===

class LaziBrain(QObject):
    """
    Talks to the user's chosen LLM provider using a tiny HTTP call.
    Lazy-imports openai so the GUI can load without it.
    """
    reply = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.provider = "poolside"
        self.api_key  = None
        self.history: List[Dict[str, str]] = []

    def configure(self, provider: str, api_key: Optional[str]):
        self.provider = provider
        self.api_key = api_key

    def ask(self, user_msg: str, system_prompt: str = "") -> None:
        """
        Async-ish: append to history, then call LLM in background. For now
        we use a simple Timer to keep the GUI responsive; if the openai
        import fails, we fall back to canned replies.
        """
        self.history.append({"role": "user", "content": user_msg})
        QTimer.singleShot(0, lambda: self._call_llm(system_prompt))

    def _call_llm(self, system_prompt: str):
        try:
            import openai  # noqa
        except ImportError:
            self._canned_reply(user_msg=self.history[-1]["content"])
            return

        try:
            base_urls = {
                "poolside": "https://inference.poolside.ai/v1",
                "openai":   "https://api.openai.com/v1",
            }
            base = base_urls.get(self.provider, "https://api.openai.com/v1")
            client = openai.OpenAI(api_key=self.api_key or "no-key", base_url=base)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.extend(self.history[-20:])  # cap context
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=400,
            )
            text = resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            self._canned_reply(user_msg=self.history[-1]["content"])
            return

        self.history.append({"role": "assistant", "content": text})
        self.reply.emit(text)

    def _canned_reply(self, user_msg: str):
        """Playful canned replies when no LLM is available."""
        lower = user_msg.lower()
        if any(t in lower for t in ["hello", "hi ", "hey", "yo"]):
            text = "Ayy chief, what we cookin' up today? I got my couch, you got the job search — let's go."
        elif "salary" in lower:
            text = "Money moves, I see. Tell me your floor and ceiling and I'll lock it in. Don't lowball yourself, chief."
        elif "title" in lower or "titles" in lower:
            text = "Job titles — toss 'em at me. The more specific the better, LinkedIn's search is title-weighted."
        elif "blacklist" in lower or "block" in lower:
            text = "Blacklist? Just name 'em. I'll make sure we never even look at those greasy companies."
        elif "resume" in lower:
            text = "Resume upload? Point me at the file. I'll parse it and fill out every form like I was born for it."
        elif "thanks" in lower or "thank you" in lower:
            text = "Anytime, chief. Now let's get you a job before I finish this bag of chips."
        elif "?" in lower:
            text = "Hmm, good question. I'm gonna have to chew on that one. Try the Couch (Command Center) — every answer's in there."
        else:
            text = "I hear ya. Open up the Couch on the left side and tweak your settings — I'll make it stick."
        self.history.append({"role": "assistant", "content": text})
        self.reply.emit(text)


# === The mascot chat overlay ===

class LaziChatOverlay(QWidget):
    """
    Floating circular widget in the corner. Click to expand into a chat
    panel. Always on top of the parent but doesn't steal focus.
    """
    command = Signal(str, dict)  # emitted when Lazi wants to set a parameter

    SYSTEM_PROMPT = (
        "You are Lazi-Bot, a playful, slightly overweight mascot bot. "
        "You help the user set up their job-search profile and parameters. "
        "Be friendly, use food/couch metaphors occasionally, and address the "
        "user as 'chief'. Keep replies under 80 words. If the user asks to "
        "set a parameter, extract it and respond with a clear 'I'll set X to Y'."
    )

    def __init__(self, parent: Optional[QWidget] = None, brain: Optional[LaziBrain] = None):
        super().__init__(parent)
        self.brain = brain or LaziBrain(self)
        self.brain.reply.connect(self._on_reply)
        self.expanded = False
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._collapsed_size = QSize(72, 72)
        self._expanded_size  = QSize(360, 480)
        self.setFixedSize(self._collapsed_size)
        self._build_ui()
        self._collapsed = True

    def _build_ui(self):
        # collapsed: just paint the mascot
        # expanded: chat list + entry
        self._chat_list = QTextEdit(self)
        self._chat_list.setReadOnly(True)
        self._chat_list.setStyleSheet(
            "QTextEdit { background: #fff8e7; border: 2px solid #b48a3a; border-radius: 8px; "
            "color: #333; font-family: 'Comic Sans MS', sans-serif; font-size: 12px; }"
        )
        self._chat_list.hide()

        self._entry = QLineEdit(self)
        self._entry.setPlaceholderText("Say something to Lazi…")
        self._entry.returnPressed.connect(self._send)
        self._entry.setStyleSheet(
            "QLineEdit { background: white; border: 1px solid #b48a3a; border-radius: 4px; padding: 4px; }"
        )
        self._entry.hide()

        # initial greeting
        self._append("Lazi", "Ayy chief, welcome to the Couch. I'm Lazi — slightly overweight, slightly dirty, but I get the job done. Click me again if you want me to shut up.")

    # --- painting the dirty mascot ---

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        # background: stained couch cushion
        p.setBrush(QBrush(QColor("#c9a96e")))
        p.setPen(QPen(QColor("#7a5a2a"), 2))
        p.drawEllipse(rect.adjusted(2, 2, -2, -2))
        # dirty spots
        for x, y, r in [(20, 50, 4), (50, 18, 3), (40, 45, 2), (58, 55, 3)]:
            p.setBrush(QBrush(QColor("#6b4a1a")))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(x, y), r, r)
        # text "LAZI"
        p.setPen(QColor("#3a2410"))
        font = QFont("Comic Sans MS", 14, QFont.Bold)
        p.setFont(font)
        p.drawText(rect, Qt.AlignCenter, "LAZI")

    # --- expand/collapse on click ---

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle()

    def _toggle(self):
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    def _expand(self):
        self._collapsed = False
        self.setFixedSize(self._expanded_size)
        self._chat_list.setGeometry(8, 8, self.width() - 16, self.height() - 56)
        self._entry.setGeometry(8, self.height() - 40, self.width() - 16, 28)
        self._chat_list.show()
        self._entry.show()
        self.raise_()

    def _collapse(self):
        self._collapsed = True
        self._chat_list.hide()
        self._entry.hide()
        self.setFixedSize(self._collapsed_size)

    # --- chat ---

    def _send(self):
        text = self._entry.text().strip()
        if not text:
            return
        self._append("You", text)
        self._entry.clear()
        self.brain.ask(text, self.SYSTEM_PROMPT)

    def _on_reply(self, text: str):
        self._append("Lazi", text)
        # detect "I'll set X to Y" commands
        import re
        m = re.search(r"I'll set (\w+) to ([\w\d$,\.\- ]+)", text, re.IGNORECASE)
        if m:
            self.command.emit(m.group(1), {"value": m.group(2).strip()})

    def _append(self, who: str, text: str):
        who_color = "#3a2410" if who == "Lazi" else "#1a4d8a"
        self._chat_list.append(
            f'<div style="color:{who_color}; font-weight:bold">{who}:</div>'
            f'<div style="margin: 2px 0 8px 0">{text}</div>'
        )


# === The Couch (Command Center) — tabbed: Welcome / Browser / Passwords ===

class TheCouch(QWidget):
    """
    The Couch is the Command Center of the app. Tabs:
      - Welcome: onboarding message + walkthrough
      - Browser: embedded Qt WebEngine browser (visible or headless)
      - Passwords: encrypted vault for site logins (LinkedIn, GitHub, etc.)
    """
    ready = Signal()  # emitted when user clicks "Set up the Couch" on the Welcome tab

    WELCOME = (
        "Welcome to the Couch, chief.\n\n"
        "I'm Lazi — your slightly overweight, slightly dirty, very useful assistant.\n"
        "This here is the Command Center. You set up:\n"
        "  • A persona (your job-search identity — pick '+ New persona' on the left)\n"
        "  • Who you are (name, email, phone)\n"
        "  • What you want (titles, salary range, experience years)\n"
        "  • Who to avoid (blacklist)\n"
        "  • Your resume (drop a .docx / .pdf / .txt and I'll fill in the rest)\n"
        "  • Where you go (browser tab — log into LinkedIn, Indeed, etc.)\n"
        "  • Your passwords (encrypted local vault, never leaves this machine)\n\n"
        "When you're done, I'll go apply to jobs while you nap on the couch."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #fff8e7;")
        outer = QVBoxLayout(self)

        # Header
        header = QLabel("THE COUCH — Command Center")
        header.setStyleSheet("font-size: 22px; font-weight: bold; color: #7a5a2a; padding: 8px;")
        header.setAlignment(Qt.AlignCenter)
        outer.addWidget(header)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabBar::tab { padding: 8px 16px; font-size: 13px; }"
            "QTabBar::tab:selected { background: #b48a3a; color: white; }"
        )
        outer.addWidget(self.tabs, stretch=1)

        # Tab 1: Welcome
        self.tabs.addTab(self._build_welcome_tab(), "☕  Welcome")

        # Tab 2: Browser
        from .browser_widget import BrowserWidget
        self.browser = BrowserWidget()
        self.tabs.addTab(self.browser, "🌐  Browser")

        # Tab 3: Passwords
        self.passwords = PasswordVaultWidget()
        self.tabs.addTab(self.passwords, "🔒  Passwords")

    def _build_welcome_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Welcome
        self.welcome = QLabel(self.WELCOME)
        self.welcome.setWordWrap(True)
        self.welcome.setStyleSheet("font-size: 14px; padding: 16px; background: #f0e2c0; border-radius: 8px;")
        layout.addWidget(self.welcome)

        # Walkthrough steps
        steps_frame = QFrame()
        steps_frame.setStyleSheet("background: #f5e7c0; border-radius: 8px; padding: 12px;")
        sl = QVBoxLayout(steps_frame)
        sl.addWidget(QLabel("Setup walkthrough:"))
        for s in [
            "1. Pick a persona (or create one)",
            "2. Upload a resume (TXT / DOCX / PDF)",
            "3. Set salary range, experience years, titles",
            "4. Add companies / titles to blacklist",
            "5. Add site logins in the Passwords tab (LinkedIn, etc.)",
            "6. Use the Browser tab to log into those sites — Lazi remembers",
            "7. Pick an LLM provider (Poolside, OpenAI, None)",
            "8. Hit Start and let Lazi do the work",
        ]:
            sl.addWidget(QLabel(s))
        layout.addWidget(steps_frame)

        # Persona dropdown — no hardcoded personas; the user creates them.
        from .profile_store import list_personas
        self.persona_combo = QComboBox()
        personas = list_personas()
        if not personas:
            self.persona_combo.addItem("(no personas yet — create one in the picker)")
        else:
            self.persona_combo.addItems(personas)
        layout.addWidget(QLabel("Active persona:"))
        layout.addWidget(self.persona_combo)
        self._persona_hint = QLabel(
            "Create a persona on the left (click '+ New persona'). "
            "Then come back here, select it, and start setting parameters."
        )
        self._persona_hint.setWordWrap(True)
        self._persona_hint.setStyleSheet("color: #666; padding: 4px; font-style: italic;")
        layout.addWidget(self._persona_hint)

        cta = QPushButton("☕ Set up the Couch")
        cta.setStyleSheet("background: #b48a3a; color: white; font-size: 16px; padding: 10px; border-radius: 6px;")
        cta.clicked.connect(self.ready.emit)
        layout.addWidget(cta)

        layout.addStretch()
        return w


# === Password Vault Widget ===

class PasswordVaultWidget(QWidget):
    """
    UI for the encrypted password vault (app/password_store.py).
    Lets the user add, edit, delete, and reveal site logins.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from .password_store import list_sites, get_entry, store_entry, delete_entry
        self._list_sites = list_sites
        self._get_entry = get_entry
        self._store = store_entry
        self._delete = delete_entry

        layout = QVBoxLayout(self)

        info = QLabel(
            "Vault is encrypted with Fernet (AES-128 + HMAC). The master key is "
            "stored in the OS credential manager (Windows Credential Manager / macOS "
            "Keychain / Linux Secret Service). The vault file cannot be read on "
            "another machine or by another user."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; padding: 8px;")
        layout.addWidget(info)

        # Two-column layout: list on left, form on right
        body = QHBoxLayout()
        layout.addLayout(body, stretch=1)

        # Left: site list
        left = QVBoxLayout()
        self.site_list = QListWidget()
        self.site_list.itemSelectionChanged.connect(self._on_select)
        left.addWidget(QLabel("Stored sites:"))
        left.addWidget(self.site_list, stretch=1)

        list_buttons = QHBoxLayout()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self._refresh)
        del_btn = QPushButton("🗑 Delete")
        del_btn.clicked.connect(self._on_delete)
        list_buttons.addWidget(refresh_btn)
        list_buttons.addWidget(del_btn)
        left.addLayout(list_buttons)
        body.addLayout(left, stretch=1)

        # Right: form
        right = QFormLayout()
        self.site_edit   = QLineEdit()
        self.url_edit    = QLineEdit()
        self.user_edit   = QLineEdit()
        self.pass_edit   = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.notes_edit  = QLineEdit()

        right.addRow("Site:",     self.site_edit)
        right.addRow("URL:",      self.url_edit)
        right.addRow("Username:", self.user_edit)
        right.addRow("Password:", self.pass_edit)

        show_row = QHBoxLayout()
        show_btn = QPushButton("👁 Show")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(self._toggle_visibility)
        show_row.addWidget(show_btn)
        show_row.addStretch()
        right.addRow("", self._wrap(show_row))

        right.addRow("Notes:",    self.notes_edit)

        save_btn = QPushButton("💾 Save / Add")
        save_btn.setStyleSheet("background: #4a7a2a; color: white; padding: 8px; border-radius: 4px;")
        save_btn.clicked.connect(self._on_save)
        right.addRow("", save_btn)

        body.addLayout(right, stretch=2)
        self._refresh()

    def _wrap(self, layout):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        w.setLayout(layout)
        return w

    def _refresh(self):
        self.site_list.clear()
        for s in self._list_sites():
            self.site_list.addItem(QListWidgetItem(s))

    def _on_select(self):
        items = self.site_list.selectedItems()
        if not items:
            return
        site = items[0].text()
        entry = self._get_entry(site)
        if not entry:
            return
        self.site_edit.setText(entry.site)
        self.url_edit.setText(entry.url)
        self.user_edit.setText(entry.username)
        self.pass_edit.setText(entry.password)
        self.notes_edit.setText(entry.notes)

    def _on_save(self):
        site = self.site_edit.text().strip()
        if not site:
            QMessageBox.warning(self, "Passwords", "Site name is required.")
            return
        self._store(
            site=site,
            username=self.user_edit.text(),
            password=self.pass_edit.text(),
            url=self.url_edit.text(),
            notes=self.notes_edit.text(),
        )
        QMessageBox.information(self, "Passwords", f"Saved entry for '{site}'.")
        self._refresh()

    def _on_delete(self):
        items = self.site_list.selectedItems()
        if not items:
            return
        site = items[0].text()
        if QMessageBox.question(self, "Delete", f"Delete entry for '{site}'?") == QMessageBox.Yes:
            self._delete(site)
            self._refresh()

    def _toggle_visibility(self, checked: bool):
        self.pass_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)


# === Legacy EmbeddedBrowser stub (kept for back-compat imports) ===

class EmbeddedBrowser(QWidget):
    """Back-compat shim — real browser now lives in app.browser_widget.BrowserWidget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from .browser_widget import BrowserWidget
        layout = QVBoxLayout(self)
        layout.addWidget(BrowserWidget())
