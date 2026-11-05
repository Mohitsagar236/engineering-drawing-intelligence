"""Single-workspace authentication: signed HttpOnly sessions and HTTP Basic API access."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from sqlalchemy import delete
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import RevokedSession

COOKIE = "ed_session"
attempts = OrderedDict()


def check_password(username, password):
    return secrets.compare_digest(
        username.encode(), settings.auth_username.encode()
    ) and secrets.compare_digest(password.encode(), settings.auth_password.encode())


def create_session():
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "actor": settings.auth_username,
                "expires": int(time.time()) + 28800,
                "nonce": secrets.token_hex(12),
            }
        ).encode()
    ).decode()
    signature = hmac.new(
        settings.auth_password.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return payload + "." + signature


def session_actor(cookie):
    try:
        payload, signature = cookie.rsplit(".", 1)
        expected = hmac.new(
            settings.auth_password.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload))
        if data["expires"] <= time.time() or data["actor"] != settings.auth_username:
            return None
        with SessionLocal() as db:
            if db.get(RevokedSession, hashlib.sha256(cookie.encode()).hexdigest()):
                return None
        return data["actor"]
    except (ValueError, KeyError, TypeError):
        return None


def revoke_session(cookie):
    if not session_actor(cookie):
        return
    with SessionLocal() as db:
        db.execute(
            delete(RevokedSession).where(RevokedSession.expires_at <= int(time.time()))
        )
        db.merge(
            RevokedSession(
                token_hash=hashlib.sha256(cookie.encode()).hexdigest(),
                expires_at=int(time.time()) + 28800,
            )
        )
        db.commit()


def throttled(ip):
    now = time.monotonic()
    history = attempts.get(ip, [])
    history = [t for t in history if now - t < 60]
    attempts[ip] = history
    attempts.move_to_end(ip)
    while len(attempts) > 10000:
        attempts.popitem(last=False)
    return len(history) >= 10


def failed_login(ip):
    attempts.setdefault(ip, []).append(time.monotonic())
