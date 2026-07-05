import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def _pre_hash(password: str) -> bytes:
    # SHA-256 first so passwords of any length work (bcrypt has a 72-byte limit)
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pre_hash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_pre_hash(plain), hashed.encode("utf-8"))


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    return jwt.encode({"sub": subject, "exp": expire}, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload.get("sub")
    except JWTError:
        return None


def create_email_verification_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode(
        {"sub": email, "exp": expire, "type": "email_verification"},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def verify_email_verification_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "email_verification":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_unsubscribe_token(user_id: int, pref_key: str) -> str:
    # No expiry: unsubscribe links must keep working in old emails.
    return jwt.encode(
        {"sub": str(user_id), "pref": pref_key, "type": "unsubscribe"},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def verify_unsubscribe_token(token: str) -> Optional[tuple]:
    """Return (user_id, pref_key) for a valid unsubscribe token, else None."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "unsubscribe":
            return None
        uid = payload.get("sub")
        pref = payload.get("pref")
        if uid is None or pref is None:
            return None
        return int(uid), pref
    except (JWTError, ValueError):
        return None


def create_password_reset_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode(
        {"sub": email, "exp": expire, "type": "password_reset"},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def verify_password_reset_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "password_reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None
