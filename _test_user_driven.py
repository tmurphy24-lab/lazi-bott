"""
Tests that personas are user-driven, not hardcoded.

  AC30: on a clean personas/ dir, no personas exist
  AC31: ensure_persona creates an empty placeholder (no titles, no blacklist)
  AC32: create_persona uses the user-supplied config verbatim
  AC33: the user-supplied config is "hardcoded for all" — persists across runs
  AC34: GUI builds with empty persona list (no supply-chain-exec / procurement)
  AC35: delete_persona removes the directory
  AC36: rename_persona moves the directory
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

failures = []
def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        failures.append((name, detail))
        print(f"  FAIL  {name}  --  {detail}")


# === Clean slate: remove any pre-existing personas ===

PERSONAS_DIR = Path("personas").resolve()
if PERSONAS_DIR.exists():
    shutil.rmtree(PERSONAS_DIR, ignore_errors=True)
PERSONAS_DIR.mkdir(parents=True, exist_ok=True)


# === AC30: no personas on a clean dir ===

print("AC30: no hardcoded personas on clean dir")
from app.profile_store import list_personas, ensure_persona, create_persona, delete_persona
check("clean personas/ has no personas", list_personas() == [], f"got {list_personas()}")


# === AC31: ensure_persona creates an EMPTY placeholder (no hardcoded titles) ===

print("\nAC31: ensure_persona creates empty placeholder, no hardcoded data")
p = ensure_persona("test-user-1")
cfg = p.load_config()
check("ensure_persona creates the persona dir", p.exists)
check("ensure_persona config has empty titles (no hardcoded list)",
      cfg.get("titles") == [], f"got titles: {cfg.get('titles')}")
check("ensure_persona config has empty blacklist_companies",
      cfg.get("blacklist_companies") == [])
check("ensure_persona config has empty blacklist_titles",
      cfg.get("blacklist_titles") == [])
check("ensure_persona config has empty experience_levels",
      cfg.get("experience_levels") == [])
# salary is 0, not 120000 (the old hardcoded value)
check("ensure_persona salary_min is 0 (not the old hardcoded 120000)",
      cfg.get("salary_min") == 0, f"got {cfg.get('salary_min')}")


# === AC32: create_persona uses user-supplied config ===

print("\nAC32: create_persona uses user-supplied config verbatim")
user_cfg = {
    "titles": ["Astronaut", "Rocket Scientist"],
    "location": "Mars",
    "salary_min": 1000000,
    "salary_max": 5000000,
    "blacklist_companies": ["NASA"],  # yes really
}
p2 = create_persona("astronaut-jane", config=user_cfg)
loaded = p2.load_config()
check("user-supplied titles persisted",
      loaded["titles"] == ["Astronaut", "Rocket Scientist"])
check("user-supplied location 'Mars' persisted",
      loaded["location"] == "Mars")
check("user-supplied salary_min 1,000,000 persisted",
      loaded["salary_min"] == 1000000)
check("user-supplied blacklist ['NASA'] persisted",
      loaded["blacklist_companies"] == ["NASA"])


# === AC33: user data is "hardcoded for all" — persists across re-loads ===

print("\nAC33: user data persists across re-loads (the 'hardcoded for all' promise)")
# Simulate re-opening the app: drop the in-memory persona and reload from disk
import gc
del p2
gc.collect()
p2_again = ensure_persona("astronaut-jane")  # finds the existing dir
loaded_again = p2_again.load_config()
check("titles persist across reload",
      loaded_again["titles"] == ["Astronaut", "Rocket Scientist"])
check("salary range persists across reload",
      loaded_again["salary_min"] == 1000000 and loaded_again["salary_max"] == 5000000)
check("blacklist persists across reload",
      loaded_again["blacklist_companies"] == ["NASA"])


# === AC34: GUI builds with empty persona list on first run ===

print("\nAC34: GUI builds with empty persona list (no hardcoded supply-chain-exec)")
# Clean again to test "first-run" state
shutil.rmtree(PERSONAS_DIR, ignore_errors=True)
PERSONAS_DIR.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from app.main import PersonaPicker, AppController
from app.lazibot import TheCouch, LaziBrain

controller = AppController(app)
brain = LaziBrain()
win = PersonaPicker(controller, brain)
check("PersonaPicker has empty persona list on first run",
      win.list_widget.count() == 0,
      f"got {win.list_widget.count()} personas")
check("PersonaPicker shows the empty-state hint on first run",
      not win.empty_hint.isHidden())

couch = TheCouch()
check("TheCouch persona_combo shows empty-state on first run",
      couch.persona_combo.count() == 1 and "no personas" in couch.persona_combo.itemText(0).lower())


# === AC35: delete_persona removes the directory ===

print("\nAC35: delete_persona removes a persona's directory")
create_persona("to-delete", config={"titles": ["X"]})
check("to-delete exists before delete", "to-delete" in list_personas())
deleted = delete_persona("to-delete")
check("delete_persona returns True on success", deleted)
check("to-delete no longer in list_personas()", "to-delete" not in list_personas())
check("to-delete directory is gone", not Path("personas/to-delete").exists())


# === AC36: rename_persona moves the directory ===

print("\nAC36: rename_persona moves the directory")
create_persona("old-name", config={"titles": ["Engineer"]})
from app.profile_store import rename_persona
new = rename_persona("old-name", "new-name")
check("rename_persona returns the new Persona", new is not None)
check("new-name directory exists", Path("personas/new-name").exists())
check("old-name directory is gone", not Path("personas/old-name").exists())
check("new-name has the user's titles",
      new.load_config()["titles"] == ["Engineer"])


# === summary ===

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n, d in failures:
        print(f"  - {n}: {d}")
    sys.exit(1)
else:
    print("ALL USER-DRIVEN CHECKS PASS — no hardcoded personas")
    sys.exit(0)
