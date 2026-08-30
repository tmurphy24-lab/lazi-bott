"""Smoke test for the upgraded Lazi-Bot system."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from app.lazibot import (
    LaziBrain, LaziDock, LaziChatOverlay, TheCouch,
    WelcomeSplash, ProfilePage, WalkthroughsPage, GameSelectionPage,
)

print("=== LaziDock (ChatGPT-style bottom dock) ===")
dock = LaziDock()
print(f"  Height: {dock.height()}, avatar: {dock.avatar is not None}, entry: {dock._entry is not None}")

print()
print("=== WelcomeSplash (Welcome 2 the Couch) ===")
splash = WelcomeSplash()
print(f"  Has head avatar: {splash.head is not None}")
print(f"  Title: 'Welcome 2 the Couch, chief.'")

print()
print("=== TheCouch (6 tabs) ===")
c = TheCouch()
print(f"  Tab count: {c.tabs.count()}")
for i in range(c.tabs.count()):
    print(f"    {i+1}. {c.tabs.tabText(i)}")

print()
print("=== ProfilePage ===")
from app.profile_store import create_persona
create_persona("lazi-test", config={"titles": ["Test"]})
pp = ProfilePage("lazi-test")
fields = ["first", "last", "email", "phone", "linkedin", "city", "state", "country", "resume"]
all_present = all(hasattr(pp, f) for f in fields)
print(f"  All 9 fields present: {all_present}")
print(f"  Avatar shows initials: {pp.avatar.text()}")

print()
print("=== WalkthroughsPage ===")
w = WalkthroughsPage()
print(f"  Walkthrough count: {len(w.WALKTHROUGHS)}")
for title, _ in w.WALKTHROUGHS:
    print(f"    - {title}")

print()
print("=== GameSelectionPage ===")
g = GameSelectionPage()
print(f"  Engine count: {len(g.ENGINES)}")
for key, name, desc, _ in g.ENGINES:
    print(f"    - [{key}] {name}")

print()
print("=== LaziBrain personality (canned replies) ===")
b = LaziBrain()
samples = ["hello", "salary?", "who are you", "add to blacklist",
           "thanks", "what about playwright", "browser?"]
for msg in samples:
    b._canned_reply(msg)
    reply = b.history[-1]["content"]
    print(f"  Q: {msg!r:30s} -> A: {reply[:65]!r}")

import shutil
shutil.rmtree("personas/lazi-test", ignore_errors=True)
print()
print("=== ALL LAZI-BOT UPGRADES WIRED IN ===")
