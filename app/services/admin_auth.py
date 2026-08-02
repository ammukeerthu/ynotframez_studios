import base64
import binascii
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class AdminSession:
    username: str
    session_version: int


def hash_admin_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    )
    return salt.hex(), digest.hex()


def verify_admin_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    )
    return hmac.compare_digest(actual, expected)


@lru_cache(maxsize=1)
def get_session_secret() -> str:
    configured = settings.admin_session_secret.strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError("ADMIN_SESSION_SECRET must contain at least 32 characters.")
        return configured

    secret_path = Path(settings.admin_session_secret_file)
    if secret_path.exists():
        stored = secret_path.read_text(encoding="utf-8").strip()
        if len(stored) >= 32:
            return stored

    generated = secrets.token_urlsafe(48)
    try:
        with secret_path.open("x", encoding="utf-8") as secret_file:
            secret_file.write(generated)
    except FileExistsError:
        stored = secret_path.read_text(encoding="utf-8").strip()
        if len(stored) >= 32:
            return stored
        secret_path.write_text(generated, encoding="utf-8")
    return generated


def create_admin_session(username: str, session_version: int) -> str:
    expires_at = int(time.time()) + settings.admin_session_hours * 60 * 60
    payload = f"{username}|{session_version}|{expires_at}"
    signature = hmac.new(
        get_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{signature}".encode("utf-8")).decode("ascii")


def read_admin_session(token: str | None) -> AdminSession | None:
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, raw_version, raw_expiry, signature = decoded.rsplit("|", 3)
        version = int(raw_version)
        expires_at = int(raw_expiry)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None

    payload = f"{username}|{version}|{expires_at}"
    expected = hmac.new(
        get_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected) or expires_at <= int(time.time()):
        return None
    return AdminSession(username=username, session_version=version)
