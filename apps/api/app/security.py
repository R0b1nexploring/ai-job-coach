import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from .config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except UnknownHashError:
        return False


def session_version(user_id: str, password_hash_value: str) -> str:
    settings = get_settings()
    message = f"{user_id}:{password_hash_value}".encode()
    secret = settings.app_secret_key.get_secret_value().encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def create_token(user_id: str, password_hash_value: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "sv": session_version(user_id, password_hash_value), "exp": expires},
        settings.app_secret_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_token(token: str) -> tuple[str, str] | None:
    try:
        secret = get_settings().app_secret_key.get_secret_value()
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        user_id = payload["sub"]
        version = payload["sv"]
        if not isinstance(user_id, str) or not isinstance(version, str):
            return None
        return user_id, version
    except (jwt.PyJWTError, KeyError, TypeError):
        return None
