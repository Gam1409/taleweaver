"""One-time recovery codes and admin-issued password reset tokens.

Both secrets are high-entropy random values, so a fast SHA-256 digest is a
sufficient at-rest protection (unlike user-chosen passwords). Plaintext values
are only ever returned once, at creation time.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.sql.elements import ColumnElement

from backend.core.auth import aget_password_hash
from backend.models.user import User

RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_GROUP_LENGTH = 5
# Crockford-style alphabet without easily confused characters (0/O, 1/I/L).
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
RESET_TOKEN_TTL = timedelta(hours=24)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def normalize_recovery_code(code: str) -> str:
    """Accept codes regardless of case, spaces, or dashes."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _random_recovery_code() -> str:
    groups = [
        "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_GROUP_LENGTH))
        for _ in range(2)
    ]
    return "-".join(groups)


def issue_recovery_codes(user: User) -> list[str]:
    """Replace the user's recovery codes and return the new plaintext codes."""
    codes = [_random_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    user.recovery_code_hashes = [_digest(normalize_recovery_code(code)) for code in codes]
    return codes


async def consume_recovery_code(db: AsyncSession, user: User, code: str, new_password: str) -> bool:
    """Atomically consume one code and rotate the password in the caller's transaction."""
    candidate = _digest(normalize_recovery_code(code))
    snapshot = list(user.recovery_code_hashes or [])
    if not any(hmac.compare_digest(item, candidate) for item in snapshot):
        return False
    hashed_password = await aget_password_hash(new_password)
    while candidate in snapshot:
        remaining = list(snapshot)
        remaining.remove(candidate)
        if await _store_password(
            db,
            user,
            hashed_password,
            User.recovery_code_hashes == snapshot,
            recovery_code_hashes=remaining,
        ):
            return True
        # Another code may have been used or the entire set replaced. Re-read
        # after the failed conditional write so unrelated codes are not restored.
        result = await db.execute(select(User.recovery_code_hashes).where(User.id == user.id))
        snapshot = list(result.scalar_one_or_none() or [])
    return False


async def regenerate_recovery_codes(db: AsyncSession, user: User) -> Optional[list[str]]:
    """Replace codes only while the verified credentials still belong to this session."""
    codes = [_random_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    hashes = [_digest(normalize_recovery_code(code)) for code in codes]
    statement = (
        update(User)
        .where(User.id == user.id, *_credential_conditions(user))
        .values(recovery_code_hashes=hashes)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    with db.no_autoflush:
        result = await db.execute(statement)
    if result.scalar_one_or_none() is None:
        return None
    set_committed_value(user, "recovery_code_hashes", hashes)
    return codes


def issue_password_reset_token(user: User) -> str:
    token = secrets.token_urlsafe(32)
    user.password_reset_token_hash = _digest(token)
    user.password_reset_expires_at = datetime.now(timezone.utc) + RESET_TOKEN_TTL
    return token


async def find_user_by_reset_token(db: AsyncSession, token: str) -> Optional[User]:
    if not token:
        return None
    result = await db.execute(select(User).where(User.password_reset_token_hash == _digest(token)))
    user = result.scalars().first()
    if user is None or _reset_token_expired(user.password_reset_expires_at):
        return None
    return user


def _reset_token_expired(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        # SQLite drops tz info; values are always written in UTC.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


async def _lock_reset_token(db: AsyncSession, user: User, token: str) -> bool:
    """Check expiry after acquiring the database writer, preserving microseconds."""
    statement = (
        update(User)
        .where(User.id == user.id, User.password_reset_token_hash == _digest(token))
        .values(password_reset_token_hash=User.password_reset_token_hash)
        .returning(User.password_reset_expires_at)
        .execution_options(synchronize_session=False)
    )
    with db.no_autoflush:
        result = await db.execute(statement)
    # This no-op write holds the lock through the password claim and commit.
    # A timestamp bound before a blocked UPDATE could otherwise accept an
    # already expired link when another SQLite writer finally releases its lock.
    return not _reset_token_expired(result.scalar_one_or_none())


async def consume_password_reset_token(
    db: AsyncSession, token: str, new_password: str
) -> Optional[User]:
    """Bind reset-link validation and consumption to the password update itself."""
    user = await find_user_by_reset_token(db, token)
    if user is None:
        return None
    hashed_password = await aget_password_hash(new_password)
    if not await _lock_reset_token(db, user, token):
        return None
    if not await _store_password(
        db,
        user,
        hashed_password,
        User.password_reset_token_hash == _digest(token),
        User.password_reset_expires_at >= datetime.now(timezone.utc),
    ):
        return None
    return user


def _credential_conditions(user: User) -> tuple[ColumnElement[bool], ...]:
    return (
        User.hashed_password == user.hashed_password,
        User.token_version == (user.token_version or 0),
    )


async def lock_current_credentials(db: AsyncSession, user: User) -> bool:
    """Guard a credential edit against a password changed during verification.

    The no-op write holds the database row until the caller commits or rolls
    back, including on SQLite where SELECT FOR UPDATE is unavailable.
    """
    statement = (
        update(User)
        .where(User.id == user.id, *_credential_conditions(user))
        .values(token_version=User.token_version)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    with db.no_autoflush:
        result = await db.execute(statement)
    return result.scalar_one_or_none() is not None


async def set_new_password(
    db: AsyncSession,
    user: User,
    new_password: str,
    *,
    require_current_credentials: bool = False,
) -> bool:
    """Rotate credentials using a database increment, without committing the transaction."""
    conditions = _credential_conditions(user) if require_current_credentials else ()
    hashed_password = await aget_password_hash(new_password)
    return await _store_password(db, user, hashed_password, *conditions)


async def _store_password(
    db: AsyncSession,
    user: User,
    hashed_password: str,
    *conditions: ColumnElement[bool],
    **extra_values: Any,
) -> bool:
    """Keep proof consumption, revocation and the password in one conditional write."""
    values = {
        "hashed_password": hashed_password,
        "password_reset_token_hash": None,
        "password_reset_expires_at": None,
        **extra_values,
    }
    statement = (
        update(User)
        .where(User.id == user.id, *conditions)
        .values(**values, token_version=func.coalesce(User.token_version, 0) + 1)
        .returning(User.token_version, User.username)
        .execution_options(synchronize_session=False)
    )
    # Pending profile/username edits must not flush before the credential check.
    with db.no_autoflush:
        result = await db.execute(statement)
    rotation = result.one_or_none()
    if rotation is None:
        return False
    version, username = rotation
    # Do not dirty these fields again: a later ORM flush must not overwrite a
    # concurrent rotation. Retain this exact version for the replacement JWT.
    for name, value in {**values, "token_version": version}.items():
        set_committed_value(user, name, value)
    # Use the principal observed by this rotation, while retaining a same-call
    # rename that still needs to flush under the held database write lock.
    if not inspect(user).attrs.username.history.has_changes():
        set_committed_value(user, "username", username)
    return True
