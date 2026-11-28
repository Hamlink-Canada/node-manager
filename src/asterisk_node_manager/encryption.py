"""Authenticated encryption for application-managed configuration values."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import TypeDecorator, Text


_VERSION_PREFIX = "fernet:v1:"
_fernet: Fernet | None = None


class EncryptionError(RuntimeError):
    """Raised when encrypted database values cannot be safely accessed."""


def configure_encryption_key(key: str | bytes) -> None:
    """Configure the process key, rejecting malformed or weak key encodings."""
    global _fernet
    try:
        _fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        _fernet = None
        raise EncryptionError(
            "security.encryption_key must be a URL-safe base64 Fernet key; "
            "generate one with Fernet.generate_key()"
        ) from error


def has_encryption_key() -> bool:
    return _fernet is not None


def require_encryption_key(key: str | bytes | None = None) -> None:
    """Configure the supplied key or fail closed if no key is available."""
    if key is not None:
        configure_encryption_key(key)
    elif _fernet is None:
        raise EncryptionError(
            "Database encryption key is required. Configure "
            "security.encryption_key or ASTNODE_SECURITY__ENCRYPTION_KEY."
        )


def encrypt_value(value: str | None) -> str | None:
    if value is None:
        return None
    if _fernet is None:
        raise EncryptionError("Database encryption key is not configured")
    token = _fernet.encrypt(value.encode("utf-8")).decode("ascii")
    return _VERSION_PREFIX + token


def decrypt_value(value: str | None) -> str | None:
    if value is None:
        return None
    if _fernet is None:
        raise EncryptionError("Database encryption key is not configured")
    if not value.startswith(_VERSION_PREFIX):
        raise EncryptionError(
            "Database contains a value that is not encrypted with the configured "
            "format; this build does not migrate existing plaintext databases."
        )
    try:
        return _fernet.decrypt(value[len(_VERSION_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as error:
        raise EncryptionError(
            "Could not decrypt a database value. Check the configured encryption key "
            "and restore the matching key with this database backup."
        ) from error


class EncryptedText(TypeDecorator):
    """Store text as authenticated ciphertext and return plaintext to the ORM."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        return decrypt_value(value)


def validate_database_encryption(database: str) -> None:
    """Decrypt one stored configuration value before a service starts."""
    from sqlalchemy import select

    from .database import session_factory
    from .models import ConfigValue, CustomLine, CustomValue

    sessions = session_factory(database)
    with sessions() as session:
        for column in (ConfigValue.default_value, CustomValue.value, CustomLine.content):
            if session.scalar(select(column).limit(1)) is not None:
                return
