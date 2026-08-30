"""
PySide6 GUI for linkedin-autopilot.

Window stack:
  1. PersonaPicker / TheCouch (onboarding + command center)
  2. RunConfig (provider / mode / engine / max jobs)
  3. RunView (live log + results)
  4. SearchableParameterEditor (filterable grid of all persona params)
  5. LaziChatOverlay (floating bot in the corner)

FIXED (review 2026-08-30):
  - RunView.start() is now called from RunConfig._start
  - Qt thread-safety: log_callback emits a Signal that fires _log on the main thread
  - _SpinBox hack removed; QSpinBox/QCheckBox imported properly
  - PersonaPicker iterates all personas (no hardcoded list)
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QTableWidget, QTableWidgetItem,
    QMessageBox, QFrame, QDialog, QFormLayout, QCheckBox, QSpinBox,
    QLineEdit, QFileDialog, QGroupBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QSplitter,
)

from app.profile_store import (
    Persona, list_personas, ensure_persona, resolve_api_key, PARAM_SCHEMA,
)
from app.bot_runner import ENGINES, run, RunResult
from app.resume_parser import profile_from_resume
from app.auto_filler import answer_form
from app.lazibot import LaziBrain, LaziChatOverlay, TheCouch, PasswordVaultWidget
from app.browser_widget import BrowserWidget

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


# === Thread-safe log bridge ===

class _LogBridge(QObject):
    line = Signal(str)


# === Page 0: Persona picker with Couch onboarding ===

class PersonaPicker(QMainWindow):
    persona_chosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("linkedin-autopilot — Pick Persona")
        self.resize(720, 540)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Left: persona list
        left = QWidget()
        ll = QVBoxLayout(left)
        title = QLabel("Select a job-search persona")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        ll.addWidget(title)

        # No hardcoded personas — the user enters their own.
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)

        # Empty-state hint when no personas exist (create BEFORE refresh)
        self.empty_hint = QLabel(
            "👋 No personas yet. Click '+ New persona' to create one.\n"
            "After you create it, your settings are saved and reused forever."
        )
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: #666; padding: 12px; font-style: italic;")
        ll.addWidget(self.empty_hint)

        self._refresh_persona_list()
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        ll.addWidget(self.list_widget, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        select_btn = QPushButton("Select →")
        select_btn.clicked.connect(self._on_select_clicked)
        new_btn = QPushButton("+ New persona")
        new_btn.clicked.connect(self._new_persona)
        del_btn = QPushButton("🗑 Delete")
        del_btn.clicked.connect(self._delete_persona)
        btn_row.addWidget(select_btn)
        btn_row.addWidget(new_btn)
        btn_row.addWidget(del_btn)
        ll.addLayout(btn_row)

        layout.addWidget(left, stretch=1)

        # Right: The Couch
        self.couch = TheCouch()
        self.couch.ready.connect(self._couch_ready)
        layout.addWidget(self.couch, stretch=2)

        # Lazi overlay
        self.brain = LaziBrain(self)
        self.lazi = LaziChatOverlay(self, brain=self.brain)
        self.lazi.command.connect(self._on_lazi_command)
        QTimer.singleShot(100, self._position_lazi)

        self.setCentralWidget(central)

    def _display_name(self, name: str) -> str:
        # No hardcoded display names — just humanize the directory name.
        return name.replace("-", " ").replace("_", " ").title()

    def _refresh_persona_list(self):
        self.list_widget.clear()
        for name in list_personas():
            item = QListWidgetItem(self._display_name(name))
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)
        self._update_empty_hint()

    def _update_empty_hint(self):
        has = self.list_widget.count() > 0
        self.empty_hint.setVisible(not has)

    def _on_select_clicked(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "Pick a persona", "Select a persona first.")
            return
        self.persona_chosen.emit(item.data(Qt.UserRole))

    def _on_double_click(self, item: QListWidgetItem):
        self.persona_chosen.emit(item.data(Qt.UserRole))

    def _new_persona(self):
        from .profile_store import create_persona
        name, ok = QInputDialog_getText(
            self, "Create persona",
            "Persona name (no spaces, lowercase):\n"
            "e.g. 'supply-chain-exec', 'procurement', 'data-scientist'"
        )
        if not ok or not name:
            return
        name = name.strip().lower().replace(" ", "-").replace("_", "-")
        if not name:
            return
        from pathlib import Path
        existing = list_personas()
        if name in existing:
            QMessageBox.warning(self, "Create persona", f"Persona '{name}' already exists.")
            return
        # Create with empty config — user fills in everything in the GUI
        create_persona(name, config={
            "titles": [],
            "location": "United States",
            "salary_min": 0,
            "salary_max": 0,
        })
        item = QListWidgetItem(self._display_name(name))
        item.setData(Qt.UserRole, name)
        self.list_widget.addItem(item)
        self.list_widget.setCurrentItem(item)
        self._update_empty_hint()
        QMessageBox.information(
            self, "Persona created",
            f"Persona '{name}' created with empty defaults.\n\n"
            "After you select it, the next screen lets you set titles, "
            "salary range, experience years, blacklist, and upload a resume."
        )

    def _delete_persona(self):
        from .profile_store import delete_persona
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "Delete", "Select a persona to delete.")
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

    def _couch_ready(self):
        item = self.list_widget.currentItem()
        if item:
            self.persona_chosen.emit(item.data(Qt.UserRole))
        else:
            QMessageBox.information(self, "Pick a persona", "Select a persona before continuing.")

    def _position_lazi(self):
        self.lazi.move(self.width() - self.lazi.width() - 16, self.height() - self.lazi.height() - 16)
        self.lazi.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.lazi:
            self._position_lazi()

    def _on_lazi_command(self, key: str, payload: dict):
        # Lazi wants to set a param. Persist it on the active persona.
        item = self.list_widget.currentItem()
        if not item:
            return
        p = Persona(item.data(Qt.UserRole))
        v = payload.get("value", "")
        try:
            ival = int(str(v).replace("$", "").replace(",", ""))
            p.update_config(**{key: ival})
        except Exception:
            p.update_config(**{key: v})


def QInputDialog_getText(*args, **kwargs):
    """Tiny shim so we don't add a QtWidgets import line."""
    from PySide6.QtWidgets import QInputDialog
    return QInputDialog.getText(*args, **kwargs)


# === Page 1: Run config ===

class RunConfig(QMainWindow):
    def __init__(self, persona_name: str, brain: Optional[LaziBrain] = None):
        super().__init__()
        self.persona_name = persona_name
        self.brain = brain or LaziBrain(self)
        self.setWindowTitle(f"linkedin-autopilot — Config: {persona_name}")
        self.resize(900, 600)
        self._build_ui()
        self._log_bridge = _LogBridge()
        self._log_bridge.line.connect(self._dummy_log)  # RunView will re-wire

    def _dummy_log(self, text: str):
        # placeholder; RunConfig doesn't render logs
        logger.info(text)

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        persona = Persona(self.persona_name)
        cfg = persona.load_config()
        profile = persona.load_profile()

        # Header
        info = QLabel(
            f"<b>Persona:</b> {self.persona_name}  |  "
            f"Titles: {len(cfg['titles'])}  |  "
            f"Salary: ${cfg['salary_min']:,} – ${cfg.get('salary_max', cfg['salary_min']):,}  |  "
            f"Location: {cfg['location']}"
        )
        layout.addWidget(info)

        # Splitter: left = SearchableParameterEditor, right = Lazi chat
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # --- LEFT: searchable parameter editor ---
        self.param_editor = SearchableParameterEditor(self.persona_name)
        splitter.addWidget(self.param_editor)

        # --- RIGHT: profile + resume + run config ---
        right = QWidget()
        rl = QVBoxLayout(right)

        # Run config
        cfg_box = QGroupBox("Run config")
        cf = QFormLayout(cfg_box)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["none", "poolside", "openai", "google"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        cf.addRow("Provider:", self.provider_combo)

        self.key_status = QLabel("—")
        cf.addRow("Key status:", self.key_status)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["auto-apply", "scrape"])
        cf.addRow("Mode:", self.mode_combo)

        self.engine_combo = QComboBox()
        self.engine_combo.addItems(list(ENGINES.keys()))
        cf.addRow("Engine:", self.engine_combo)

        self.max_jobs_spin = QSpinBox()
        self.max_jobs_spin.setRange(1, 500)
        self.max_jobs_spin.setValue(50)
        cf.addRow("Max jobs:", self.max_jobs_spin)

        self.headless_chk = QCheckBox("headless (hidden browser)")
        cf.addRow("Options:", self.headless_chk)

        rl.addWidget(cfg_box)

        # Profile + resume
        prof_box = QGroupBox("Profile (auto-fill forms from this)")
        pf = QFormLayout(prof_box)
        self.pi_first = QLineEdit(profile["personal_info"].get("first_name",""))
        self.pi_last  = QLineEdit(profile["personal_info"].get("last_name",""))
        self.pi_email = QLineEdit(profile["personal_info"].get("email",""))
        self.pi_phone = QLineEdit(profile["personal_info"].get("phone",""))
        self.pi_link  = QLineEdit(profile["personal_info"].get("linkedin_url",""))
        self.pi_city  = QLineEdit(profile["personal_info"].get("city",""))
        self.pi_state = QLineEdit(profile["personal_info"].get("state",""))
        self.pi_country = QLineEdit(profile["personal_info"].get("country","United States"))
        for label, w in [
            ("First name:", self.pi_first), ("Last name:", self.pi_last),
            ("Email:", self.pi_email), ("Phone:", self.pi_phone),
            ("LinkedIn URL:", self.pi_link), ("City:", self.pi_city),
            ("State:", self.pi_state), ("Country:", self.pi_country),
        ]:
            pf.addRow(label, w)

        resume_row = QHBoxLayout()
        self.resume_path = QLineEdit(profile.get("resume_path","") or "")
        resume_browse = QPushButton("Browse…")
        resume_browse.clicked.connect(self._browse_resume)
        resume_apply = QPushButton("Parse → Profile")
        resume_apply.clicked.connect(self._parse_resume_to_profile)
        resume_row.addWidget(self.resume_path)
        resume_row.addWidget(resume_browse)
        resume_row.addWidget(resume_apply)
        pf.addRow("Resume path:", resume_row)

        resume_save = QPushButton("Save Profile")
        resume_save.clicked.connect(self._save_profile)
        pf.addRow("", resume_save)

        rl.addWidget(prof_box)

        # Blacklist add/remove
        bl_box = QGroupBox("Blacklist")
        bf = QVBoxLayout(bl_box)
        bl_row1 = QHBoxLayout()
        bl_row1.addWidget(QLabel("Company:"))
        self.bl_company_input = QLineEdit()
        bl_row1.addWidget(self.bl_company_input)
        bl_row1.addWidget(self._mk_btn("Add", lambda: self._add_blacklist("company")))
        bl_row1.addWidget(self._mk_btn("Remove", lambda: self._add_blacklist("company", remove=True)))
        bf.addLayout(bl_row1)
        bl_row2 = QHBoxLayout()
        bl_row2.addWidget(QLabel("Title:"))
        self.bl_title_input = QLineEdit()
        bl_row2.addWidget(self.bl_title_input)
        bl_row2.addWidget(self._mk_btn("Add", lambda: self._add_blacklist("title")))
        bl_row2.addWidget(self._mk_btn("Remove", lambda: self._add_blacklist("title", remove=True)))
        bf.addLayout(bl_row2)
        rl.addWidget(bl_box)

        rl.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([500, 400])

        # Start button
        self.start_btn = QPushButton("🚀 Start")
        self.start_btn.setStyleSheet("font-size: 16px; padding: 12px;")
        self.start_btn.clicked.connect(self._start)
        layout.addWidget(self.start_btn)

        # Lazi overlay
        self.lazi = LaziChatOverlay(self, brain=self.brain)
        self.lazi.command.connect(lambda k, v: self.param_editor.set_param(k, v))
        QTimer.singleShot(100, self._position_lazi)

        self.setCentralWidget(central)
        self._on_provider_changed()

    def _mk_btn(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

    def _on_provider_changed(self):
        provider = self.provider_combo.currentText()
        if provider == "none":
            self.key_status.setText("No API key (form-only answering)")
        else:
            key = resolve_api_key(provider)
            self.key_status.setText("✅ Found" if key else "❌ Missing — go to keys/")

    def _browse_resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select resume", "", "Resumes (*.txt *.md *.docx *.pdf)"
        )
        if path:
            self.resume_path.setText(path)

    def _parse_resume_to_profile(self):
        path = self.resume_path.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Resume", "Pick a valid resume file first.")
            return
        parsed = profile_from_resume(path)
        # fill fields
        pi = parsed["personal_info"]
        self.pi_first.setText(pi.get("first_name", ""))
        self.pi_last.setText(pi.get("last_name", ""))
        self.pi_email.setText(pi.get("email", ""))
        self.pi_phone.setText(pi.get("phone", ""))
        self.pi_link.setText(pi.get("linkedin_url", ""))
        self.pi_country.setText(pi.get("country", "United States"))
        QMessageBox.information(
            self, "Resume parsed",
            f"Found {len(parsed['skills'])} skills, "
            f"{len(parsed['experience'])} experience entries, "
            f"{len(parsed['education'])} education entries. "
            "Click Save Profile to persist."
        )

    def _save_profile(self):
        p = Persona(self.persona_name)
        profile = p.load_profile()
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
        p.save_profile(profile)
        QMessageBox.information(self, "Profile", "Saved.")

    def _add_blacklist(self, kind: str, remove: bool = False):
        p = Persona(self.persona_name)
        if kind == "company":
            val = self.bl_company_input.text().strip()
            if not val:
                return
            if remove:
                p.remove_blacklist_company(val)
            else:
                p.add_blacklist_company(val)
        else:
            val = self.bl_title_input.text().strip()
            if not val:
                return
            if remove:
                p.remove_blacklist_title(val)
            else:
                p.add_blacklist_title(val)
        QMessageBox.information(self, "Blacklist", f"{'Removed' if remove else 'Added'}: {val}")

    def _position_lazi(self):
        self.lazi.move(self.width() - self.lazi.width() - 16, self.height() - self.lazi.height() - 16)
        self.lazi.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.lazi:
            self._position_lazi()

    def _start(self):
        # save profile first if user typed anything
        if self.pi_first.text() or self.pi_email.text():
            self._save_profile()

        provider = self.provider_combo.currentText()
        mode = self.mode_combo.currentText()
        engine = self.engine_combo.currentText()
        max_jobs = self.max_jobs_spin.value()
        headless = self.headless_chk.isChecked()

        # configure Lazi brain with provider key (so it can talk to LLM)
        if provider != "none":
            self.brain.configure(provider, resolve_api_key(provider))

        self._run_window = RunView(
            persona_name=self.persona_name,
            engine=engine,
            provider=provider,
            mode=mode,
            max_jobs=max_jobs,
            headless=headless,
            brain=self.brain,
        )
        self._run_window.show()
        self._run_window.start()  # FIXED: actually start the background thread
        self.close()


# === Searchable parameter editor ===

class SearchableParameterEditor(QWidget):
    """
    Filterable grid of all persona parameters. Search bar on top;
    ranges show as min/max spinboxes, bools as checkboxes, strs as line edits.
    Edits write back to search_config.yaml immediately.
    """
    def __init__(self, persona_name: str):
        super().__init__()
        self.persona_name = persona_name
        self.persona = Persona(persona_name)
        self._cfg = self.persona.load_config()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        title = QLabel("Searchable parameters")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # Search bar
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Search parameters (e.g. salary, remote, blacklist)…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        # Container for param widgets
        self.container = QWidget()
        self.form_layout = QFormLayout(self.container)
        layout.addWidget(self.container, stretch=1)

        # Titles + blacklist
        self.titles_edit = QTextEdit()
        self.titles_edit.setPlainText("\n".join(self._cfg["titles"]))
        self.titles_edit.textChanged.connect(self._save_titles)
        self.form_layout.addRow("Titles (one per line):", self.titles_edit)

        self.location_edit = QLineEdit(self._cfg["location"])
        self.location_edit.editingFinished.connect(self._save_location)
        self.form_layout.addRow("Location:", self.location_edit)

        # dynamic per PARAM_SCHEMA
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
            else:  # str with options
                w = QComboBox()
                opts = spec.get("options") or [str(default)]
                w.addItems(opts)
                w.setCurrentText(str(current))
                w.currentTextChanged.connect(lambda v, k=key: self._save_param(k, v))
            self._param_widgets[key] = w
            self.form_layout.addRow(spec["label"] + ":", w)

        # Blacklist (companies + titles)
        bl_companies = QTextEdit()
        bl_companies.setPlainText("\n".join(self._cfg["blacklist_companies"]))
        bl_companies.textChanged.connect(lambda: self._save_list("blacklist_companies", bl_companies.toPlainText()))
        self.form_layout.addRow("Blacklist companies:", bl_companies)
        self._param_widgets["blacklist_companies"] = bl_companies

        bl_titles = QTextEdit()
        bl_titles.setPlainText("\n".join(self._cfg["blacklist_titles"]))
        bl_titles.textChanged.connect(lambda: self._save_list("blacklist_titles", bl_titles.toPlainText()))
        self.form_layout.addRow("Blacklist titles:", bl_titles)
        self._param_widgets["blacklist_titles"] = bl_titles

        # Auto-filler test
        test_btn = QPushButton("🧪 Test auto-filler (simulate form)")
        test_btn.clicked.connect(self._test_auto_filler)
        self.form_layout.addRow("", test_btn)
        self._test_output = QTextEdit()
        self._test_output.setReadOnly(True)
        self.form_layout.addRow("Auto-filler output:", self._test_output)

    def _filter(self, q: str):
        q = q.strip().lower()
        for i in range(self.form_layout.rowCount()):
            label_item = self.form_layout.itemAt(i, QFormLayout.ItemRole.LabelRole)
            field_item = self.form_layout.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if not label_item or not field_item:
                continue
            label_text = ""
            if label_item.widget():
                label_text = label_item.widget().text().lower()
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
        """Public hook so Lazi overlay can set a parameter."""
        w = self._param_widgets.get(key)
        if w is None:
            return
        try:
            if isinstance(w, QSpinBox):
                w.setValue(int(value))
            elif isinstance(w, QCheckBox):
                w.setChecked(str(value).lower() in ("true","yes","1"))
            elif isinstance(w, QComboBox):
                w.setCurrentText(str(value))
        except Exception as e:
            logger.warning("set_param failed: %s", e)

    def _test_auto_filler(self):
        from .auto_filler import answer_form
        sample = [
            "First name", "Last name", "Email", "Phone",
            "City", "State", "Country",
            "Years of experience", "Expected salary",
            "Do you have a Bachelor's degree?",
            "Are you authorized to work in the US?",
        ]
        ans = answer_form(sample, self.persona)
        lines = []
        for i, q in enumerate(sample):
            a = ans.get(str(i), "(no answer)")
            lines.append(f"  {q:40s} -> {a}")
        self._test_output.setPlainText("\n".join(lines))


# === Page 2: Run view ===

class RunView(QMainWindow):
    """Step 3: live log + results table."""

    def __init__(self, persona_name, engine, provider, mode, max_jobs, headless, brain=None):
        super().__init__()
        self.persona_name = persona_name
        self.engine = engine
        self.provider = provider
        self.mode = mode
        self.max_jobs = max_jobs
        self.headless = headless
        self.brain = brain or LaziBrain(self)
        self.setWindowTitle(f"linkedin-autopilot — Running ({engine})")
        self.resize(900, 600)
        self._log_bridge = _LogBridge()
        self._log_bridge.line.connect(self._log)  # main-thread slot
        self._build_ui()

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
        self.results_table.verticalHeader().setVisible(False)
        layout.addWidget(self.results_table, stretch=2)

        stop = QPushButton("⏹ Stop")
        stop.clicked.connect(self._stop)
        layout.addWidget(stop)

        self.setCentralWidget(central)

        # Lazi overlay
        self.lazi = LaziChatOverlay(self, brain=self.brain)
        QTimer.singleShot(100, self._position_lazi)

    def _log(self, text: str):
        self.log_panel.append(text)
        sb = self.log_panel.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _position_lazi(self):
        self.lazi.move(self.width() - self.lazi.width() - 16, self.height() - self.lazi.height() - 16)
        self.lazi.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.lazi:
            self._position_lazi()

    def start(self):
        """Run the bot_runner.run() in a background thread."""
        self._log(f"▶ Starting: {self.engine} / {self.persona_name} / {self.provider} / {self.mode}")
        # thread-safe log forwarder: emit to main thread
        def emit(line: str):
            self._log_bridge.line.emit(line)
        self._log_forwarder = emit

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
                for e in result.errors:
                    emit(f"  ⚠ {e}")
            except Exception as e:
                emit(f"❌ Fatal error: {e}")
                emit(traceback.format_exc())

        t = threading.Thread(target=_work, daemon=True)
        t.start()

    def _stop(self):
        self._log("⏹ Stop requested (subprocesses will exit when their loop ends)")


# === Entry point ===

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    win = PersonaPicker()
    win.persona_chosen.connect(lambda name: open_run_config(name, win))
    win.show()
    sys.exit(app.exec())


def open_run_config(persona_name: str, picker: PersonaPicker):
    rc = RunConfig(persona_name, brain=picker.brain)
    rc.show()
    picker.close()


if __name__ == "__main__":
    main()
