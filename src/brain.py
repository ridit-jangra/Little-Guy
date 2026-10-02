import math
import random
import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from src.renderer import play_grounded

ENERGY_DRAIN = 0.001
ENERGY_GAIN = 0.02
BOREDOM_GAIN = 0.02
WALK_SPEED = 60
MIN_WALK = 120
WAVE_CHANCE = 0.25
CHOICE_TEMPERATURE = 0.3

QUICK_NAP_SECONDS = 30
LONG_NAP_SECONDS = 90

COOLDOWNS = {"idle": 0, "walk": 5, "nap": 300}


def is_night(hour):
    return hour >= 22 or hour < 6


def is_afternoon(hour):
    return 13 <= hour < 16


def drain_multiplier(hour):
    if is_night(hour):
        return 2.0
    if is_afternoon(hour):
        return 1.5
    return 1.0


class Brain:
    def __init__(self, guy):
        self.guy = guy
        self.energy = 1.0
        self.boredom = 0.0
        self.busy = True
        self.last_used = {}
        self.wake_at = 0
        self.last_cursor = QCursor.pos()

        self.walk_x = 0.0
        self.walk_target = 0.0
        self.walk_last = 0.0

        self.thinker = QTimer(guy)
        self.thinker.timeout.connect(self.think)
        self.thinker.start(1000)

        self.mover = QTimer(guy)
        self.mover.timeout.connect(self.walk_step)

    def finish(self):
        self.busy = False
        play_grounded(self.guy, random.choice(["idle", "idle-2"]))

    def think(self):
        hour = datetime.now().hour
        cursor = QCursor.pos()
        cursor_moved = cursor != self.last_cursor
        self.last_cursor = cursor

        if self.guy.sleeping:
            self.energy = min(1.0, self.energy + ENERGY_GAIN)
            if cursor_moved or time.monotonic() >= self.wake_at:
                self.guy.wake()
            return

        self.energy = max(0.0, self.energy - ENERGY_DRAIN * drain_multiplier(hour))

        if self.busy or self.guy.held:
            return

        self.boredom = min(1.0, self.boredom + BOREDOM_GAIN)
        action = self.choose_action(hour)
        self.last_used[action] = time.monotonic()

        if action == "idle":
            self.start_idle()
        elif action == "walk":
            self.start_walk()
        elif action == "nap":
            self.start_nap(hour)

    def scores(self, hour):
        scores = {
            "idle": 0.3,
            "walk": 0.2 + self.boredom,
            "nap": 0.0,
        }

        if self.energy < 0.8:
            scores["nap"] = (1 - self.energy) ** 2 * 1.5
            if is_afternoon(hour):
                scores["nap"] += 0.4

        now = time.monotonic()
        for action, cooldown in COOLDOWNS.items():
            if now - self.last_used.get(action, 0) < cooldown:
                scores[action] *= 0.2

        return scores

    def choose_action(self, hour):
        scores = self.scores(hour)
        actions = [action for action in scores if scores[action] > 0]
        weights = [math.exp(scores[a] / CHOICE_TEMPERATURE) for a in actions]
        return random.choices(actions, weights)[0]

    def start_idle(self):
        self.busy = True
        play_grounded(self.guy, random.choice(["idle", "idle-2"]))
        QTimer.singleShot(random.randint(4000, 8000), self.finish)

    def start_nap(self, hour):
        self.busy = True
        if is_afternoon(hour):
            seconds = QUICK_NAP_SECONDS
        else:
            seconds = LONG_NAP_SECONDS
        self.wake_at = time.monotonic() + seconds
        play_grounded(self.guy, "yawn", loop=False, then=self.fall_asleep)

    def fall_asleep(self):
        self.guy.anim = "idle-2"
        self.guy.sleep()
        self.busy = False

    def start_walk(self):
        self.busy = True
        self.boredom = 0.0

        area = QApplication.primaryScreen().availableGeometry()
        left = area.left()
        right = area.right() - self.guy.width()

        target = random.uniform(left, right)
        if abs(target - self.guy.x()) < MIN_WALK:
            if self.guy.x() - left > right - self.guy.x():
                target = left
            else:
                target = right

        if target > self.guy.x():
            direction = "right"
        else:
            direction = "left"

        if random.random() < WAVE_CHANCE:
            anim = f"walking-{direction}"
        else:
            anim = f"walking-{direction}-plain"

        self.walk_x = float(self.guy.x())
        self.walk_target = target
        self.walk_last = time.monotonic()
        self.guy.walking = True
        self.guy.walk_resume = self.guy.anim
        play_grounded(self.guy, anim)
        self.mover.start(16)

    def walk_step(self):
        now = time.monotonic()
        distance = WALK_SPEED * (now - self.walk_last)
        self.walk_last = now
        gap = self.walk_target - self.walk_x

        if abs(gap) <= distance:
            self.guy.move(round(self.walk_target), self.guy.y())
            self.mover.stop()
            self.guy.walking = False
            self.finish()
            return

        self.walk_x += math.copysign(distance, gap)
        self.guy.move(round(self.walk_x), self.guy.y())
