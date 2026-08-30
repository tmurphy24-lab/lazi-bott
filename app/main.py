"""
PySide6 GUI for linkedin-autopilot.

v3 (refactor 2026-08-30): UI design system + flow refactor
  - Single AppController owns all windows + active persona
  - RunConfig uses a left sidebar nav with 4 sub-sections
  - Toast notifications replace QMessageBox spam
  - Keyboard shortcuts: Ctrl+N (new persona), Ctrl+S (save), F1 (help), Esc (close)
  - Lazi Dock is the bottom bar on every page

The 4 sub-pages of RunConfig:
  1. 👤 Profile   — personal info, resume upload
  2. 🎯 Search    — searchable parameter editor + run config
  3. 🚫 Blacklist — companies + titles to avoid
  4. 🚀 Run       — provider, mode, engine, start button
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QComboBox, QTextEdit, QTableWidget, QTableWidgetItem,
    QMessageBox, QFrame, QDialog, QFormLayout, QCheckBox, QSpinBox, QInputDialog,
    QLineEdit, QFileDialog, QGroupBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QSplitter, QDockWidget, QStatusBar,
)

from app.profile_store import (
    Persona, list_personas, ensure_persona, resolve_api_key, PARAM_SCHEMA,
)
from app.bot_runner import ENGINES, run, RunResult
from app.resume_parser import profile_from_resume
from app.auto_filler import answer_form
from app.lazibot import LaziBrain, LaziChatOverlay, LaziDock, TheCouch, WelcomeSplash
from app.browser_widget import BrowserWidget
from app.ui_kit import (
    LaziColors, apply_app_theme, ToastManager, Toast, Card, SectionHeader,
    EmptyState, StatusBadge, StatBlock, IconLabel, Divider, Toolbar,
    SPACING, SHADOWS,
)

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


# === Thread-safe log bridge ===

class _LogBridge(QObject):
    line = Signal(str)


# === Single app controller ===

class AppController(QObject):
    """
    Owns the active persona and the live windows. Replaces manual window juggling.

    Signals:
      persona_changed(str) — fired when the user picks a different persona
      theme_changed(str)   — fired when theme is switched
    """
    persona_changed = Signal(str)
    theme_changed = Signal(str)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.active_persona: Optional[str] = None
        self.theme_name: str = "couch"
        self._windows: List[QMainWindow] = []
        # apply initial theme
        apply_app_theme(app, self.theme_name)

    def track_window(self, w: QMainWindow) -> None:
        self._windows.append(w)

    def untrack_window(self, w: QMainWindow) -> None:
        if w in self._windows:
            self._windows.remove(w)

    def set_active_persona(self, name: str) -> None:
        self.active_persona = name
        self.persona_changed.emit(name)

    def set_theme(self, name: str) -> None:
        if name not in ("couch", "stealth"):
            return
        self.theme_name = name
        apply_app_theme(self.app, name)
        self.theme_changed.emit(name)

    def toast(self, parent: QWidget, message: str, level: str = "info") -> None:
        ToastManager.show(parent, message, level=level)

    def quit_clean(self) -> None:
        for w in list(self._windows):
            try:
                w.close()
            except Exception:
                pass
        self._windows.clear()
        self.app.quit()


# === Shared form widgets (used by Profile sub-page) ===

class ProfileSubPage(QWidget):
    """👤 Sub-page: personal info + resume upload."""

    def __init__(self, persona_name: str, controller: AppController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.persona_name = persona_name
        self.controller = controller
        self.persona = Persona(persona_name)
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        # personal info card
        info_card = Card("Personal info")
        form = QFormLayout()
        self.pi_first   = QLineEdit()
        self.pi_last    = QLineEdit()
        self.pi_email   = QLineEdit()
        self.pi_phone   = QLineEdit()
        self.pi_link    = QLineEdit()
        self.pi_city    = QLineEdit()
        self.pi_state   = QLineEdit()
        self.pi_country = QLineEdit()
        for label, w in [
            ("First name:", self.pi_first), ("Last name:", self.pi_last),
            ("Email:", self.pi_email),       ("Phone:", self.pi_phone),
            ("LinkedIn URL:", self.pi_link),  ("City:", self.pi_city),
            ("State:", self.pi_state),        ("Country:", self.pi_country),
        ]:
            form.addRow(label, w)
        info_card.body.addLayout(form)

        # resume card
        resume_card = Card("Resume (TXT / DOCX / PDF)")
        rform = QFormLayout()
        self.resume_path = QLineEdit()
        self.resume_status = StatusBadge("No resume loaded", level="warn")
        rform.addRow("Path:", self.resume_path)
        rform.addRow("Status:", self.resume_status)
        btn_row = QHBoxLayout()
        b1 = QPushButton("Browse…")
        b1.setProperty("variant", "ghost")
        b1.clicked.connect(self._browse_resume)
        b2 = QPushButton("Parse → Profile")
        b2.setProperty("variant", "ghost")
        b2.clicked.connect(self._parse_resume_to_profile)
        b3 = QPushButton("Save")
        b3.setProperty("variant", "primary")
        b3.clicked.connect(self._save)
        btn_row.addWidget(b1)
        btn_row.addWidget(b2)
        btn_row.addStretch()
        btn_row.addWidget(b3)
        rform.addRow("", _wrap(btn_row))
        resume_card.body.addLayout(rform)

        # save status
        self.save_status = StatusBadge("", level="info")
        info_card.body.addWidget(self.save_status, alignment=Qt.AlignRight)

        outer.addWidget(info_card)
        outer.addWidget(resume_card)
        outer.addStretch()

    def focus_first_input(self):
        """Focus the first field — called by parent when this page becomes current."""
        self.pi_first.setFocus()
        self.pi_first.selectAll()

    def _browse_resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select resume", "", "Resumes (*.txt *.md *.docx *.pdf)"
        )
        if path:
            self.resume_path.setText(path)
            self.resume_status.set_text(f"Selected: {Path(path).name}", level="info")

    def _parse_resume_to_profile(self):
        path = self.resume_path.text().strip()
        if not path or not Path(path).exists():
            self.controller.toast(self, "Pick a valid resume file first.", level="warn")
            return
        parsed = profile_from_resume(path)
        pi = parsed["personal_info"]
        self.pi_first.setText(pi.get("first_name", ""))
        self.pi_last.setText(pi.get("last_name", ""))
        self.pi_email.setText(pi.get("email", ""))
        self.pi_phone.setText(pi.get("phone", ""))
        self.pi_link.setText(pi.get("linkedin_url", ""))
        self.pi_country.setText(pi.get("country", "United States"))
        n_skills = len(parsed.get("skills", []))
        n_exp = len(parsed.get("experience", []))
        n_edu = len(parsed.get("education", []))
        self.resume_status.set_text(
            f"Parsed: {n_skills} skills, {n_exp} jobs, {n_edu} schools", level="success"
        )
        self.controller.toast(
            self,
            f"Resume parsed: {n_skills} skills, {n_exp} jobs, {n_edu} schools. Click Save.",
            level="success",
        )

    def _save(self):
        profile = self.persona.load_profile()
        profile["personal_info"] = {
            "first_name":   self.pi_first.text(),
            "last_name":    self.pi_last.text(),
            "email":        self.pi_email.text(),
            "phone":        self.pi_phone.text(),
            "linkedin_url": self.pi_link.text(),
            "city":         self.pi_city.text(),
            "state":        self.pi_state.text(),
            "country":      self.pi_country.text() or "United States",
        }
        profile["resume_path"] = self.resume_path.text().strip()
        self.persona.save_profile(profile)
        self.save_status.set_text("✓ Saved", level="success")
        self.controller.toast(self, "Profile saved.", level="success")

    def _load(self):
        profile = self.persona.load_profile()
        pi = profile.get("personal_info", {})
        self.pi_first.setText(pi.get("first_name", ""))
        self.pi_last.setText(pi.get("last_name", ""))
        self.pi_email.setText(pi.get("email", ""))
        self.pi_phone.setText(pi.get("phone", ""))
        self.pi_link.setText(pi.get("linkedin_url", ""))
        self.pi_city.setText(pi.get("city", ""))
        self.pi_state.setText(pi.get("state", ""))
        self.pi_country.setText(pi.get("country", "United States"))
        rp = profile.get("resume_path", "") or ""
        self.resume_path.setText(rp)
        if rp and Path(rp).exists():
            self.resume_status.set_text(f"Loaded: {Path(rp).name}", level="success")
        elif rp:
            self.resume_status.set_text("File not found", level="warn")
        else:
            self.resume_status.set_text("No resume loaded", level="warn")


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


# === Search sub-page (searchable parameter editor + run config) ===

class SearchSubPage(QWidget):
    """🎯 Sub-page: searchable parameter editor + run config in one card."""

    def __init__(self, persona_name: str, controller: AppController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.persona_name = persona_name
        self.controller = controller
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        # searchable params card
        params_card = Card("Searchable parameters (type to filter)")
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Filter by label (e.g. 'salary', 'remote', 'experience')")
        self.search.textChanged.connect(self._filter)
        params_card.body.addWidget(self.search)
        self.form_holder = QWidget()
        self.form_layout = QFormLayout(self.form_holder)
        params_card.body.addWidget(self.form_holder)

        # delegate all real widget construction to the existing
        # SearchableParameterEditor; we just render it inside our card
        from app.main import SearchableParameterEditor
        self._editor = SearchableParameterEditor(self.persona_name)
        # the editor owns its own layout; render the editor widget directly
        params_card.body.addWidget(self._editor)

        outer.addWidget(params_card)
        outer.addStretch()

    def focus_first_input(self):
        """Focus the search bar — called by parent when this page becomes current."""
        self.search.setFocus()
        self.search.selectAll()

    def _filter(self, q: str):
        # delegate to the editor's own filter
        self._editor._filter(q)


# === Blacklist sub-page ===

class BlacklistSubPage(QWidget):
    """🚫 Sub-page: add/remove companies and titles to avoid."""

    def __init__(self, persona_name: str, controller: AppController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.persona_name = persona_name
        self.controller = controller
        self.persona = Persona(persona_name)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        # companies
        co_card = Card("Blacklisted companies (skipped by on_job filter)")
        co_row = QHBoxLayout()
        self.co_edit = QLineEdit()
        self.co_edit.setPlaceholderText("Company name (e.g. SpamCo, StaffingRUs)")
        co_row.addWidget(self.co_edit)
        add = QPushButton("Add")
        add.setProperty("variant", "primary")
        add.clicked.connect(self._add_company)
        rem = QPushButton("Remove")
        rem.setProperty("variant", "ghost")
        rem.clicked.connect(lambda: self._add_company(remove=True))
        co_row.addWidget(add)
        co_row.addWidget(rem)
        co_card.body.addLayout(co_row)
        self.co_list = QListWidget()
        co_card.body.addWidget(self.co_list, stretch=1)
        outer.addWidget(co_card)

        # titles
        ti_card = Card("Blacklisted title keywords")
        ti_row = QHBoxLayout()
        self.ti_edit = QLineEdit()
        self.ti_edit.setPlaceholderText("Title keyword (e.g. Junior, Intern, Recruiter)")
        ti_row.addWidget(self.ti_edit)
        add2 = QPushButton("Add")
        add2.setProperty("variant", "primary")
        add2.clicked.connect(self._add_title)
        rem2 = QPushButton("Remove")
        rem2.setProperty("variant", "ghost")
        rem2.clicked.connect(lambda: self._add_title(remove=True))
        ti_row.addWidget(add2)
        ti_row.addWidget(rem2)
        ti_card.body.addLayout(ti_row)
        self.ti_list = QListWidget()
        ti_card.body.addWidget(self.ti_list, stretch=1)
        outer.addWidget(ti_card)
        outer.addStretch()

    def focus_first_input(self):
        """Focus the first input — called by parent when this page becomes current."""
        self.co_edit.setFocus()

    def _refresh(self):
        cfg = self.persona.load_config()
        self.co_list.clear()
        for c in cfg.get("blacklist_companies", []):
            self.co_list.addItem(c)
        self.ti_list.clear()
        for t in cfg.get("blacklist_titles", []):
            self.ti_list.addItem(t)

    def _add_company(self, remove: bool = False):
        val = self.co_edit.text().strip()
        if not val:
            self.controller.toast(self, "Type a company name first.", level="warn")
            return
        if remove:
            self.persona.remove_blacklist_company(val)
            self.controller.toast(self, f"Removed '{val}'.", level="info")
        else:
            self.persona.add_blacklist_company(val)
            self.controller.toast(self, f"Blacklisted '{val}'.", level="success")
        self.co_edit.clear()
        self._refresh()

    def _add_title(self, remove: bool = False):
        val = self.ti_edit.text().strip()
        if not val:
            self.controller.toast(self, "Type a title keyword first.", level="warn")
            return
        if remove:
            self.persona.remove_blacklist_title(val)
            self.controller.toast(self, f"Removed '{val}'.", level="info")
        else:
            self.persona.add_blacklist_title(val)
            self.controller.toast(self, f"Blacklisted '{val}'.", level="success")
        self.ti_edit.clear()
        self._refresh()


# === Run sub-page (provider, mode, engine, start) ===

class RunSubPage(QWidget):
    """🚀 Sub-page: provider, mode, engine, max jobs, start button."""

    run_requested = Signal(dict)  # emitted with run params

    def __init__(self, persona_name: str, controller: AppController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.persona_name = persona_name
        self.controller = controller
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        run_card = Card("Run configuration")
        form = QFormLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["none", "poolside", "openai", "google"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self.provider_combo)
        self.key_status = QLabel("—")
        form.addRow("Key status:", self.key_status)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["auto-apply", "scrape"])
        form.addRow("Mode:", self.mode_combo)
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(list(ENGINES.keys()))
        form.addRow("Engine:", self.engine_combo)
        self.max_jobs_spin = QSpinBox()
        self.max_jobs_spin.setRange(1, 500)
        self.max_jobs_spin.setValue(50)
        form.addRow("Max jobs:", self.max_jobs_spin)
        self.headless_chk = QCheckBox("headless (hidden browser)")
        form.addRow("Options:", self.headless_chk)
        run_card.body.addLayout(form)

        outer.addWidget(run_card)

        # Start button (primary variant — uses design-system accent)
        self.start_btn = QPushButton("🚀  Start run")
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.setMinimumHeight(48)
        self.start_btn.setToolTip("Start the bot run (Enter)")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._start)
        outer.addWidget(self.start_btn)

        # Auto-filler test output
        test_card = Card("🧪 Auto-filler test (see what Lazi would answer)")
        test_card.body.addWidget(QLabel("Click to preview answers for a sample form:"))
        self.test_btn = QPushButton("Run preview")
        self.test_btn.clicked.connect(self._test_auto_filler)
        test_card.body.addWidget(self.test_btn)
        self.test_output = QTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMaximumHeight(160)
        test_card.body.addWidget(self.test_output)

        outer.addWidget(test_card)
        outer.addStretch()

    def focus_first_input(self):
        """Focus the first interactive control — called by parent when this page becomes current."""
        self.start_btn.setFocus()

    def _on_provider_changed(self):
        provider = self.provider_combo.currentText()
        if provider == "none":
            self.key_status.setText("No API key (form-only answering)")
        else:
            key = resolve_api_key(provider)
            self.key_status.setText("✅ Found" if key else "❌ Missing — see Settings")

    def _start(self):
        params = dict(
            persona_name=self.persona_name,
            engine=self.engine_combo.currentText(),
            provider=self.provider_combo.currentText(),
            mode=self.mode_combo.currentText(),
            max_jobs=self.max_jobs_spin.value(),
            headless=self.headless_chk.isChecked(),
        )
        self.controller.toast(self, f"Starting {params['engine']} for {self.persona_name}…", level="info")
        self.run_requested.emit(params)

    def _test_auto_filler(self):
        questions = [
            "First name", "Last name", "Email", "Phone",
            "Years of experience", "Expected salary",
        ]
        ans = answer_form(questions, Persona(self.persona_name))
        lines = []
        for i, q in enumerate(questions):
            a = ans.get(str(i), "(no answer)")
            lines.append(f"  {q:30s} -> {a}")
        self.test_output.setPlainText("\n".join(lines))


# === RunConfig with sidebar nav (refactored) ===

class RunConfig(QMainWindow):
    """Refactored RunConfig: 4 sub-pages (Profile, Search, Blacklist, Run) in a sidebar layout."""

    def __init__(self, persona_name: str, controller: AppController, brain: LaziBrain):
        super().__init__()
        self.persona_name = persona_name
        self.controller = controller
        self.brain = brain
        self.setWindowTitle(f"linkedin-autopilot — {persona_name}")
        self.resize(1000, 700)
        self._build_ui()
        self._install_shortcuts()
        # status bar
        sb = QStatusBar()
        sb.showMessage(f"Ready — {persona_name} selected.")
        self.setStatusBar(sb)
        controller.track_window(self)

    def _build_ui(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # LEFT: sidebar nav (using proper spacing + active state)
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar.setObjectName("sidebar")
        sbl = QVBoxLayout(sidebar)
        sbl.setContentsMargins(0, SPACING["sm"], 0, SPACING["sm"])
        sbl.setSpacing(0)
        # header
        header_lbl = QLabel("📋  CONFIG")
        header_lbl.setProperty("type", "caption")
        header_lbl.setContentsMargins(SPACING["lg"], SPACING["sm"], SPACING["lg"], SPACING["sm"])
        sbl.addWidget(header_lbl)
        sbl.addWidget(Divider())

        # nav buttons (icon + label, proper active state)
        self.nav_buttons: List[QPushButton] = []
        NAV_ITEMS = [
            ("👤", "Profile",   "Ctrl+1"),
            ("🎯", "Search",    "Ctrl+2"),
            ("🚫", "Blacklist", "Ctrl+3"),
            ("🚀", "Run",       "Ctrl+4"),
        ]
        nav_holder = QWidget()
        nav_layout = QVBoxLayout(nav_holder)
        nav_layout.setContentsMargins(0, SPACING["sm"], 0, SPACING["sm"])
        nav_layout.setSpacing(2)
        for idx, (icon, label, hint) in enumerate(NAV_ITEMS):
            btn = QPushButton(f"  {icon}   {label}")
            btn.setCheckable(True)
            btn.setToolTip(f"{label}  ({hint})")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(44)
            btn.setProperty("nav", "true")
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            nav_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        sbl.addWidget(nav_holder)

        sbl.addStretch()
        sbl.addWidget(Divider())

        # persona footer
        persona_footer = QWidget()
        pf = QVBoxLayout(persona_footer)
        pf.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        pf.setSpacing(SPACING["xs"])
        pn = IconLabel("👤", self.persona_name.replace("-", " ").title(), size=14)
        pf.addWidget(pn)
        switch = QPushButton("Change persona…")
        switch.setProperty("variant", "ghost")
        switch.clicked.connect(self._change_persona)
        pf.addWidget(switch)
        sbl.addWidget(persona_footer)
        outer.addWidget(sidebar)

        # RIGHT: stacked sub-pages
        self.stack = QStackedWidget()
        self.profile_page  = ProfileSubPage(self.persona_name, self.controller)
        self.search_page   = SearchSubPage(self.persona_name, self.controller)
        self.blacklist_pg  = BlacklistSubPage(self.persona_name, self.controller)
        self.run_page      = RunSubPage(self.persona_name, self.controller)
        self.run_page.run_requested.connect(self._on_run_requested)
        self.stack.addWidget(self.profile_page)
        self.stack.addWidget(self.search_page)
        self.stack.addWidget(self.blacklist_pg)
        self.stack.addWidget(self.run_page)
        outer.addWidget(self.stack, stretch=1)

        self.setCentralWidget(central)
        # default to Run page
        self._switch_page(3)

        # bottom dock: Lazi
        self.lazi_dock = LaziDock(self, brain=self.brain)
        from PySide6.QtWidgets import QDockWidget
        self.lazi_widget = QDockWidget("Lazi — bottom dock", self)
        self.lazi_widget.setWidget(self.lazi_dock)
        self.lazi_widget.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.lazi_widget)
        # legacy overlay (hidden)
        self.lazi_overlay = LaziChatOverlay(self, brain=self.brain)
        self.lazi_overlay.command.connect(self._on_lazi_command)
        self.lazi_overlay.hide()

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self._switch_page(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self._switch_page(1))
        QShortcut(QKeySequence("Ctrl+3"), self, activated=lambda: self._switch_page(2))
        QShortcut(QKeySequence("Ctrl+4"), self, activated=lambda: self._switch_page(3))
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_active)
        QShortcut(QKeySequence("Esc"),   self, activated=self.close)

    def _switch_page(self, idx: int):
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)
        # Focus management: each sub-page exposes focus_first_input() that
        # moves focus to its primary input. Deferred so the stack is settled.
        pages = [self.profile_page, self.search_page, self.blacklist_pg, self.run_page]
        if 0 <= idx < len(pages):
            page = pages[idx]
            if hasattr(page, "focus_first_input"):
                QTimer.singleShot(0, page.focus_first_input)

    def _save_active(self):
        # save whatever the current sub-page cares about
        if self.stack.currentIndex() == 0:
            self.profile_page._save()
        else:
            self.controller.toast(self, "Nothing to save on this page.", level="info")

    def _on_run_requested(self, params: dict):
        # hand off to the bot runner; show RunView in a new window
        if params["provider"] != "none":
            self.brain.configure(params["provider"], resolve_api_key(params["provider"]))
        rv = RunView(
            persona_name=params["persona_name"],
            engine=params["engine"],
            provider=params["provider"],
            mode=params["mode"],
            max_jobs=params["max_jobs"],
            headless=params["headless"],
            brain=self.brain,
            controller=self.controller,
        )
        rv.show()
        rv.start()
        self.hide()

    def _on_lazi_command(self, key: str, payload: dict):
        # forward to search sub-page
        if hasattr(self.search_page, "_editor"):
            self._switch_page(1)
            self.search_page._editor.set_param(key, payload.get("value", ""))
            self.controller.toast(self, f"Lazi set {key}={payload.get('value','')}", level="success")

    def _change_persona(self):
        # open PersonaPicker
        names = list_personas()
        if not names:
            self.controller.toast(self, "No personas yet. Create one first.", level="warn")
            return
        name, ok = QInputDialog.getItem(self, "Change persona", "Pick a persona:", names, 0, False)
        if ok and name:
            self.persona_name = name
            self.controller.set_active_persona(name)
            self.close()
            new_rc = RunConfig(name, self.controller, self.brain)
            new_rc.show()

    def keyPressEvent(self, event):
        # global Q key on search page jumps to search bar
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            self._switch_page(1)
            self.search_page.search.setFocus()
        else:
            super().keyPressEvent(event)


# === Searchable parameter editor (kept, slight cleanup) ===

class SearchableParameterEditor(QWidget):
    """Filterable grid of all persona parameters. Used inside SearchSubPage."""

    def __init__(self, persona_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.persona_name = persona_name
        self.persona = Persona(persona_name)
        self._cfg = self.persona.load_config()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Filter by label…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.container = QWidget()
        self.form_layout = QFormLayout(self.container)
        layout.addWidget(self.container, stretch=1)

        # titles
        self.titles_edit = QTextEdit()
        self.titles_edit.setPlainText("\n".join(self._cfg["titles"]))
        self.titles_edit.setMaximumHeight(80)
        self.titles_edit.textChanged.connect(self._save_titles)
        self.form_layout.addRow("Titles (one per line):", self.titles_edit)
        # location
        self.location_edit = QLineEdit(self._cfg["location"])
        self.location_edit.editingFinished.connect(self._save_location)
        self.form_layout.addRow("Location:", self.location_edit)

        self._param_widgets: Dict[str, QWidget] = {}
        for spec in PARAM_SCHEMA:
            key, typ, default = spec["key"], spec["type"], spec["default"]
            current = self._cfg.get(key, default)
            if typ == "int":
                w = QSpinBox()
                w.setRange(spec.get("min", 0), spec.get("max", 1_000_000))
                w.setSingleStep(spec.get("step", 1))
                w.setValue(int(current))
                w.valueChanged.connect(lambda v, k=key: self._save_param(k, v))
            elif typ == "bool":
                w = QCheckBox()
                w.setChecked(bool(current))
                w.toggled.connect(lambda v, k=key: self._save_param(k, v))
            else:
                w = QComboBox()
                opts = spec.get("options") or [str(default)]
                w.addItems(opts)
                w.setCurrentText(str(current))
                w.currentTextChanged.connect(lambda v, k=key: self._save_param(k, v))
            self._param_widgets[key] = w
            self.form_layout.addRow(spec["label"] + ":", w)

        # blacklist text edits
        bl_co = QTextEdit()
        bl_co.setPlainText("\n".join(self._cfg["blacklist_companies"]))
        bl_co.setMaximumHeight(60)
        bl_co.textChanged.connect(lambda: self._save_list("blacklist_companies", bl_co.toPlainText()))
        self.form_layout.addRow("Blacklist companies:", bl_co)
        self._param_widgets["blacklist_companies"] = bl_co

        bl_ti = QTextEdit()
        bl_ti.setPlainText("\n".join(self._cfg["blacklist_titles"]))
        bl_ti.setMaximumHeight(60)
        bl_ti.textChanged.connect(lambda: self._save_list("blacklist_titles", bl_ti.toPlainText()))
        self.form_layout.addRow("Blacklist titles:", bl_ti)
        self._param_widgets["blacklist_titles"] = bl_ti

    def _filter(self, q: str):
        q = q.strip().lower()
        for i in range(self.form_layout.rowCount()):
            label_item = self.form_layout.itemAt(i, QFormLayout.ItemRole.LabelRole)
            field_item = self.form_layout.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if not label_item or not field_item:
                continue
            label_text = label_item.widget().text().lower() if label_item.widget() else ""
            show = (not q) or (q in label_text)
            if label_item.widget():
                label_item.widget().setVisible(show)
            if field_item.widget():
                field_item.widget().setVisible(show)

    def _save_param(self, key, value):
        self._cfg[key] = value
        self.persona.save_config(self._cfg)

    def _save_titles(self):
        titles = [t.strip() for t in self.titles_edit.toPlainText().splitlines() if t.strip()]
        self._cfg["titles"] = titles
        self.persona.save_config(self._cfg)

    def _save_location(self):
        self._cfg["location"] = self.location_edit.text().strip()
        self.persona.save_config(self._cfg)

    def _save_list(self, key, raw):
        items = [t.strip() for t in raw.splitlines() if t.strip()]
        self._cfg[key] = items
        self.persona.save_config(self._cfg)

    def set_param(self, key: str, value):
        w = self._param_widgets.get(key)
        if w is None:
            return
        try:
            if isinstance(w, QSpinBox):
                w.setValue(int(value))
            elif isinstance(w, QCheckBox):
                w.setChecked(str(value).lower() in ("true", "yes", "1"))
            elif isinstance(w, QComboBox):
                w.setCurrentText(str(value))
        except Exception as e:
            logger.warning("set_param failed: %s", e)


# === RunView with controller + status bar ===

class RunView(QMainWindow):
    """Step 3: live log + results table."""

    def __init__(self, persona_name, engine, provider, mode, max_jobs, headless,
                 brain=None, controller: Optional[AppController] = None):
        super().__init__()
        self.persona_name = persona_name
        self.engine = engine
        self.provider = provider
        self.mode = mode
        self.max_jobs = max_jobs
        self.headless = headless
        self.brain = brain or LaziBrain(self)
        self.controller = controller
        self.setWindowTitle(f"linkedin-autopilot — Running ({engine})")
        self.resize(900, 600)
        self._log_bridge = _LogBridge()
        self._log_bridge.line.connect(self._log)
        self._build_ui()
        if controller:
            controller.track_window(self)

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        info = QLabel(
            f"Persona: {self.persona_name}  |  Engine: {self.engine}  |  "
            f"Provider: {self.provider}  |  Mode: {self.mode}"
        )
        layout.addWidget(info)

        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setStyleSheet("font-family: monospace; font-size: 12px;")
        layout.addWidget(self.log_panel, stretch=3)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Job Title", "Company", "Status", "Error"])
        layout.addWidget(self.results_table, stretch=2)

        stop = QPushButton("⏹ Stop")
        stop.clicked.connect(self._stop)
        layout.addWidget(stop)
        self.setCentralWidget(central)

        # status bar
        sb = QStatusBar()
        self.status_label = QLabel("Running…")
        sb.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        sb.addPermanentWidget(self.progress)
        self.setStatusBar(sb)

        # Lazi dock
        self.lazi_dock = LaziDock(self, brain=self.brain)
        from PySide6.QtWidgets import QDockWidget
        self.lazi_widget = QDockWidget("Lazi — bottom dock", self)
        self.lazi_widget.setWidget(self.lazi_dock)
        self.lazi_widget.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.lazi_widget)

    def _log(self, text: str):
        self.log_panel.append(text)
        sb = self.log_panel.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start(self):
        self._log(f"▶ Starting: {self.engine} / {self.persona_name} / {self.provider} / {self.mode}")
        if self.controller:
            self.controller.toast(self, f"Run started: {self.engine}", level="info")
        self.status_label.setText("Running…")

        def emit(line: str):
            self._log_bridge.line.emit(line)

        def _work():
            try:
                result: RunResult = run(
                    persona_name=self.persona_name,
                    engine_name=self.engine,
                    provider=self.provider,
                    mode=self.mode,
                    max_jobs=self.max_jobs,
                    headless=self.headless,
                    log_callback=emit,
                )
                emit(f"✅ Done. Found: {result.jobs_found}, Applied: {result.jobs_applied}, "
                     f"Skipped: {result.jobs_skipped}, Failed: {result.jobs_failed}")
                self.status_label.setText(
                    f"Done: {result.jobs_applied} applied, {result.jobs_failed} failed"
                )
                if self.controller:
                    self.controller.toast(
                        self,
                        f"Run complete: {result.jobs_applied} applied, {result.jobs_failed} failed",
                        level="success",
                    )
                for e in result.errors:
                    emit(f"  ⚠ {e}")
            except Exception as e:
                emit(f"❌ Fatal error: {e}")
                emit(traceback.format_exc())
                self.status_label.setText("Fatal error")
                if self.controller:
                    self.controller.toast(self, f"Fatal error: {e}", level="error")

        t = threading.Thread(target=_work, daemon=True)
        t.start()

    def _stop(self):
        self.status_label.setText("Stop requested")
        if self.controller:
            self.controller.toast(self, "Stop requested.", level="warn")
        self._log("⏹ Stop requested (subprocesses will exit when their loop ends)")


# === Page 0: PersonaPicker (refactored with controller + keyboard shortcuts) ===

class PersonaPicker(QMainWindow):
    persona_chosen = Signal(str)

    def __init__(self, controller: AppController, brain: LaziBrain):
        super().__init__()
        self.controller = controller
        self.brain = brain
        self.setWindowTitle("linkedin-autopilot — Pick Persona")
        self.resize(820, 600)
        self._build_ui()
        self._install_shortcuts()
        sb = QStatusBar()
        sb.showMessage("Ready. Ctrl+N to create a new persona. F1 for help.")
        self.setStatusBar(sb)
        controller.track_window(self)

    def _build_ui(self):
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # left: persona list with a proper toolbar + empty state
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        # toolbar with title + New button
        toolbar = Toolbar("Personas")
        toolbar.add_right(self._make_toolbar_btn("➕ New", "Ctrl+N", self._new_persona, variant="primary"))
        ll.addWidget(toolbar)

        # stat block + divider
        stats_row = QWidget()
        sl = QHBoxLayout(stats_row)
        sl.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        sl.setSpacing(SPACING["lg"])
        self.stat_count = StatBlock("0", "personas")
        self.stat_jobs = StatBlock("0", "applied")
        sl.addWidget(self.stat_count)
        sl.addWidget(self.stat_jobs)
        sl.addStretch()
        ll.addWidget(stats_row)
        ll.addWidget(Divider())

        # the actual list (or EmptyState)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        ll.addWidget(self.list_widget, stretch=1)

        # EmptyState (shown when no personas) — big illustration + bigger CTA
        self.empty_state = EmptyState(
            icon="👋",
            title="No personas yet",
            body="Create your first persona to start applying for jobs. "
                 "Each persona has its own titles, salary range, resume, and blacklist.",
            action_text="➕  Create your first persona",
            on_action=self._new_persona,
            big_cta=True,
        )
        self.empty_state.hide()
        ll.addWidget(self.empty_state)

        # action buttons at bottom
        bottom = QWidget()
        bottom.setStyleSheet("QWidget { background: palette(window); border-top: 1px solid palette(midlight); }")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"])
        bl.setSpacing(SPACING["sm"])
        select = self._make_toolbar_btn("▶ Select", "Enter", self._on_select_clicked, variant="primary")
        delete = self._make_toolbar_btn("🗑 Delete", "Del", self._delete_persona, variant="ghost")
        bl.addWidget(select)
        bl.addStretch()
        bl.addWidget(delete)
        ll.addWidget(bottom)

        layout.addWidget(left, stretch=1)

        # right: The Couch
        self.couch = TheCouch()
        layout.addWidget(self.couch, stretch=2)

        # Lazi bottom dock
        self.lazi_dock = LaziDock(self, brain=self.brain)
        layout.addWidget(self.lazi_dock)

        # Lazi legacy floating (hidden)
        self.lazi_overlay = LaziChatOverlay(self, brain=self.brain)
        self.lazi_overlay.command.connect(self._on_lazi_command)
        self.lazi_overlay.hide()

        self.setCentralWidget(central)
        self._refresh_persona_list()

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_persona)
        QShortcut(QKeySequence("F1"),      self, activated=self._show_help)
        QShortcut(QKeySequence("Ctrl+,"),  self, activated=self._open_settings)
        QShortcut(QKeySequence("Return"),  self, activated=self._on_select_clicked)
        QShortcut(QKeySequence("Enter"),   self, activated=self._on_select_clicked)
        QShortcut(QKeySequence("Esc"),     self, activated=self.close)

    def _show_help(self):
        QMessageBox.information(
            self, "Keyboard shortcuts",
            "Ctrl+N   New persona\n"
            "Ctrl+1/2/3/4   Jump to RunConfig sub-page (in RunConfig window)\n"
            "Ctrl+S   Save current sub-page (in RunConfig window)\n"
            "Ctrl+F   Focus search bar (in Search sub-page)\n"
            "Ctrl+,   Open Settings tab in The Couch\n"
            "F1       This help\n"
            "Enter    Select highlighted persona\n"
            "Esc      Close window",
        )

    def _open_settings(self):
        for i in range(self.couch.tabs.count()):
            if "Settings" in self.couch.tabs.tabText(i):
                self.couch.tabs.setCurrentIndex(i)
                return
        self.controller.toast(self, "Settings tab not found in this Couch version.", level="warn")

    def _make_toolbar_btn(self, text: str, hint: str, slot, variant: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(f"{text}  ({hint})" if hint else text)
        b.clicked.connect(slot)
        if variant:
            b.setProperty("variant", variant)
        return b

    def _refresh_persona_list(self):
        self.list_widget.clear()
        for name in list_personas():
            display = name.replace("-", " ").replace("_", " ").title()
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)
        # toggle empty state vs list
        has = self.list_widget.count() > 0
        self.list_widget.setVisible(has)
        self.empty_state.setVisible(not has)
        # update stat block
        n = len(list_personas())
        self.stat_count.set_value(str(n))
        # applied count from job tracker
        try:
            from app.job_tracker import list_applications
            n_jobs = len(list_applications())
        except Exception:
            n_jobs = 0
        self.stat_jobs.set_value(str(n_jobs))

    def _update_empty_hint(self):
        # Kept for back-compat; now delegates to _refresh_persona_list
        self._refresh_persona_list()

    def _on_select_clicked(self):
        item = self.list_widget.currentItem()
        if not item:
            self.controller.toast(self, "Select a persona first.", level="warn")
            return
        name = item.data(Qt.UserRole)
        self._open_run_config(name)

    def _on_double_click(self, item: QListWidgetItem):
        self._open_run_config(item.data(Qt.UserRole))

    def _new_persona(self):
        name, ok = QInputDialog.getText(
            self, "Create persona",
            "Persona name (lowercase, no spaces):\n"
            "e.g. 'supply-chain-exec', 'procurement', 'data-scientist'"
        )
        if not ok or not name:
            return
        name = name.strip().lower().replace(" ", "-").replace("_", "-")
        if not name:
            return
        if name in list_personas():
            self.controller.toast(self, f"Persona '{name}' already exists.", level="warn")
            return
        from app.profile_store import create_persona
        create_persona(name, config={
            "titles": [],
            "location": "United States",
            "salary_min": 0,
            "salary_max": 0,
        })
        item = QListWidgetItem(name.replace("-", " ").title())
        item.setData(Qt.UserRole, name)
        self.list_widget.addItem(item)
        self.list_widget.setCurrentItem(item)
        self._update_empty_hint()
        self.controller.toast(
            self,
            f"Persona '{name}' created. Now set titles, salary, resume in RunConfig.",
            level="success",
        )

    def _delete_persona(self):
        from app.profile_store import delete_persona
        item = self.list_widget.currentItem()
        if not item:
            self.controller.toast(self, "Select a persona to delete.", level="warn")
            return
        name = item.data(Qt.UserRole)
        if QMessageBox.question(
            self, "Delete persona",
            f"Delete persona '{name}' and all its files?\n(This cannot be undone.)"
        ) != QMessageBox.Yes:
            return
        if delete_persona(name):
            self.list_widget.takeItem(self.list_widget.row(item))
            self._update_empty_hint()
            self.controller.toast(self, f"Deleted persona '{name}'.", level="info")

    def _open_run_config(self, persona_name: str):
        self.controller.set_active_persona(persona_name)
        rc = RunConfig(persona_name, self.controller, self.brain)
        rc.show()
        self.hide()

    def _on_lazi_command(self, key: str, payload: dict):
        # legacy overlay command — open run config
        if self.controller.active_persona:
            self._open_run_config(self.controller.active_persona)
        else:
            self.controller.toast(self, "Pick a persona first.", level="warn")


# === Entry point ===

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    controller = AppController(app)
    brain = LaziBrain()
    win = PersonaPicker(controller, brain)
    # Show WelcomeSplash on first run
    splash = WelcomeSplash(win)
    splash.setGeometry(win.geometry())
    splash.dismissed.connect(splash.deleteLater)
    splash.show()
    QTimer.singleShot(800, splash.raise_)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
