import signal
import sys

from PySide6.QtWidgets import QApplication

from src.connectors.pixl import enable_pixl
from src.renderer import LittleGuy, cycle_idles, follow_cursor, nap, wander

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    guy = LittleGuy()
    guy.play("spawn", False)
    cycle_idles(guy)
    follow_cursor(guy)
    wander(guy)
    nap(guy)
    link = enable_pixl(guy)
    guy.show()
    sys.exit(app.exec())
