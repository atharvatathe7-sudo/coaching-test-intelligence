"""
Password hashing with Argon2id (argon2-cffi defaults).

Passwords are never logged or returned.
"""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .. import config

_hasher = PasswordHasher()

# Verified against when the email is unknown, so a failed login takes
# about the same time whether or not the account exists.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


class PasswordPolicyError(ValueError):
    pass


def check_password_policy(password: str) -> None:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {config.MIN_PASSWORD_LENGTH} "
            "characters."
        )
    if len(password) > config.MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {config.MAX_PASSWORD_LENGTH} "
            "characters."
        )


def hash_password(password: str) -> str:
    check_password_policy(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    """Spend the same effort as a real verification; always fails."""
    verify_password(_DUMMY_HASH, password)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
