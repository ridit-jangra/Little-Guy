import base64
import hashlib
import json
import os
import secrets

import keyring
from keyring.errors import KeyringError
from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QNetworkReply, QNetworkRequest, QTcpServer
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol

from src.connectors.bubble import Bubble
from src.paths import TEMPLATES

SERVER = os.environ.get("LITTLE_GUY_SERVER", "http://localhost:8080").rstrip("/")
CLIENT_PORT = 47831
LOGIN_TIMEOUT_MS = 5 * 60 * 1000
CLOSE_BAD_TOKEN = 4001
FIRST_RETRY_MS = 2000
MAX_RETRY_MS = 5 * 60 * 1000
KEYRING_SERVICE = "little-guy"
KEYRING_USER = "pixl-token"

ICONS = {"approved": "🎉", "changes": "📝", "reviewing": "👀", "ban": "🚫", "restored": "✅", "info": "📦"}

OK_HEADERS = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n"
NOT_FOUND = b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n"


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


def make_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def connected_page():
    return OK_HEADERS + (TEMPLATES / "connected.html").read_bytes()


def code_from_request(data):
    first_line = data.split(b"\r\n", 1)[0]
    try:
        method, target, _ = first_line.decode("ascii").split(" ", 2)
    except (UnicodeDecodeError, ValueError):
        return None

    url = QUrl(target)
    if method != "GET" or url.path() != "/callback":
        return None
    return QUrlQuery(url).queryItemValue("code") or None


def authorized_request(url, token):
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
    return request


class PixlLink(QObject):
    def __init__(self, guy):
        super().__init__(guy)
        self.guy = guy
        self.bubble = Bubble(guy)
        self.net = QNetworkAccessManager(self)
        self.token = load_token()
        self.verifier = None
        self.login_server = None
        self.retry_ms = FIRST_RETRY_MS

        self.login_timeout = QTimer(self)
        self.login_timeout.setSingleShot(True)
        self.login_timeout.timeout.connect(self.stop_login)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.timeout.connect(self.open_socket)

        self.socket = QWebSocket()
        self.socket.textMessageReceived.connect(self.on_message)
        self.socket.connected.connect(self.on_connected)
        self.socket.disconnected.connect(self.on_disconnected)

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
        query = QUrlQuery()
        query.addQueryItem("challenge", make_challenge(self.verifier))
        url = QUrl(f"{SERVER}/login")
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
        connection = self.login_server.nextPendingConnection()
        connection.setParent(self)
        connection.disconnected.connect(connection.deleteLater)
        connection.readyRead.connect(lambda: self.on_login_request(connection))

    def on_login_request(self, connection):
        data = bytes(connection.readAll())
        if b"\r\n" not in data:
            return

        code = code_from_request(data)
        if not code:
            connection.write(NOT_FOUND)
            connection.disconnectFromHost()
            return

        connection.write(connected_page())
        connection.disconnectFromHost()

        verifier = self.verifier
        self.stop_login()
        self.redeem(code, verifier)

    def redeem(self, code, verifier):
        request = QNetworkRequest(QUrl(f"{SERVER}/token"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        body = json.dumps({"code": code, "verifier": verifier}).encode()
        reply = self.net.post(request, QByteArray(body))
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

        self.token = token
        save_token(token)
        self.retry_ms = FIRST_RETRY_MS
        self.bubble.say("Connected to Pixl!", ms=3000, now=True)
        self.open_socket()

    def disconnect_account(self):
        if self.token:
            request = authorized_request(f"{SERVER}/logout", self.token)
            reply = self.net.post(request, QByteArray())
            reply.finished.connect(reply.deleteLater)

        self.forget()
        self.bubble.say("Disconnected from Pixl.", ms=3000, now=True)

    def forget(self):
        self.token = None
        save_token(None)
        self.reconnect_timer.stop()
        self.socket.close()

    def open_socket(self):
        if not self.token:
            return
        url = SERVER.replace("http", "ws", 1) + "/ws"
        self.socket.open(authorized_request(url, self.token))

    def on_connected(self):
        self.retry_ms = FIRST_RETRY_MS

    def on_disconnected(self):
        if self.socket.closeCode() == QWebSocketProtocol.CloseCode(CLOSE_BAD_TOKEN):
            self.forget()
            self.bubble.say("My Pixl login expired. Right-click me to connect again.")
            return

        if self.token:
            self.reconnect_timer.start(self.retry_ms)
            self.retry_ms = min(self.retry_ms * 2, MAX_RETRY_MS)

    def on_message(self, text):
        try:
            event = json.loads(text)
        except ValueError:
            return

        title = str(event.get("title") or "")
        if not title:
            return

        self.guy.wake()
        icon = ICONS.get(event.get("kind"), "📦")
        message = f"{icon} {title}"
        project = event.get("project")
        if project:
            message += f"\n{project}"
        self.bubble.say(message)


def enable_pixl(guy):
    return PixlLink(guy)
