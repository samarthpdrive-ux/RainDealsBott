"""Server-side API key functions with encrypted owner-only key display."""

import hashlib
import secrets
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken

from database import SessionLocal
from models.api_key import ApiKey
from config import API_KEY_ENCRYPTION_KEY, API_KEY_PEPPER


class ApiKeyConfigurationError(RuntimeError):
    pass


def _hash_key(raw_key: str) -> str:
    if not API_KEY_PEPPER:
        raise ApiKeyConfigurationError("API_KEY_PEPPER is not configured")
    return hashlib.sha256(f"{API_KEY_PEPPER}:{raw_key}".encode("utf-8")).hexdigest()


def _cipher() -> Fernet:
    if not API_KEY_ENCRYPTION_KEY:
        raise ApiKeyConfigurationError("API_KEY_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(API_KEY_ENCRYPTION_KEY.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ApiKeyConfigurationError("API_KEY_ENCRYPTION_KEY is invalid") from exc


def _encrypt_key(raw_key: str) -> str:
    return _cipher().encrypt(raw_key.encode("utf-8")).decode("utf-8")


def _decrypt_key(encrypted_key: str | None) -> str | None:
    if not encrypted_key:
        return None
    try:
        return _cipher().decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def create_api_key(telegram_id: int) -> tuple[str, ApiKey]:
    """Rotate a user's key and retain it encrypted for its owner to view."""
    raw_key = f"AK_{secrets.token_urlsafe(32)}"
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        for existing in db.query(ApiKey).filter(
            ApiKey.telegram_id == telegram_id, ApiKey.is_active == True
        ).all():
            existing.is_active = False
            existing.revoked_at = now
        key = ApiKey(
            telegram_id=telegram_id,
            key_prefix=raw_key[:11],
            key_hash=_hash_key(raw_key),
            encrypted_key=_encrypt_key(raw_key),
            is_active=True,
        )
        db.add(key)
        db.commit()
        db.refresh(key)
        return raw_key, key
    finally:
        db.close()


def active_api_key(telegram_id: int) -> ApiKey | None:
    db = SessionLocal()
    try:
        return db.query(ApiKey).filter(
            ApiKey.telegram_id == telegram_id, ApiKey.is_active == True
        ).order_by(ApiKey.id.desc()).first()
    finally:
        db.close()


def active_api_key_with_secret(telegram_id: int) -> tuple[ApiKey | None, str | None]:
    """Return the active record plus its owner-displayable encrypted key."""
    db = SessionLocal()
    try:
        key = db.query(ApiKey).filter(
            ApiKey.telegram_id == telegram_id, ApiKey.is_active == True
        ).order_by(ApiKey.id.desc()).first()
        return key, _decrypt_key(key.encrypted_key) if key else None
    finally:
        db.close()


def revoke_api_key(telegram_id: int) -> bool:
    db = SessionLocal()
    try:
        keys = db.query(ApiKey).filter(
            ApiKey.telegram_id == telegram_id, ApiKey.is_active == True
        ).all()
        if not keys:
            return False
        now = datetime.utcnow()
        for key in keys:
            key.is_active = False
            key.revoked_at = now
        db.commit()
        return True
    finally:
        db.close()


def authenticate_api_key(raw_key: str) -> ApiKey | None:
    """Returns an active key when the supplied secret matches its stored hash."""
    if not raw_key or not raw_key.startswith("AK_"):
        return None
    db = SessionLocal()
    try:
        key = db.query(ApiKey).filter(
            ApiKey.key_hash == _hash_key(raw_key), ApiKey.is_active == True
        ).first()
        if key:
            key.last_used_at = datetime.utcnow()
            db.commit()
        return key
    finally:
        db.close()
