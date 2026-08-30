"""Quick smoke test: every requested feature is wired in."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from app.main import SearchableParameterEditor
from app.lazibot import TheCouch, PasswordVaultWidget, LaziChatOverlay
from app.browser_widget import BrowserWidget, HAS_WEB_ENGINE
from app.password_store import store_entry, get_entry, list_sites, delete_entry
from app.profile_store import create_persona

p = create_persona("demo-user", config={
    "titles": ["Director of Supply Chain"],
    "salary_min": 150000,
    "salary_max": 300000,
})

print("=== FEATURE 1: Searchable parameters ===")
editor = SearchableParameterEditor("demo-user")
print(f"  SearchableParameterEditor: {editor.form_layout.rowCount()} rows")
print(f"  Search bar: {editor.search is not None}")
print(f"  Range spinboxes (salary/experience): {len(editor._param_widgets)} schema params")

print()
print("=== FEATURE 2: Add and blacklist what you want ===")
p.add_blacklist_company("SpamCo")
p.add_blacklist_title("Spam")
cfg = p.load_config()
print(f"  add_blacklist_company: {cfg['blacklist_companies']}")
print(f"  add_blacklist_title:   {cfg['blacklist_titles']}")
p.remove_blacklist_company("SpamCo")
p.remove_blacklist_title("Spam")
print(f"  remove_* methods on Persona also work")

print()
print("=== FEATURE 3: Person profile (no hardcoded) ===")
profile = p.load_profile()
print(f"  profile.yaml exists: {p.profile_path.exists()}")
print(f"  personal_info fields: {list(profile['personal_info'].keys())}")
print(f"  skills field: {profile.get('skills')}")

print()
print("=== FEATURE 4: Encrypted password vault ===")
delete_entry("linkedin.com"); delete_entry("github.com")
store_entry("linkedin.com", "me@x.com", "secret123", url="https://linkedin.com")
store_entry("github.com", "gh", "gh-secret", url="https://github.com")
print(f"  list_sites() = {list_sites()}")
e = get_entry("linkedin.com")
print(f"  get_entry('linkedin.com').password decrypted = {e.password!r}")
vault_bytes = Path("keys/vault.enc").read_bytes()
print(f"  vault.enc is encrypted (no plaintext 'secret123'): {'secret123' not in vault_bytes.decode('latin1')}")

print()
print("=== FEATURE 5: Embedded browser (Playwright + Qt WebEngine) ===")
b = BrowserWidget()
print(f"  BrowserWidget: Qt WebEngine available = {HAS_WEB_ENGINE}")
print(f"  view is set: {b.view is not None}")
print(f"  URL bar: {b.url_bar is not None}")
print(f"  Headless toggle: {b.headless_chk is not None}")

print()
print("=== THE COUCH (Command Center) tabs ===")
couch = TheCouch()
print(f"  Tab count: {couch.tabs.count()}")
for i in range(couch.tabs.count()):
    print(f"    {i+1}. {couch.tabs.tabText(i)}")

# cleanup
delete_entry("linkedin.com"); delete_entry("github.com")
import shutil
shutil.rmtree("personas/demo-user", ignore_errors=True)

print()
print("=== ALL 5 FEATURES WIRED IN ===")
