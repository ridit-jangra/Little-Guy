import math
import random
import signal
import time
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from pixl_link import enable_pixl

anims = ["idle", "idle-2", "walking-left", "walking-right", "jump"]

SIDES = ["right", "bottom-right", "bottom", "bottom-left", "left", "top-left", "top", "top-right"]
ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 72
FPS = {"idle-2": 6, "sleep": 6, "wake": 8, "walking-left": 7, "walking-right": 7, "walking-left-plain": 7, "walking-right-plain": 7}
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
        self.anim = None
        self.walking = False
        self.held = False
        self.sleeping = False
        self.wake_resume = None
        self.loop = True
        self.then = None
        self.walk_resume = None
        self.menu_hooks = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.play(anim)

        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 50, area.bottom() - self.height() + 1)

    def play(self, anim, loop=True, then=None):
        frames = load_frames(anim)
        if not frames:
            return
        self.frames = frames
        self.index = 0
        self.anim = anim
        self.loop = loop
        self.then = then
        self.setPixmap(self.frames[0])
        self.resize(self.frames[0].size())
        self.timer.start(1000 // FPS.get(anim, DEFAULT_FPS))

    def next_frame(self):
        if not self.loop and self.index == len(self.frames) - 1:
            self.timer.stop()
            then, self.then = self.then, None
            if then:
                QTimer.singleShot(0, then)
            return
        self.index = (self.index + 1) % len(self.frames)
        self.setPixmap(self.frames[self.index])

    def sleep(self):
        if self.sleeping:
            return
        self.sleeping = True
        self.wake_resume = self.anim
        play_grounded(self, "sleep", loop=False)

    def wake(self, instant=False):
        if not self.sleeping:
            return
        if instant:
            self.sleeping = False
            self.play(self.wake_resume)
            return
        if self.anim != "wake":
            play_grounded(self, "wake", loop=False, then=self.woke)

    def woke(self):
        self.sleeping = False
        play_grounded(self, self.wake_resume)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for hook in self.menu_hooks:
            hook(menu)
        menu.addAction("Quit", QApplication.quit)
        menu.exec(event.globalPos())


def cycle_idles(guy, anims=("idle-2", "idle"), every_loops=5):
    state = {"current": 0, "loops": 0}

    def on_frame():
        if guy.walking or guy.sleeping or guy.index != 0:
            return
        state["loops"] += 1
        if state["loops"] < every_loops:
            return
        state["loops"] = 0
        state["current"] = (state["current"] + 1) % len(anims)
        bottom = guy.y() + guy.height()
        guy.play(anims[state["current"]])
        guy.move(guy.x(), bottom - guy.height())

    guy.timer.timeout.connect(on_frame)

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
    sides = load_sides()
    state = {"last": QCursor.pos(), "still_for": 0, "following": False, "side": None}
    poll_ms = 30

    def look(side):
        if side != state["side"]:
            state["side"] = side
            guy.setPixmap(sides[side])

    def poll():
        pos = QCursor.pos()
        if guy.walking or guy.held or guy.sleeping:
            state["last"] = pos
            state["following"] = False
            state["side"] = None
            return
        if pos == state["last"]:
            state["still_for"] += poll_ms
            if state["following"] and state["still_for"] >= still_ms:
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


def play_grounded(guy, anim, **kwargs):
    bottom = guy.y() + guy.height()
    guy.play(anim, **kwargs)
    guy.move(guy.x(), bottom - guy.height())


def wander(guy, speed=60, rest_s=(1, 3), min_walk=120, wave_chance=0.25):
    state = {"x": 0.0, "target": 0.0, "last": 0.0, "resume": None, "dir": "left"}
    waving = {d: load_frames(f"walking-{d}") for d in ("left", "right")}
    plain = {d: load_frames(f"walking-{d}-plain") for d in ("left", "right")}
    mover = QTimer(guy)

    def on_frame():
        if guy.walking and guy.index == 0:
            d = state["dir"]
            guy.frames = waving[d] if random.random() < wave_chance else plain[d]

    def rest():
        QTimer.singleShot(int(random.uniform(*rest_s) * 1000), start_walk)

    def start_walk():
        if guy.sleeping:
            rest()
            return
        if guy.held:
            QTimer.singleShot(500, start_walk)
            return
        area = QApplication.primaryScreen().availableGeometry()
        lo, hi = area.left(), area.right() - guy.width()
        spots = [x for x in (random.uniform(lo, hi) for _ in range(20)) if abs(x - guy.x()) >= min_walk]
        target = spots[0] if spots else (lo if guy.x() - lo > hi - guy.x() else hi)

        direction = "right" if target > guy.x() else "left"
        state.update(x=float(guy.x()), target=target, last=time.monotonic(), resume=guy.anim, dir=direction)
        guy.walking = True
        guy.walk_resume = guy.anim
        play_grounded(guy, f"walking-{direction}-plain")
        mover.start(16)

    def step():
        if not guy.walking:
            mover.stop()
            rest()
            return
        now = time.monotonic()
        dist = speed * (now - state["last"])
        state["last"] = now
        gap = state["target"] - state["x"]
        if abs(gap) <= dist:
            guy.move(round(state["target"]), guy.y())
            mover.stop()
            guy.walking = False
            play_grounded(guy, state["resume"])
            rest()
            return
        state["x"] += math.copysign(dist, gap)
        guy.move(round(state["x"]), guy.y())

    mover.timeout.connect(step)
    guy.timer.timeout.connect(on_frame)
    rest()
    return mover


def nap(guy, after_s=60, poll_ms=250):
    state = {"last": QCursor.pos(), "still_since": time.monotonic()}

    def poll():
        pos = QCursor.pos()
        now = time.monotonic()
        if pos != state["last"]:
            state["last"], state["still_since"] = pos, now
            guy.wake()
        elif not (guy.sleeping or guy.walking or guy.held) and now - state["still_since"] >= after_s:
            guy.sleep()

    poller = QTimer(guy)
    poller.timeout.connect(poll)
    poller.start(poll_ms)
    return poller


class Dragger(QObject):
    GRAVITY = 2600
    BOUNCE = 0.25
    MIN_BOUNCE = 500

    def __init__(self, guy):
        super().__init__(guy)
        self.guy = guy
        self.pose = load_sides()["bottom"]
        self.grab = QPoint()
        self.y = 0.0
        self.vy = 0.0
        self.last = 0.0
        self.faller = QTimer(self)
        self.faller.timeout.connect(self.fall)
        guy.installEventFilter(self)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.pick_up(event.globalPosition().toPoint())
            return True
        if t == QEvent.Type.MouseMove and self.guy.held and not self.faller.isActive():
            self.guy.move(event.globalPosition().toPoint() - self.grab)
            return True
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton and self.guy.held:
            self.drop()
            return True
        return False

    def pick_up(self, pos):
        guy = self.guy
        self.faller.stop()
        guy.wake(instant=True)
        if guy.walking:
            guy.walking = False
            guy.play(guy.walk_resume)
        guy.held = True
        guy.timer.stop()
        guy.setPixmap(self.pose)
        guy.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.grab = pos - guy.pos()

    def drop(self):
        self.guy.unsetCursor()
        area = QApplication.primaryScreen().availableGeometry()
        x = min(max(self.guy.x(), area.left()), area.right() - self.guy.width())
        self.guy.move(x, self.guy.y())
        self.y, self.vy, self.last = float(self.guy.y()), 0.0, time.monotonic()
        self.faller.start(16)

    def fall(self):
        guy = self.guy
        now = time.monotonic()
        dt, self.last = now - self.last, now
        ground = QApplication.primaryScreen().availableGeometry().bottom() + 1 - guy.height()
        self.vy += self.GRAVITY * dt
        self.y += self.vy * dt
        if self.y >= ground:
            self.y = ground
            if self.vy > self.MIN_BOUNCE:
                self.vy = -self.vy * self.BOUNCE
            else:
                self.faller.stop()
                guy.move(guy.x(), round(ground))
                guy.held = False
                guy.setPixmap(guy.frames[guy.index])
                guy.timer.start()
                return
        guy.move(guy.x(), round(self.y))


def enable_drag(guy):
    return Dragger(guy)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    guy = LittleGuy()
    cycle_idles(guy)
    follow_cursor(guy)
    wander(guy)
    nap(guy)
    enable_drag(guy)
    link = enable_pixl(guy)
    guy.show()
    sys.exit(app.exec())
