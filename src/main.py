import signal
import sys

from PySide6.QtWidgets import QApplication

from src.brain import Brain
from src.connectors.pixl import enable_pixl
from src.cursor import CursorFollower
from src.renderer import LittleGuy

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)

    guy = LittleGuy()
    brain = Brain(guy)
    follower = CursorFollower(guy)
    pixl = enable_pixl(guy)

    guy.play("spawn", False, then=brain.finish)
    guy.show()
    sys.exit(app.exec())
