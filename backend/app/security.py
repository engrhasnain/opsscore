"""Passwords, access tokens and API keys."""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

JWT_ALGORITHM = "HS256"
API_KEY_PREFIX = "ok"
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


def _prehash(password: str) -> bytes:
    """bcrypt only reads the first 72 bytes. Pre-hashing makes every byte count.

    The digest is base64-encoded so it never contains a NUL byte.
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except ValueError:
        return False


# A real hash to compare against when the account does not exist, so a missing
# account takes as long to reject as a wrong password (no user enumeration).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        problems.append(f"must be at most {PASSWORD_MAX_LENGTH} characters")
    if password.strip() != password:
        problems.append("must not start or end with spaces")
    if len(set(password)) < 5:
        problems.append("is too repetitive")
    return problems


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    token_version: int


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID | None, token_version: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "ver": token_version,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenClaims | None:
    """Return the claims, or None for anything expired, forged or malformed."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "ver", "typ"]},
        )
        if payload.get("typ") != "access":
            return None
        org = payload.get("org")
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(org) if org else None,
            token_version=int(payload["ver"]),
        )
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        return None


@dataclass(frozen=True)
class NewApiKey:
    plaintext: str
    prefix: str
    key_hash: str


def generate_api_key() -> NewApiKey:
    """Keys look like ``ok_<prefix>_<secret>``. Only the hash is stored."""
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    plaintext = f"{API_KEY_PREFIX}_{prefix}_{secret}"
    return NewApiKey(plaintext=plaintext, prefix=prefix, key_hash=hash_api_key(plaintext))


def hash_api_key(plaintext: str) -> str:
    # API keys carry 256 bits of entropy, so a fast hash is appropriate.
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def parse_api_key_prefix(plaintext: str) -> str | None:
    parts = plaintext.split("_", 2)
    if len(parts) != 3 or parts[0] != API_KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1]


def api_key_matches(plaintext: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(plaintext), stored_hash)
