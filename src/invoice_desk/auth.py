"""Small signed-token auth. Demo mode hands out a role on request so anyone can try the portal."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

ROLES = {"viewer": 1, "reviewer": 2, "admin": 3}


class AuthError(Exception):
    pass


class Auth:
    def __init__(self, secret: str | None = None, demo: bool | None = None, users: str | None = None, ttl: int = 8 * 3600):
        self.secret = (secret or os.environ.get("INVOICE_DESK_SECRET") or secrets.token_hex(32)).encode()
        self.demo = demo if demo is not None else os.environ.get("DEMO_MODE", "1") not in ("0", "false", "")
        self.ttl = ttl
        self.users: dict[str, tuple[str, str]] = {}
        for item in filter(None, (users or os.environ.get("INVOICE_DESK_USERS", "")).split(",")):
            name, pw, role = item.split(":")
            if role not in ROLES:
                raise ValueError(f"bad role for {name}")
            self.users[name] = (pw, role)

    def _sign(self, body: str) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.secret, body.encode(), hashlib.sha256).digest()).decode().rstrip("=")

    def issue(self, name: str, role: str) -> str:
        body = base64.urlsafe_b64encode(json.dumps(dict(sub=name, role=role, exp=int(time.time()) + self.ttl)).encode()).decode().rstrip("=")
        return f"{body}.{self._sign(body)}"

    def verify(self, token: str | None) -> dict:
        if not token or "." not in token:
            raise AuthError("sign in first")
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(body)):
            raise AuthError("invalid token")
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except Exception:
            raise AuthError("invalid token") from None
        if data.get("exp", 0) < time.time() or data.get("role") not in ROLES:
            raise AuthError("session expired")
        return data

    def demo_login(self, role: str) -> str:
        if not self.demo:
            raise AuthError("demo mode is off")
        if role not in ROLES:
            raise AuthError("unknown role")
        return self.issue(f"demo-{role}", role)

    def login(self, name: str, password: str) -> str:
        pw, role = self.users.get(name, (None, None))
        if pw is None or not hmac.compare_digest(pw.encode(), password.encode()):
            raise AuthError("wrong name or password")
        return self.issue(name, role)


def allows(role: str, needed: str) -> bool:
    return ROLES[role] >= ROLES[needed]
