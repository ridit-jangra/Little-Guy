import sys
import signal
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication

from src.renderer import LittleGuy

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_animation.py <animation>")
        sys.exit(1)

    anim = sys.argv[1]

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    guy = LittleGuy()
    guy.play(anim)
    guy.show()
    sys.exit(app.exec())
