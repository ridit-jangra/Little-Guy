import base64
import hashlib
import json
import os
import secrets

import keyring
from keyring.errors import KeyringError
from PySide6.QtCore import QByteArray, QObject, QPoint, Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QNetworkReply, QNetworkRequest, QTcpServer
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol
from PySide6.QtWidgets import QLabel

SERVER = os.environ.get("LITTLE_GUY_SERVER", "http://localhost:8080").rstrip("/")
CLIENT_PORT = 47831
LOGIN_TIMEOUT_MS = 5 * 60 * 1000
CLOSE_BAD_TOKEN = 4001
KEYRING_SERVICE = "little-guy"
KEYRING_USER = "pixl-token"

ICONS = {"approved": "🎉", "changes": "📝", "reviewing": "👀", "ban": "🚫", "restored": "✅", "info": "📦"}

DONE_PAGE = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n"
    b"<!doctype html><title>Little Guy</title>"
    b'<body style="font-family:sans-serif;text-align:center;margin-top:4rem">'
    b"<h2>Little Guy is connected!</h2><p>You can close this tab.</p></body>"
)


def load_token():
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except KeyringError:
        return None


def save_token(token):
    try:
        if token:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
        else:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except KeyringError:
        pass


class Bubble(QLabel):

    def __init__(self, guy, show_ms=8000):
        super().__init__()
        self.guy = guy
        self.show_ms = show_ms
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMaximumWidth(240)
        self.setStyleSheet(
            "QLabel { background: #fffdf5; color: #222; border: 2px solid #222;"
            " border-radius: 10px; padding: 6px 10px; font-size: 13px; }"
        )
        self.queue = []
        self.hide_timer = QTimer(self, singleShot=True, timeout=self.next)
        self.follow = QTimer(self, interval=30, timeout=self.place)

    def say(self, text, ms=None, now=False):
        item = (text, ms or self.show_ms)
        if now:
            self.queue.insert(0, item)
            self.next()
            return
        self.queue.append(item)
        if not self.isVisible():
            self.next()

    def next(self):
        if not self.queue:
            self.hide()
            self.follow.stop()
            return
        text, ms = self.queue.pop(0)
        self.setText(text)
        self.adjustSize()
        self.place()
        self.show()
        self.follow.start()
        self.hide_timer.start(ms)

    def place(self):
        top = self.guy.mapToGlobal(QPoint(self.guy.width() // 2, 0))
        self.move(top.x() - self.width() // 2, top.y() - self.height() - 4)

    def mousePressEvent(self, event):
        self.next()


class PixlLink(QObject):
    def __init__(self, guy):
        super().__init__(guy)
        self.guy = guy
        self.bubble = Bubble(guy)
        self.net = QNetworkAccessManager(self)
        self.token = load_token()
        self.verifier = None
        self.login_server = None
        self.login_timeout = QTimer(self, singleShot=True, timeout=self.stop_login)
        self.retry_ms = 2000
        self.reconnect = QTimer(self, singleShot=True, timeout=self.open_socket)

        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self.on_message)
        self.ws.connected.connect(self.on_connected)
        self.ws.disconnected.connect(self.on_disconnected)

        guy.menu_hooks.append(self.add_menu_items)
        if self.token:
            self.open_socket()

    def add_menu_items(self, menu):
        if self.token:
            menu.addAction("Disconnect Pixl", self.disconnect_account)
        else:
            menu.addAction("Connect to Pixl", self.connect_account)


    def connect_account(self):
        self.stop_login()
        self.login_server = QTcpServer(self)
        if not self.login_server.listen(QHostAddress.SpecialAddress.LocalHost, CLIENT_PORT):
            self.login_server = None
            self.bubble.say(f"Couldn't start the login (port {CLIENT_PORT} is busy).", now=True)
            return
        self.login_server.newConnection.connect(self.on_login_connection)
        self.verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        url = QUrl(f"{SERVER}/login")
        query = QUrlQuery()
        query.addQueryItem("challenge", challenge)
        url.setQuery(query)
        QDesktopServices.openUrl(url)
        self.login_timeout.start(LOGIN_TIMEOUT_MS)
        self.bubble.say("Finish logging in in your browser!", ms=LOGIN_TIMEOUT_MS, now=True)

    def stop_login(self):
        if self.login_timeout.isActive() and not self.token:
            self.bubble.next()
        self.login_timeout.stop()
        if self.login_server:
            self.login_server.close()
            self.login_server.deleteLater()
            self.login_server = None

    def on_login_connection(self):
        sock = self.login_server.nextPendingConnection()
        sock.setParent(self)
        sock.disconnected.connect(sock.deleteLater)
        sock.readyRead.connect(lambda: self.on_login_request(sock))

    def on_login_request(self, sock):
        data = bytes(sock.readAll())
        if b"\r\n" not in data:
            return
        try:
            method, target, _ = data.split(b"\r\n", 1)[0].decode("ascii").split(" ", 2)
        except (UnicodeDecodeError, ValueError):
            sock.close()
            return
        url = QUrl(target)
        code = QUrlQuery(url).queryItemValue("code")
        if method != "GET" or url.path() != "/callback" or not code:
            sock.write(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
            sock.disconnectFromHost()
            return
        sock.write(DONE_PAGE)
        sock.disconnectFromHost()
        verifier = self.verifier
        self.stop_login()
        self.redeem(code, verifier)

    def redeem(self, code, verifier):
        req = QNetworkRequest(QUrl(f"{SERVER}/token"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        reply = self.net.post(req, QByteArray(json.dumps({"code": code, "verifier": verifier}).encode()))
        reply.finished.connect(lambda: self.on_token(reply))

    def on_token(self, reply):
        reply.deleteLater()
        token = None
        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                token = json.loads(bytes(reply.readAll())).get("token")
            except ValueError:
                pass
        if not token:
            self.bubble.say("Login didn't work, try again?", now=True)
            return
        self.bubble.say("Connected to Pixl!", ms=3000, now=True)
        self.token = token
        save_token(token)
        self.retry_ms = 2000
        self.open_socket()

    def disconnect_account(self):
        if self.token:
            req = QNetworkRequest(QUrl(f"{SERVER}/logout"))
            req.setRawHeader(b"Authorization", f"Bearer {self.token}".encode())
            reply = self.net.post(req, QByteArray())
            reply.finished.connect(reply.deleteLater)
        self.forget()
        self.bubble.say("Disconnected from Pixl.", ms=3000, now=True)

    def forget(self):
        self.token = None
        save_token(None)
        self.reconnect.stop()
        self.ws.close()


    def open_socket(self):
        if not self.token:
            return
        ws_url = SERVER.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"
        req = QNetworkRequest(QUrl(ws_url))
        req.setRawHeader(b"Authorization", f"Bearer {self.token}".encode())
        self.ws.open(req)

    def on_connected(self):
        self.retry_ms = 2000

    def on_disconnected(self):
        if self.ws.closeCode() == QWebSocketProtocol.CloseCode(CLOSE_BAD_TOKEN):
            self.forget()
            self.bubble.say("My Pixl login expired. Right-click me to connect again.")
            return
        if self.token:
            self.reconnect.start(self.retry_ms)
            self.retry_ms = min(self.retry_ms * 2, 5 * 60 * 1000)

    def on_message(self, text):
        try:
            event = json.loads(text)
        except ValueError:
            return
        title = str(event.get("title") or "")
        if not title:
            return
        self.guy.wake()
        project = event.get("project")
        line = f"{ICONS.get(event.get('kind'), '📦')} {title}"
        self.bubble.say(f"{line}\n{project}" if project else line)


def enable_pixl(guy):
    return PixlLink(guy)
