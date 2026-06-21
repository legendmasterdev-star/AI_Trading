from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

# PBKDF2 work factor and session lifetime. These are deliberately stdlib-only so
# the project keeps a minimal dependency list (no passlib / pyjwt needed).
_PBKDF2_ITERATIONS = 200_000
_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_MIN_PASSWORD_LENGTH = 6


class AuthError(Exception):
    """Raised for any authentication/authorization failure with an HTTP status."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class AuthService:
    """SQLite-backed accounts with hashed passwords and signed session tokens."""

    def __init__(self, db_path: str | None = None, secret: str | None = None):
        default_path = Path(__file__).resolve().parent.parent / "data" / "app.db"
        self.db_path = Path(db_path or os.getenv("AUTH_DB_PATH") or default_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()
        # Stable signing secret: prefer the env var, otherwise persist a random
        # one so issued tokens survive server restarts without manual config.
        self.secret = (
            secret or os.getenv("SESSION_SECRET") or self._persisted_secret()
        ).encode()

    # ----- database plumbing -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            with conn:  # commits on success, rolls back on exception
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT,
                    plan TEXT,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _persisted_secret(self) -> str:
        with self._lock, self._db() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'session_secret'"
            ).fetchone()
            if row:
                return row["value"]
            value = secrets.token_hex(32)
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('session_secret', ?)",
                (value,),
            )
            return value

    # ----- password hashing --------------------------------------------------

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
        )
        return derived.hex()

    @staticmethod
    def _normalize_email(email: str | None) -> str:
        return (email or "").strip().lower()

    @classmethod
    def _validate_credentials(cls, email: str, password: str | None) -> None:
        domain = email.split("@")[-1] if "@" in email else ""
        if not email or "@" not in email or "." not in domain:
            raise AuthError("Enter a valid email address.")
        if not password or len(password) < _MIN_PASSWORD_LENGTH:
            raise AuthError(
                f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."
            )

    # ----- public API --------------------------------------------------------

    def register(
        self,
        email: str,
        password: str,
        name: str | None = None,
        plan: str | None = None,
    ) -> dict:
        email = self._normalize_email(email)
        self._validate_credentials(email, password)

        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        display_name = (name or "").strip() or email.split("@")[0]
        now = int(time.time())

        try:
            with self._lock, self._db() as conn:
                conn.execute(
                    """
                    INSERT INTO users (email, name, plan, password_hash, password_salt, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (email, display_name, plan, password_hash, salt.hex(), now),
                )
        except sqlite3.IntegrityError:
            raise AuthError("An account with this email already exists.", 409)

        return self._issue(email)

    def login(self, email: str, password: str) -> dict:
        email = self._normalize_email(email)
        with self._lock, self._db() as conn:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM users WHERE email = ?",
                (email,),
            ).fetchone()

        # Always run a hash to keep timing roughly constant for unknown emails.
        salt = bytes.fromhex(row["password_salt"]) if row else secrets.token_bytes(16)
        candidate = self._hash_password(password or "", salt)
        if row is None or not hmac.compare_digest(candidate, row["password_hash"]):
            raise AuthError("Invalid email or password.", 401)

        return self._issue(email)

    def user_public(self, email: str | None) -> dict | None:
        if not email:
            return None
        with self._lock, self._db() as conn:
            row = conn.execute(
                "SELECT email, name, plan, created_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        if row is None:
            return None
        return {
            "email": row["email"],
            "name": row["name"],
            "plan": row["plan"],
            "created_at": row["created_at"],
        }

    # ----- token signing / verification -------------------------------------

    def _issue(self, email: str) -> dict:
        payload = {"sub": email, "exp": int(time.time()) + _TOKEN_TTL_SECONDS}
        return {"token": self._sign(payload), "user": self.user_public(email)}

    def _sign(self, payload: dict) -> str:
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        signature = hmac.new(self.secret, body.encode(), hashlib.sha256).digest()
        return f"{body}.{_b64(signature)}"

    def verify_token(self, token: str | None) -> dict:
        if not token or token.count(".") != 1:
            raise AuthError("Not authenticated.", 401)

        body, _, signature = token.partition(".")
        expected = hmac.new(self.secret, body.encode(), hashlib.sha256).digest()
        try:
            provided = _unb64(signature)
        except (ValueError, TypeError):
            raise AuthError("Invalid session.", 401)
        if not hmac.compare_digest(expected, provided):
            raise AuthError("Invalid session.", 401)

        try:
            payload = json.loads(_unb64(body))
        except (ValueError, TypeError):
            raise AuthError("Invalid session.", 401)

        if int(payload.get("exp", 0)) < int(time.time()):
            raise AuthError("Session expired. Please sign in again.", 401)

        user = self.user_public(payload.get("sub"))
        if user is None:
            raise AuthError("Account not found.", 401)
        return user
