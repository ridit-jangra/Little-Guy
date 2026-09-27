import math
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu

anims = ["idle", "idle-2", "walk-left", "walk-right", "jump"]

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 72
FPS = {"idle-2": 6}  # anything not listed plays at DEFAULT_FPS
DEFAULT_FPS = 10


def lowest_opaque_row(image):
    for y in range(image.height() - 1, -1, -1):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                return y
    return image.height() - 1


def load_frames(anim):
    images = [QImage(str(p)) for p in sorted((ASSETS / anim).glob("frame-*.png"))]
    if not images:
        return []
    # crop the shared transparent strip at the bottom so his feet sit on the taskbar
    bottom = max(lowest_opaque_row(img) for img in images)
    return [
        QPixmap.fromImage(img.copy(0, 0, img.width(), bottom + 1)).scaledToWidth(
            SIZE, Qt.TransformationMode.SmoothTransformation
        )
        for img in images
    ]


class LittleGuy(QLabel):
    def __init__(self, anim="idle-2"):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.frames = []
        self.index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.play(anim)

        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 50, area.bottom() - self.height() + 1)

    def play(self, anim):
        frames = load_frames(anim)
        if not frames:
            return
        self.frames = frames
        self.index = 0
        self.setPixmap(self.frames[0])
        self.resize(self.frames[0].size())
        self.timer.start(1000 // FPS.get(anim, DEFAULT_FPS))

    def next_frame(self):
        self.index = (self.index + 1) % len(self.frames)
        self.setPixmap(self.frames[self.index])

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Quit", QApplication.quit)
        menu.exec(event.globalPos())


def cycle_idles(guy, anims=("idle-2", "idle"), every_loops=5):
    """Alternate between idle animations after each one plays every_loops full loops."""
    state = {"current": 0, "loops": 0}

    def on_frame():
        # index just wrapped to 0: one full loop finished
        if guy.index != 0:
            return
        state["loops"] += 1
        if state["loops"] < every_loops:
            return
        state["loops"] = 0
        state["current"] = (state["current"] + 1) % len(anims)
        bottom = guy.y() + guy.height()
        guy.play(anims[state["current"]])
        guy.move(guy.x(), bottom - guy.height())  # keep his feet on the taskbar

    guy.timer.timeout.connect(on_frame)


# clockwise from pointing right (screen y grows downward)
SIDES = ["right", "bottom-right", "bottom", "bottom-left", "left", "top-left", "top", "top-right"]


def load_sides():
    names = SIDES + ["center"]
    images = {name: QImage(str(ASSETS / "sides" / f"{name}.png")) for name in names}
    bottom = max(lowest_opaque_row(img) for img in images.values())
    return {
        name: QPixmap.fromImage(img.copy(0, 0, img.width(), bottom + 1)).scaledToWidth(
            SIZE, Qt.TransformationMode.SmoothTransformation
        )
        for name, img in images.items()
    }


def follow_cursor(guy, still_ms=1500, dead_zone=40):
    """While the cursor moves, pause the idle animation and look toward it."""
    sides = load_sides()
    state = {"last": QCursor.pos(), "still_for": 0, "following": False, "side": None}
    poll_ms = 30

    def look(side):
        if side != state["side"]:
            state["side"] = side
            guy.setPixmap(sides[side])

    def poll():
        pos = QCursor.pos()
        if pos == state["last"]:
            state["still_for"] += poll_ms
            if state["following"] and state["still_for"] >= still_ms:
                # cursor stopped: go back to the idle animation where it paused
                state["following"] = False
                state["side"] = None
                guy.setPixmap(guy.frames[guy.index])
                guy.timer.start()
            return

        state["last"] = pos
        state["still_for"] = 0
        if not state["following"]:
            state["following"] = True
            guy.timer.stop()

        eyes = guy.mapToGlobal(QPoint(guy.width() // 2, guy.height() // 3))
        dx, dy = pos.x() - eyes.x(), pos.y() - eyes.y()
        if math.hypot(dx, dy) < dead_zone:
            look("center")
        else:
            look(SIDES[round(math.degrees(math.atan2(dy, dx)) / 45) % 8])

    poller = QTimer(guy)
    poller.timeout.connect(poll)
    poller.start(poll_ms)
    return poller


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    guy = LittleGuy()
    cycle_idles(guy)
    follow_cursor(guy)
    guy.show()
    sys.exit(app.exec())
