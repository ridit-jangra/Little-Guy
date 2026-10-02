import math

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QCursor, QImage, QPixmap

from src.paths import ASSETS
from src.renderer import SIZE, lowest_opaque_row, scale_to_guy

SIDES = ["right", "bottom-right", "bottom", "bottom-left", "left", "top-left", "top", "top-right"]
POLL_MS = 30


def load_sides():
    images = {}
    for name in SIDES + ["center"]:
        images[name] = QImage(str(ASSETS / "sides" / f"{name}.png"))

    bottom = max(lowest_opaque_row(image) for image in images.values())
    return {name: scale_to_guy(image, bottom) for name, image in images.items()}


class CursorFollower:
    def __init__(self, guy, still_ms=1500, dead_zone=40):
        self.guy = guy
        self.still_ms = still_ms
        self.dead_zone = dead_zone
        self.sides = load_sides()

        self.last_pos = QCursor.pos()
        self.still_for = 0
        self.following = False
        self.side = None

        self.timer = QTimer(guy)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)

    def stop_following(self):
        self.following = False
        self.side = None

    def look(self, side):
        if side != self.side:
            self.side = side
            self.guy.setPixmap(self.sides[side])

    def poll(self):
        pos = QCursor.pos()

        if self.guy.walking or self.guy.held or self.guy.sleeping:
            self.last_pos = pos
            self.stop_following()
            return

        if pos == self.last_pos:
            self.still_for += POLL_MS
            if self.following and self.still_for >= self.still_ms:
                self.stop_following()
                self.guy.setPixmap(self.guy.frames[self.guy.index])
                self.guy.timer.start()
            return

        self.last_pos = pos
        self.still_for = 0
        if not self.following:
            self.following = True
            self.guy.timer.stop()

        eyes = self.guy.mapToGlobal(QPoint(self.guy.width() // 2, self.guy.height() // 3))
        dx = pos.x() - eyes.x()
        dy = pos.y() - eyes.y()

        if math.hypot(dx, dy) < self.dead_zone:
            self.look("center")
        else:
            angle = math.degrees(math.atan2(dy, dx))
            self.look(SIDES[round(angle / 45) % 8])
