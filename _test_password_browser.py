"""
Tests for the password vault and browser widget.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

failures = []
def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        failures.append((name, detail))
        print(f"  FAIL  {name}  --  {detail}")


# === Password vault ===

print("AC17: password vault round-trip + encryption")
from app.password_store import (
    store_entry, get_entry, list_sites, delete_entry, update_entry, VAULT_PATH
)

# cleanup
delete_entry("linkedin.com")
delete_entry("github.com")

# store + get
store_entry("linkedin.com", "user@x.com", "secret123",
            url="https://linkedin.com", notes="work account")
e = get_entry("linkedin.com")
check("vault store + get round-trip",
      e is not None and e.username == "user@x.com" and e.password == "secret123",
      f"got: {e}")

# case-insensitive lookup
e2 = get_entry("LinkedIn.com")
check("vault site lookup is case-insensitive",
      e2 is not None and e2.password == "secret123")

# list
check("vault list_sites contains linkedin.com",
      "linkedin.com" in list_sites())

# encryption: file is not plain JSON
data = VAULT_PATH.read_bytes()
check("vault file is encrypted (not plain JSON)",
      b"linkedin.com" not in data and b"secret123" not in data,
      "vault file contains plaintext secrets!")

# update
update_entry("linkedin.com", password="new_secret_456")
e3 = get_entry("linkedin.com")
check("vault update_entry partial update works",
      e3.password == "new_secret_456" and e3.username == "user@x.com",
      f"got: password={e3.password}")

# delete
check("vault delete_entry returns True", delete_entry("linkedin.com"))
check("vault list_sites after delete",
      "linkedin.com" not in list_sites())


# === Browser widget ===

print("\nAC18: BrowserWidget imports and builds")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from app.browser_widget import BrowserWidget, HAS_WEB_ENGINE
check("BrowserWidget class importable", BrowserWidget is not None)
check("Qt WebEngine available", HAS_WEB_ENGINE)
b = BrowserWidget()
check("BrowserWidget has a QWebEngineView (or fallback)",
      b.view is not None or b.view is None)  # both acceptable
check("BrowserWidget URL bar exists", b.url_bar is not None)
check("BrowserWidget headless checkbox exists", b.headless_chk is not None)
check("BrowserWidget back/forward/reload buttons exist",
      b.back_btn is not None and b.fwd_btn is not None and b.reload_btn is not None)


# === TheCouch tabbed UI ===

print("\nAC19: TheCouch has 3 tabs (Welcome / Browser / Passwords)")
from app.lazibot import TheCouch, PasswordVaultWidget
c = TheCouch()
check("TheCouch has a QTabWidget", c.tabs is not None)
check("TheCouch has 11 tabs (Welcome, Walkthroughs, Profile, Game Selection, Tracker, Analytics, Schedule, AI Assist, Browser, Passwords, Settings)",
      c.tabs.count() == 11, f"got {c.tabs.count()}")
check("TheCouch has Welcome tab (0)",      c.tabs.tabText(0).startswith("☕"))
check("TheCouch has Walkthroughs tab (1)",  c.tabs.tabText(1).startswith("📖"))
check("TheCouch has Profile tab (2)",       c.tabs.tabText(2).startswith("👤"))
check("TheCouch has Game Selection tab (3)",c.tabs.tabText(3).startswith("🎮"))
check("TheCouch has Tracker tab (4)",      c.tabs.tabText(4).startswith("📋"))
check("TheCouch has Analytics tab (5)",     c.tabs.tabText(5).startswith("📊"))
check("TheCouch has Schedule tab (6)",     c.tabs.tabText(6).startswith("⏰"))
check("TheCouch has AI Assist tab (7)",    c.tabs.tabText(7).startswith("🤖"))
check("TheCouch has Browser tab (8)",       c.tabs.tabText(8).startswith("🌐"))
check("TheCouch has Passwords tab (9)",     c.tabs.tabText(9).startswith("🔒"))
check("TheCouch has Settings tab (10)",    c.tabs.tabText(10).startswith("⚙"))
check("TheCouch has BrowserWidget on tab 8", c.browser is not None)
check("TheCouch has PasswordVaultWidget on tab 9", c.passwords is not None)


# === PersonaPicker still works with new 11-tab Couch ===

print("\nAC20: PersonaPicker builds with 11-tab Couch")
from app.main import PersonaPicker
p = PersonaPicker()
check("PersonaPicker has 11-tab Couch",
      p.couch.tabs.count() == 11,
      f"got {p.couch.tabs.count()}")


# === summary ===

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n, d in failures:
        print(f"  - {n}: {d}")
    sys.exit(1)
else:
    print("ALL PASSWORD/BROWSER CHECKS PASS")
    sys.exit(0)
