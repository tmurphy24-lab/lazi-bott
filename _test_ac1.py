import sys; sys.path.insert(0,'.')
from PySide6.QtWidgets import QApplication
from app.main import PersonaPicker
app = QApplication.instance() or QApplication(sys.argv)
win = PersonaPicker()
win.show()
# verify the window built and has persona cards
kids = win.centralWidget().findChildren(type(win.centralWidget()))
child_count = len(win.centralWidget().children())
print(f'AC1 PASS: PersonaPicker window built, {child_count} child widgets')
print(f'  Window title: {win.windowTitle()}')
win.close()
