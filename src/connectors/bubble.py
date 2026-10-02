from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QLabel


class Bubble(QLabel):
    def __init__(self, guy, show_ms=8000):
        super().__init__()
        self.guy = guy
        self.show_ms = show_ms
        self.queue = []

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMaximumWidth(240)
        self.setStyleSheet(
            "QLabel { background: #fffdf5; color: #222; border: 2px solid #222;"
            " border-radius: 10px; padding: 6px 10px; font-size: 13px; }"
        )

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.next)

        self.follow_timer = QTimer(self)
        self.follow_timer.setInterval(30)
        self.follow_timer.timeout.connect(self.place)

    def say(self, text, ms=None, now=False):
        message = (text, ms or self.show_ms)
        if now:
            self.queue.insert(0, message)
            self.next()
        else:
            self.queue.append(message)
            if not self.isVisible():
                self.next()

    def next(self):
        if not self.queue:
            self.hide()
            self.follow_timer.stop()
            return

        text, ms = self.queue.pop(0)
        self.setText(text)
        self.adjustSize()
        self.place()
        self.show()
        self.follow_timer.start()
        self.hide_timer.start(ms)

    def place(self):
        top = self.guy.mapToGlobal(QPoint(self.guy.width() // 2, 0))
        self.move(top.x() - self.width() // 2, top.y() - self.height() - 4)

    def mousePressEvent(self, event):
        self.next()
