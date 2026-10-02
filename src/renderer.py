from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from src.paths import ASSETS

SIZE = 72
DEFAULT_FPS = 10
FPS = {
    "idle-2": 6,
    "sleep": 6,
    "wake": 8,
    "walking-left": 7,
    "walking-right": 7,
    "walking-left-plain": 7,
    "walking-right-plain": 7,
}


def lowest_opaque_row(image):
    for y in range(image.height() - 1, -1, -1):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                return y
    return image.height() - 1


def scale_to_guy(image, bottom):
    cropped = image.copy(0, 0, image.width(), bottom + 1)
    return QPixmap.fromImage(cropped).scaledToWidth(SIZE, Qt.TransformationMode.SmoothTransformation)


def load_frames(anim):
    images = [QImage(str(path)) for path in sorted((ASSETS / anim).glob("frame-*.png"))]
    if not images:
        return []

    bottom = max(lowest_opaque_row(image) for image in images)
    return [scale_to_guy(image, bottom) for image in images]


def play_grounded(guy, anim, **kwargs):
    bottom = guy.y() + guy.height()
    guy.play(anim, **kwargs)
    guy.move(guy.x(), bottom - guy.height())


class LittleGuy(QLabel):
    def __init__(self, anim="idle-2"):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.frames = []
        self.index = 0
        self.anim = None
        self.loop = True
        self.then = None
        self.walking = False
        self.walk_resume = None
        self.held = False
        self.sleeping = False
        self.wake_resume = None
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
        at_last_frame = self.index == len(self.frames) - 1
        if not self.loop and at_last_frame:
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
        self.wake_resume = self.walk_resume if self.walking else self.anim
        self.walking = False
        play_grounded(self, "sleep", loop=False)

    def wake(self, instant=False):
        if not self.sleeping:
            return

        if instant:
            self.sleeping = False
            self.play(self.wake_resume)
        elif self.anim != "wake":
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
