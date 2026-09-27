import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

HCA_BASE = "https://auth.hackclub.com"
HCA_CLIENT_ID = os.environ["HCA_CLIENT_ID"]
HCA_CLIENT_SECRET = os.environ["HCA_CLIENT_SECRET"]
HCA_SCOPES = os.environ.get("HCA_SCOPES", "openid slack_id")
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")
PIXL_API_KEYS = [k.strip().encode() for k in os.environ["PIXL_API_KEY"].split(",") if k.strip()]
PORT = int(os.environ.get("PORT", "8080"))
DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).resolve().parent / "littleguy.db"))

CLIENT_PORT = 47831
LOGIN_TTL = 10 * 60
CODE_TTL = 60
TOKEN_TTL = 90 * 24 * 3600
QUEUE_DAYS = 7
QUEUE_MAX = 50
MAX_PENDING = 10_000
WEBHOOK_SKEW = 300
CLOSE_BAD_TOKEN = 4001

CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
SLACK_ID_RE = re.compile(r"^[A-Z0-9]{2,32}$")
KINDS = {"approved", "changes", "reviewing", "ban", "restored", "info"}

pending_logins: dict[str, tuple[str, float]] = {}
codes: dict[str, tuple[str, str, float]] = {}
sockets: dict[str, set[web.WebSocketResponse]] = {}


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def open_db() -> sqlite3.Connection:
    os.umask(0o077)
    conn = sqlite3.connect(DB_PATH)
    os.chmod(DB_PATH, 0o600)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            hash TEXT PRIMARY KEY,
            slack_id TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slack_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS queue_slack ON queue (slack_id, id);
        CREATE TABLE IF NOT EXISTS seen (
            event_id TEXT PRIMARY KEY,
            at INTEGER NOT NULL
        );
        """
    )
    return conn


db = open_db()


def prune(now: float):
    for store in (pending_logins, codes):
        for k in [k for k, v in store.items() if v[-1] <= now]:
            del store[k]
    db.execute("DELETE FROM tokens WHERE expires_at <= ?", (int(now),))
    db.execute("DELETE FROM queue WHERE created_at <= ?", (int(now) - QUEUE_DAYS * 86400,))
    db.execute("DELETE FROM seen WHERE at <= ?", (int(now) - 86400,))
    db.commit()


def page(title: str, message: str, status: int = 200) -> web.Response:
    html = (
        "<!doctype html><meta charset=utf-8><title>Little Guy</title>"
        '<body style="font-family:sans-serif;text-align:center;margin-top:4rem">'
        f"<h2>{title}</h2><p>{message}</p></body>"
    )
    return web.Response(text=html, content_type="text/html", status=status)


def bearer(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    return header[7:] if header.startswith("Bearer ") else None


def token_owner(token: str | None) -> str | None:
    if not token:
        return None
    row = db.execute(
        "SELECT slack_id FROM tokens WHERE hash = ? AND expires_at > ?",
        (sha256_hex(token), int(time.time())),
    ).fetchone()
    return row[0] if row else None


async def login(request: web.Request) -> web.Response:
    challenge = request.query.get("challenge", "")
    if not CHALLENGE_RE.match(challenge):
        return page("Login failed", "Start the login from Little Guy.", 400)
    now = time.time()
    prune(now)
    if len(pending_logins) >= MAX_PENDING:
        return page("Too many logins", "Try again in a few minutes.", 503)
    state = secrets.token_urlsafe(24)
    pending_logins[state] = (challenge, now + LOGIN_TTL)
    query = urlencode(
        {
            "client_id": HCA_CLIENT_ID,
            "redirect_uri": f"{PUBLIC_URL}/callback",
            "response_type": "code",
            "scope": HCA_SCOPES,
            "state": state,
        }
    )
    raise web.HTTPFound(f"{HCA_BASE}/oauth/authorize?{query}")


async def callback(request: web.Request) -> web.Response:
    pending = pending_logins.pop(request.query.get("state", ""), None)
    hca_code = request.query.get("code", "")
    if not pending or not hca_code or pending[1] <= time.time():
        return page("Login expired", "Start the login again from Little Guy.", 400)
    challenge = pending[0]

    session: aiohttp.ClientSession = request.app["http"]
    async with session.post(
        f"{HCA_BASE}/oauth/token",
        json={
            "client_id": HCA_CLIENT_ID,
            "client_secret": HCA_CLIENT_SECRET,
            "redirect_uri": f"{PUBLIC_URL}/callback",
            "code": hca_code,
            "grant_type": "authorization_code",
        },
    ) as res:
        if res.status != 200:
            print(f"[login] HCA token exchange failed: {res.status}")
            return page("Login failed", "Hack Club Auth didn't accept the login. Try again in a minute.", 502)
        access_token = (await res.json()).get("access_token", "")

    async with session.get(
        f"{HCA_BASE}/api/v1/me", headers={"Authorization": f"Bearer {access_token}"}
    ) as res:
        if res.status != 200:
            print(f"[login] HCA /me failed: {res.status}")
            return page("Login failed", "Couldn't read your Hack Club account.", 502)
        me = await res.json()

    slack_id = ((me.get("identity") or {}).get("slack_id") or "").strip()
    if not SLACK_ID_RE.match(slack_id):
        return page("No Slack account", "Link Slack to your Hack Club account, then try again.", 400)

    code = secrets.token_urlsafe(32)
    codes[code] = (slack_id, challenge, time.time() + CODE_TTL)
    raise web.HTTPFound(f"http://127.0.0.1:{CLIENT_PORT}/callback?{urlencode({'code': code})}")


async def token(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        code, verifier = str(body["code"]), str(body["verifier"])
    except (ValueError, KeyError, TypeError):
        return web.json_response({"ok": False}, status=400)
    entry = codes.pop(code, None)
    if not entry or entry[2] <= time.time():
        return web.json_response({"ok": False}, status=400)
    slack_id, challenge, _ = entry
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    if not hmac.compare_digest(expected, challenge):
        return web.json_response({"ok": False}, status=400)

    session_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + TOKEN_TTL
    db.execute(
        "INSERT INTO tokens (hash, slack_id, expires_at) VALUES (?, ?, ?)",
        (sha256_hex(session_token), slack_id, expires_at),
    )
    db.commit()
    return web.json_response({"ok": True, "token": session_token, "expires_at": expires_at})


async def logout(request: web.Request) -> web.Response:
    tok = bearer(request)
    if tok:
        db.execute("DELETE FROM tokens WHERE hash = ?", (sha256_hex(tok),))
        db.commit()
    return web.json_response({"ok": True})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    slack_id = token_owner(bearer(request))
    if not slack_id:
        await ws.close(code=CLOSE_BAD_TOKEN, message=b"bad token")
        return ws

    sockets.setdefault(slack_id, set()).add(ws)
    try:
        rows = db.execute(
            "SELECT id, payload FROM queue WHERE slack_id = ? ORDER BY id", (slack_id,)
        ).fetchall()
        for row_id, payload in rows:
            await ws.send_str(payload)
            db.execute("DELETE FROM queue WHERE id = ?", (row_id,))
        db.commit()
        async for _ in ws:
            pass
    finally:
        conns = sockets.get(slack_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del sockets[slack_id]
    return ws


def signature_ok(request: web.Request, raw: bytes) -> bool:
    ts = request.headers.get("x-little-guy-timestamp", "")
    given = request.headers.get("x-little-guy-signature", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > WEBHOOK_SKEW:
        return False
    signed = ts.encode() + b"." + raw
    return any(
        hmac.compare_digest(hmac.new(key, signed, hashlib.sha256).hexdigest(), given)
        for key in PIXL_API_KEYS
    )


async def webhook(request: web.Request) -> web.Response:
    raw = await request.read()
    if not signature_ok(request, raw):
        return web.json_response({"ok": False}, status=401)
    try:
        event = json.loads(raw)
        event_id = str(event["id"])[:100]
        slack_ids = [s for s in event["slack_ids"] if isinstance(s, str) and SLACK_ID_RE.match(s)]
        kind = event["kind"] if event["kind"] in KINDS else "info"
        title = str(event["title"])[:100]
        project = str(event["project"])[:80] if event.get("project") else None
    except (ValueError, KeyError, TypeError):
        return web.json_response({"ok": False}, status=400)

    now = int(time.time())
    prune(now)
    if db.execute("SELECT 1 FROM seen WHERE event_id = ?", (event_id,)).fetchone():
        return web.json_response({"ok": True, "duplicate": True})
    db.execute("INSERT INTO seen (event_id, at) VALUES (?, ?)", (event_id, now))

    payload = json.dumps({"kind": kind, "title": title, "project": project})
    for slack_id in slack_ids:
        conns = list(sockets.get(slack_id, ()))
        sent = False
        for ws in conns:
            try:
                await ws.send_str(payload)
                sent = True
            except ConnectionResetError:
                pass
        if not sent:
            db.execute(
                "INSERT INTO queue (slack_id, payload, created_at) VALUES (?, ?, ?)",
                (slack_id, payload, now),
            )
            db.execute(
                "DELETE FROM queue WHERE slack_id = ? AND id NOT IN "
                "(SELECT id FROM queue WHERE slack_id = ? ORDER BY id DESC LIMIT ?)",
                (slack_id, slack_id, QUEUE_MAX),
            )
    db.commit()
    return web.json_response({"ok": True})


async def http_session(app: web.Application):
    app["http"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    yield
    await app["http"].close()


def make_app() -> web.Application:
    app = web.Application(client_max_size=16 * 1024)
    app.cleanup_ctx.append(http_session)
    app.router.add_get("/login", login)
    app.router.add_get("/callback", callback)
    app.router.add_post("/token", token)
    app.router.add_post("/logout", logout)
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/webhook/pixl", webhook)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host=["0.0.0.0", "::"], port=PORT, access_log=None)
