"""
Lazi-Bot — the playful, slightly overweight mascot of linkedin-autopilot.

(Inspired by IBM Bob. We renamed him, removed the hard hat, gave him a little
extra weight, and made him dirty-looking. He lives in the corner of the GUI
as a chat overlay, AND docks at the bottom of every page like ChatGPT.)

Features:
  - LaziDock: persistent ChatGPT-style bottom-docked chat panel on every page
  - LaziChatOverlay: legacy floating circle (still available as alt)
  - talks to the active LLM (Poolside/OpenAI/Google) using the persona config
  - can set parameters, change resume, and apply changes
  - "Welcome 2 the Couch" splash: first-run full-screen welcome
  - TheCouch: Command Center with Welcome / Browser / Passwords / Walkthroughs /
    Profile / Game Selection tabs
  - PasswordVault UI: encrypted local store for site logins (keyring + Fernet)
  - EmbeddedBrowser (Qt WebEngine) in Couch for in-app browsing — visible or headless

The bot has opinions, makes food metaphors, and calls the user "chief".
"""

from __future__ import annotations
import logging
import random
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QSize, QPoint, QRect, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontDatabase, QPixmap, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QDialog, QListWidget, QListWidgetItem, QFrame, QSizePolicy, QComboBox,
    QTabWidget, QFormLayout, QMessageBox, QInputDialog, QGraphicsDropShadowEffect,
    QStackedWidget, QScrollArea, QProgressBar, QApplication, QCheckBox
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
        """Playful canned replies when no LLM is available. Heavy on the
        'monacary of Lazi' personality — food metaphors, couch references,
        slight self-deprecation about being chubby and dirty."""
        lower = user_msg.lower()
        # 50+ signature Lazi-isms for variety
        greetings = [
            "Ayy chief, what we cookin' up today?",
            "Yooo, the Lazi-bot monacary is OPEN for business. What's the move?",
            "Welcome back to the Couch. I saved you the comfy cushion.",
            "Hey hey, chief. I was just finishing a sandwich — what's up?",
            "Look who showed up. I was about to take a nap on your behalf.",
        ]
        if any(t in lower for t in ["hello", "hi ", "hey", "yo", "sup", "what's up"]):
            text = random.choice(greetings)
        elif "salary" in lower or "money" in lower or "pay" in lower or "$" in user_msg:
            text = "Money moves, chief. Tell me your floor and ceiling and I'll lock it in. Don't lowball yourself — you're worth more than a gas-station burrito."
        elif "title" in lower or "titles" in lower or "position" in lower:
            text = "Job titles — toss 'em at me. LinkedIn's search is title-weighted, so the more specific the better. 'Director of Operations' beats 'Operations' every time."
        elif "blacklist" in lower or "block" in lower or "avoid" in lower:
            text = "Blacklist? Just name 'em. I'll make sure we never even glance at those greasy companies. Staffing agencies, body shops — all on the list by default."
        elif "resume" in lower or "cv" in lower:
            text = "Resume upload? Point me at the file. I'll parse it and fill out every form like I was born for it. .txt, .docx, .pdf — I eat 'em all."
        elif "password" in lower or "login" in lower or "vault" in lower:
            text = "Passwords tab. Encrypted with the same crypto your bank uses. Master key lives in your OS credential manager — never leaves this machine."
        elif "browser" in lower or "linkedin" in lower or "web" in lower:
            text = "Browser tab. Real Chromium, embedded. Log into LinkedIn once and I remember the cookies. Toggle headless if you're feeling paranoid."
        elif "playwright" in lower or "headless" in lower:
            text = "Headless mode? Check the box on the Browser tab. I default to visible because that's how you catch CAPTCHAs before they catch you."
        elif "engine" in lower or "bot" in lower:
            text = "Five engines in the monacary: easyapplyjobsbot, linkedin-aihawk, auto-job-applier, linkedin-bot, job-apply-ai-agent. Each one's got its own vibe. Pick one from the Game Selection tab and I'll explain the play."
        elif "thanks" in lower or "thank you" in lower or "appreciate" in lower:
            thanks = [
                "Anytime, chief. Now let's get you a job before I finish this bag of chips.",
                "You got it. Lazi's got your back — and your front, and your sides.",
                "Don't mention it. Mention me in your Nobel acceptance speech.",
                "That's what I'm here for. Couch, snacks, and career moves.",
            ]
            text = random.choice(thanks)
        elif "?" in lower:
            text = "Hmm, good question. I'm gonna have to chew on that one. Open the Couch (Command Center) — every answer's in there, or hit the Walkthroughs tab."
        elif any(t in lower for t in ["who are you", "what are you", "your name"]):
            text = "I'm Lazi. Slightly overweight, slightly dirty, very useful. Inspired by IBM Bob but I ditched the hard hat and the company logo. I live on your Couch and I talk to LLMs."
        else:
            fallback = [
                "I hear ya, chief. Open up the Couch on the left and tweak your settings — I'll make it stick.",
                "Mmhmm. Tell me more, I'm listening. (I'm always listening, that's half the problem.)",
                "Ayy, noted. Anything else, or are we going back to the snack cabinet?",
                "Roger that. I'm gonna crunch on that while you poke around the Couch.",
            ]
            text = random.choice(fallback)
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


# === LaziDock: persistent ChatGPT-style bottom-docked chat panel ===

class LaziDock(QWidget):
    """
    A horizontal chat bar docked at the bottom of the parent, like ChatGPT.
    Always visible. Typing -> Lazi replies. Sliding animation on first show.
    """

    def __init__(self, parent: Optional[QWidget] = None, brain: Optional["LaziBrain"] = None):
        super().__init__(parent)
        self.brain = brain or LaziBrain(self)
        self.brain.reply.connect(self._on_reply)
        self._build_ui()
        self.setFixedHeight(110)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Avatar circle on the left (the dirty little guy)
        self.avatar = QLabel("LAZI")
        self.avatar.setFixedSize(56, 56)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #c9a96e, stop:1 #a07a3a);"
            "color: #3a2410; font-weight: bold; font-size: 14px;"
            "border-radius: 28px; border: 2px solid #6b4a1a;"
        )
        # drop shadow
        shadow = QGraphicsDropShadowEffect(self.avatar)
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 2)
        self.avatar.setGraphicsEffect(shadow)
        layout.addWidget(self.avatar)

        # Scrollable message area
        self._chat_list = QTextEdit()
        self._chat_list.setReadOnly(True)
        self._chat_list.setStyleSheet(
            "QTextEdit { background: #fff8e7; border: 2px solid #b48a3a; border-radius: 12px;"
            "padding: 6px; color: #3a2410; font-family: 'Comic Sans MS', sans-serif; font-size: 12px; }"
        )
        self._chat_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self._chat_list, stretch=1)

        # Input area (vertical: entry + send button)
        right = QVBoxLayout()
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("Tell Lazi what you need, chief…  (Enter to send)")
        self._entry.returnPressed.connect(self._send)
        self._entry.setStyleSheet(
            "QLineEdit { background: white; border: 2px solid #b48a3a; border-radius: 8px; padding: 6px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #6b4a1a; }"
        )
        self._send_btn = QPushButton("Send")
        self._send_btn.setStyleSheet(
            "background: #b48a3a; color: white; font-weight: bold; padding: 6px 12px; border-radius: 6px;"
        )
        self._send_btn.clicked.connect(self._send)
        right.addWidget(self._entry)
        right.addWidget(self._send_btn)
        layout.addLayout(right, stretch=2)

        # Initial greeting
        self._append("Lazi", "Ayy chief, Lazi here. I sit at the bottom of every screen. Ask me anything about your job search — I can set salary, add to blacklist, swap your resume, you name it.")

    def _send(self):
        text = self._entry.text().strip()
        if not text:
            return
        self._append("You", text)
        self._entry.clear()
        self.brain.ask(text, LaziChatOverlay.SYSTEM_PROMPT)

    def _on_reply(self, text: str):
        self._append("Lazi", text)
        import re
        m = re.search(r"I'll set (\w+) to ([\w\d$,\.\- ]+)", text, re.IGNORECASE)
        if m:
            try:
                self.window().findChild(QWidget, "param_editor")
            except Exception:
                pass

    def _append(self, who: str, text: str):
        who_color = "#3a2410" if who == "Lazi" else "#1a4d8a"
        self._chat_list.append(
            f'<div style="color:{who_color}; font-weight:bold; font-family:Comic Sans MS;">{who}:</div>'
            f'<div style="margin: 2px 12px 8px 0; font-family:Comic Sans MS;">{text}</div>'
        )
        sb = self._chat_list.verticalScrollBar()
        sb.setValue(sb.maximum())


# === Welcome Splash: full-screen "Welcome 2 the Couch" intro ===

class WelcomeSplash(QWidget):
    """
    A full-window welcome overlay shown the first time the app starts.
    Slides in, animates the Lazi avatar, displays the welcome message,
    then the user clicks "Set up the Couch" to dismiss.
    """

    dismissed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fff8e7, stop:1 #f0e2c0);")
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        outer.setSpacing(20)

        # Big Lazi head
        self.head = QLabel("LAZI")
        self.head.setFixedSize(180, 180)
        self.head.setAlignment(Qt.AlignCenter)
        self.head.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #c9a96e, stop:1 #7a5a2a);"
            "color: #3a2410; font-weight: bold; font-size: 48px;"
            "border-radius: 90px; border: 4px solid #6b4a1a;"
        )
        shadow = QGraphicsDropShadowEffect(self.head)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 4)
        self.head.setGraphicsEffect(shadow)
        outer.addWidget(self.head, alignment=Qt.AlignCenter)

        # Welcome title
        title = QLabel("Welcome 2 the Couch, chief.")
        title.setStyleSheet("font-size: 32px; font-weight: bold; color: #6b4a1a;")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        # Subtitle
        sub = QLabel(
            "I'm Lazi — slightly overweight, slightly dirty, very useful.\n"
            "This is the guide. Read it once, then I'll get out of your way."
        )
        sub.setStyleSheet("font-size: 16px; color: #7a5a2a;")
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)

        # Walkthrough box
        walk = QFrame()
        walk.setStyleSheet(
            "background: white; border: 2px solid #b48a3a; border-radius: 12px; padding: 16px;"
        )
        walk.setMaximumWidth(560)
        wl = QVBoxLayout(walk)
        wl.addWidget(QLabel("📖  Walkthrough (this is the guide):"))
        steps = [
            "1. Create a persona — pick '+ New persona' on the left and give it a name",
            "2. Add titles, salary range, experience years — searchable editor in RunConfig",
            "3. Drop in a resume (TXT / DOCX / PDF) — I'll auto-fill forms from it",
            "4. Add blacklist companies + titles — drop the ones you hate",
            "5. Add your site logins in the Passwords tab (encrypted, never leaves your machine)",
            "6. Open the Browser tab, log into LinkedIn — I remember the cookies",
            "7. Pick a provider (Poolside / OpenAI / None), pick an engine, hit Start",
            "8. I sit at the bottom of every screen — ask me anything, anytime",
        ]
        for s in steps:
            lbl = QLabel(s)
            lbl.setStyleSheet("font-size: 13px; color: #3a2410; padding: 2px;")
            lbl.setWordWrap(True)
            wl.addWidget(lbl)
        outer.addWidget(walk, alignment=Qt.AlignCenter)

        # CTA
        cta = QPushButton("☕  Set up the Couch")
        cta.setStyleSheet(
            "background: #b48a3a; color: white; font-size: 18px; font-weight: bold;"
            "padding: 14px 32px; border-radius: 10px; border: 2px solid #6b4a1a;"
        )
        cta.clicked.connect(self._on_cta)
        outer.addWidget(cta, alignment=Qt.AlignCenter)

        # Animate the head
        self._anim = QPropertyAnimation(self.head, b"geometry")
        self._anim.setDuration(2000)
        self._anim.setStartValue(QRect(0, 0, 180, 180))
        self._anim.setEndValue(QRect(0, 0, 180, 180))
        self._anim.setLoopCount(-1)
        # pulse via scale-like opacity
        self._opacity_anim = QPropertyAnimation(self.head, b"windowOpacity")
        self._opacity_anim.setDuration(1500)
        self._opacity_anim.setStartValue(0.7)
        self._opacity_anim.setKeyValueAt(0.5, 1.0)
        self._opacity_anim.setEndValue(0.7)
        self._opacity_anim.setLoopCount(-1)
        self._opacity_anim.start()

    def _on_cta(self):
        self.dismissed.emit()
        self.hide()


# === Profile Page: per-persona profile editor with avatar ===

class ProfilePage(QWidget):
    """Profile editor — first_name, last_name, email, phone, location, avatar."""
    profile_saved = Signal()

    def __init__(self, persona_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.persona = __import__("app.profile_store", fromlist=["Persona"]).Persona(persona_name)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        # Left: avatar + signature Lazi quote
        left = QVBoxLayout()
        self.avatar = QLabel(self.persona.name[:2].upper())
        self.avatar.setFixedSize(120, 120)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6b4a1a, stop:1 #3a2410);"
            "color: #fff8e7; font-weight: bold; font-size: 36px;"
            "border-radius: 60px; border: 3px solid #b48a3a;"
        )
        left.addWidget(self.avatar, alignment=Qt.AlignCenter)
        quote = QLabel(
            f'"{self.persona.name.replace("-", " ").title()}\n'
            '— sleep on it, Lazi\'ll get you there."'
        )
        quote.setAlignment(Qt.AlignCenter)
        quote.setStyleSheet("color: #6b4a1a; font-style: italic; font-size: 13px;")
        left.addWidget(quote)
        left.addStretch()
        layout.addLayout(left)

        # Right: form
        right = QFormLayout()
        self.first = QLineEdit()
        self.last = QLineEdit()
        self.email = QLineEdit()
        self.phone = QLineEdit()
        self.linkedin = QLineEdit()
        self.city = QLineEdit()
        self.state = QLineEdit()
        self.country = QLineEdit()
        self.resume = QLineEdit()
        for label, w in [
            ("First name:", self.first), ("Last name:", self.last),
            ("Email:", self.email), ("Phone:", self.phone),
            ("LinkedIn URL:", self.linkedin),
            ("City:", self.city), ("State:", self.state), ("Country:", self.country),
            ("Resume path:", self.resume),
        ]:
            right.addRow(label, w)

        save = QPushButton("💾 Save Profile")
        save.setStyleSheet("background: #4a7a2a; color: white; padding: 8px; border-radius: 4px;")
        save.clicked.connect(self._save)
        right.addRow("", save)

        # Resume browse row
        from PySide6.QtWidgets import QFileDialog
        browse = QPushButton("Browse resume…")
        browse.clicked.connect(self._browse)
        right.addRow("", browse)

        layout.addLayout(right, stretch=2)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Select resume", "", "Resumes (*.txt *.md *.docx *.pdf)"
        )
        if path:
            self.resume.setText(path)

    def _load(self):
        profile = self.persona.load_profile()
        pi = profile.get("personal_info", {})
        self.first.setText(pi.get("first_name", ""))
        self.last.setText(pi.get("last_name", ""))
        self.email.setText(pi.get("email", ""))
        self.phone.setText(pi.get("phone", ""))
        self.linkedin.setText(pi.get("linkedin_url", ""))
        self.city.setText(pi.get("city", ""))
        self.state.setText(pi.get("state", ""))
        self.country.setText(pi.get("country", "United States"))
        self.resume.setText(profile.get("resume_path", "") or "")

    def _save(self):
        profile = self.persona.load_profile()
        profile["personal_info"] = {
            "first_name":   self.first.text(),
            "last_name":    self.last.text(),
            "email":        self.email.text(),
            "phone":        self.phone.text(),
            "linkedin_url": self.linkedin.text(),
            "city":         self.city.text(),
            "state":        self.state.text(),
            "country":      self.country.text() or "United States",
        }
        profile["resume_path"] = self.resume.text().strip()
        self.persona.save_profile(profile)
        QMessageBox.information(self, "Profile", "Saved.")
        self.profile_saved.emit()


# === Walkthroughs Page: step-by-step guides ===

class WalkthroughsPage(QWidget):
    """Step-by-step guides for every feature."""

    WALKTHROUGHS = [
        ("🎯  Set up your first persona", [
            "Click '+ New persona' on the left.",
            "Give it a name (lowercase, no spaces). E.g. 'supply-chain-exec' or 'my-dream-job'.",
            "Click Select → on the new persona.",
            "The next screen has a searchable parameter editor. Type 'salary' to filter.",
            "Set salary_min and salary_max using the spinboxes.",
            "Add your job titles (one per line).",
            "Click Start when you're ready.",
        ]),
        ("📄  Upload your resume", [
            "On the RunConfig screen (or the Profile tab in The Couch), find the 'Resume path' field.",
            "Type or browse to a .txt, .docx, or .pdf file.",
            "Click 'Parse → Profile' to auto-fill your name, email, phone, and skills.",
            "Click 'Save Profile' to persist.",
            "Lazi will use this profile to auto-fill every form the bots encounter.",
        ]),
        ("🚫  Add a company or title to the blacklist", [
            "On the RunConfig screen, find the 'Blacklist' box.",
            "Type a company name in the 'Company:' field, click Add.",
            "Type a title keyword in the 'Title:' field, click Add.",
            "To remove, type the name again and click Remove.",
            "Lazi's on_job filter will skip any job matching the blacklist.",
        ]),
        ("🔒  Save a site password", [
            "Open The Couch (Command Center) → Passwords tab.",
            "Type a site (e.g. 'linkedin.com'), URL, username, password.",
            "Click 💾 Save / Add.",
            "The vault is encrypted with Fernet. Master key in OS Credential Manager.",
            "Nobody can read it without your OS user account.",
        ]),
        ("🌐  Use the embedded browser", [
            "Open The Couch → Browser tab.",
            "Type a URL, press Enter.",
            "Check 'Headless' to run without a window.",
            "Log into LinkedIn once — cookies persist in your persona's Chrome profile.",
            "The browser is real Chromium (Qt WebEngine). Playwright is the fallback.",
        ]),
        ("🧠  Chat with Lazi", [
            "I'm at the bottom of every screen. Type anything.",
            "I can set parameters, swap your resume, add to blacklist, answer questions.",
            "If your LLM provider is configured (Poolside / OpenAI), I use it.",
            "Otherwise I use my canned 'monacary' personality — food metaphors, couch references, the whole vibe.",
        ]),
        ("🚀  Start your first run", [
            "Pick a persona.",
            "Pick a provider (Poolside / OpenAI / None).",
            "Pick a mode: auto-apply or scrape-only.",
            "Pick an engine (5 to choose from: easyapplyjobsbot, linkedin-aihawk, etc.).",
            "Set max jobs, hit Start.",
            "Watch the log panel for live output. Lazi's doing the work.",
        ]),
        ("🎮  Game Selection: pick the right engine", [
            "easyapplyjobsbot — form filling, no AI. Fastest, least smart.",
            "linkedin-aihawk — YAML resume answers. No LLM needed.",
            "auto-job-applier — GodsScion's engine. Heavy, comprehensive.",
            "linkedin-bot — OpenAI/Gemini answers form questions. Smartest.",
            "job-apply-ai-agent — scrapes + tailors CVs. No auto-apply.",
            "Pick based on whether you want speed (easyapplyjobsbot) or intelligence (linkedin-bot).",
        ]),
    ]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("📖  Walkthroughs — the Lazi guide")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #6b4a1a;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll_layout = QVBoxLayout(inner)

        for header, steps in self.WALKTHROUGHS:
            frame = QFrame()
            frame.setStyleSheet("background: white; border: 2px solid #b48a3a; border-radius: 10px; padding: 12px;")
            fl = QVBoxLayout(frame)
            h = QLabel(header)
            h.setStyleSheet("font-size: 16px; font-weight: bold; color: #3a2410;")
            fl.addWidget(h)
            for s in steps:
                lbl = QLabel("•  " + s)
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #3a2410; padding: 2px;")
                fl.addWidget(lbl)
            scroll_layout.addWidget(frame)

        scroll_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)


# === Game Selection Page: pick an engine with playful descriptions ===

class GameSelectionPage(QWidget):
    """Pick which bot engine to use. Each one has a personality."""

    engine_chosen = Signal(str)

    ENGINES = [
        ("easyapplyjobsbot", "🛡  Easy Apply Jobs Bot",
         "The workhorse. Form-fills, no LLM. Fast, dumb, reliable. Like a golden retriever — eager, not clever.",
         "Best for: high volume, simple forms, no LLM budget."),
        ("linkedin-aihawk", "🦅  LinkedIn AI Hawk",
         "Resume-based answers. No LLM needed at runtime. Smart enough for 80% of jobs, dumb enough to never get creative.",
         "Best for: clean resumés, no API budget, want it to just work."),
        ("auto-job-applier", "🏛  GodsScion Auto Job Applier",
         "The big one. Heaviest, most thorough, most options. Supports multiple AI providers. Will try every filter combination known to LinkedIn.",
         "Best for: power users, when you want to throw everything at the wall."),
        ("linkedin-bot", "🤖  LinkedIn Bot (lukerbs)",
         "The smart one. Uses OpenAI to answer custom form questions. Poolside-compatible. Will read the JD and write a tailored answer.",
         "Best for: applications with custom questions, when you have an API key."),
        ("job-apply-ai-agent", "📄  Job Apply AI Agent",
         "The tailor. Scrapes jobs, then generates a tailored CV for each. Doesn't auto-apply — you do.",
         "Best for: custom CVs, manual apply workflow."),
    ]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel("🎮  Game Selection — pick your fighter")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #6b4a1a;")
        layout.addWidget(title)
        sub = QLabel("Each engine in the Lazi monacary has a different vibe. Pick the one that fits the battle.")
        sub.setStyleSheet("color: #7a5a2a;")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        sl = QVBoxLayout(inner)
        for key, name, desc, best in self.ENGINES:
            card = QFrame()
            card.setStyleSheet("background: white; border: 2px solid #b48a3a; border-radius: 10px; padding: 12px;")
            cl = QVBoxLayout(card)
            h = QLabel(name)
            h.setStyleSheet("font-size: 16px; font-weight: bold; color: #3a2410;")
            cl.addWidget(h)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setStyleSheet("color: #3a2410; padding: 4px;")
            cl.addWidget(d)
            b = QLabel(best)
            b.setWordWrap(True)
            b.setStyleSheet("color: #2a7a2a; font-style: italic; padding: 4px;")
            cl.addWidget(b)
            btn = QPushButton(f"Pick {name.split('  ', 1)[-1] if '  ' in name else name}")
            btn.setStyleSheet("background: #b48a3a; color: white; padding: 8px; border-radius: 6px; font-weight: bold;")
            btn.clicked.connect(lambda _, k=key: self.engine_chosen.emit(k))
            cl.addWidget(btn)
            sl.addWidget(card)
        sl.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)


# === The Couch (Command Center) — tabbed: Welcome / Browser / Passwords / Walkthroughs / Profile / Game Selection ===

class TheCouch(QWidget):
    """
    The Couch is the Command Center of the app. Tabs:
      - Welcome: "Welcome 2 the Couch" onboarding + walkthrough
      - Walkthroughs: step-by-step guides for every feature
      - Profile: per-persona profile editor with avatar
      - Game Selection: pick the engine (the "bot battle" scenario)
      - Browser: embedded Qt WebEngine browser (visible or headless)
      - Passwords: encrypted vault for site logins (LinkedIn, GitHub, etc.)
    """
    ready = Signal()
    persona_changed = Signal(str)
    engine_chosen = Signal(str)

    WELCOME_TITLE = "Welcome 2 the Couch, chief."
    WELCOME_BODY = (
        "I'm Lazi — slightly overweight, slightly dirty, very useful. This is the guide.\n"
        "Read it once, then I'll get out of your way and start applying to jobs.\n\n"
        "The Couch is your Command Center. You can:\n"
        "  • Walk through the setup step by step (Walkthroughs tab)\n"
        "  • Edit your profile and upload a resume (Profile tab)\n"
        "  • Pick which bot engine to deploy (Game Selection tab)\n"
        "  • Browse LinkedIn / Indeed in-app (Browser tab)\n"
        "  • Save site logins in an encrypted vault (Passwords tab)\n\n"
        "When you're done, hit 'Set up the Couch' to roll."
    )

    def __init__(self, parent=None, persona_name: Optional[str] = None):
        super().__init__(parent)
        self.persona_name = persona_name or ""
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
        # Tab 2: Walkthroughs
        self.tabs.addTab(WalkthroughsPage(), "📖  Walkthroughs")
        # Tab 3: Profile
        self.profile_page = self._build_profile_tab()
        self.tabs.addTab(self.profile_page, "👤  Profile")
        # Tab 4: Game Selection
        self.game_page = GameSelectionPage()
        self.game_page.engine_chosen.connect(self.engine_chosen)
        self.tabs.addTab(self.game_page, "🎮  Game Selection")
        # Tab 5: Browser
        from .browser_widget import BrowserWidget
        self.browser = BrowserWidget()
        self.tabs.addTab(self.browser, "🌐  Browser")
        # Tab 6: Passwords
        self.passwords = PasswordVaultWidget()
        self.tabs.addTab(self.passwords, "🔒  Passwords")

    def _build_welcome_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        title = QLabel(self.WELCOME_TITLE)
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #6b4a1a; padding: 4px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        intro = QLabel(self.WELCOME_BODY)
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 14px; padding: 16px; background: #f0e2c0; border-radius: 8px; color: #3a2410;")
        layout.addWidget(intro)

        from .profile_store import list_personas
        self.persona_combo = QComboBox()
        self._refresh_persona_combo()
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

    def _build_profile_tab(self) -> QWidget:
        from .profile_store import list_personas, Persona, create_persona
        if not self.persona_name or not Persona(self.persona_name).exists:
            personas = list_personas()
            if personas:
                self.persona_name = personas[0]
            else:
                # No personas yet — show an empty placeholder, don't auto-create
                return self._build_empty_profile_tab()
        page = ProfilePage(self.persona_name)
        page.profile_saved.connect(self._on_profile_saved)
        return page

    def _build_empty_profile_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("👤  No persona yet")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #6b4a1a;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        body = QLabel(
            "Create a persona on the left (click '+ New persona'),\n"
            "then come back to edit your profile here."
        )
        body.setStyleSheet("color: #3a2410; font-size: 14px;")
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch()
        return w

    def _refresh_persona_combo(self):
        from .profile_store import list_personas
        self.persona_combo.clear()
        personas = list_personas()
        if not personas:
            self.persona_combo.addItem("(no personas yet — create one in the picker)")
        else:
            self.persona_combo.addItems(personas)
            if self.persona_name and self.persona_name in personas:
                self.persona_combo.setCurrentText(self.persona_name)
        self.persona_combo.currentTextChanged.connect(self._on_persona_changed_in_combo)

    def _on_persona_changed_in_combo(self, name: str):
        if name.startswith("("):
            return
        self.persona_name = name
        self.persona_changed.emit(name)
        old_idx = self.tabs.indexOf(self.profile_page)
        self.tabs.removeTab(old_idx)
        self.profile_page = ProfilePage(name)
        self.profile_page.profile_saved.connect(self._on_profile_saved)
        self.tabs.insertTab(old_idx, self.profile_page, "👤  Profile")
        self.tabs.setCurrentIndex(old_idx)

    def _on_profile_saved(self):
        QMessageBox.information(self, "Profile", "Profile saved.")

    def set_persona(self, name: str):
        self.persona_name = name
        self._refresh_persona_combo()


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
