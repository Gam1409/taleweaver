"""Read-only, user-bound access to private media without putting tokens in URLs."""

from datetime import timedelta
from pathlib import PurePosixPath

import jwt
from fastapi import HTTPException, Request, Response
from starlette.types import Scope

from backend.core.auth import ALGORITHM, SECRET_KEY, create_access_token
from backend.core.database import AsyncSessionLocal
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.user import User

COOKIE = "tw_media"


def issue_media_cookie(response: Response, request: Request, user: User) -> None:
    token = create_access_token(
        {"sub": user.id, "ver": user.token_version or 0, "aud": "media"},
        expires_delta=timedelta(hours=24),
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=86400,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/data",
    )


async def authorize_media(path: str, scope: Scope) -> None:
    request = Request(scope)
    try:
        payload = jwt.decode(
            request.cookies.get(COOKIE, ""),
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience="media",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sign in to view this media.") from exc
    async with AsyncSessionLocal() as db:
        user = await db.get(User, payload.get("sub"))
        if user is None or payload.get("ver") != (user.token_version or 0):
            raise HTTPException(401, "Sign in to view this media.")
        parts = PurePosixPath(path).parts
        if ".." in parts:
            raise HTTPException(403, "Access denied")
        if user.role == "admin":
            return
        if len(parts) >= 3 and parts[:2] == ("adventures", "sessions"):
            session = await db.get(GameSession, parts[2])
            if session is None or session.user_id != user.id:
                raise HTTPException(403, "Access denied")
        if len(parts) >= 3 and parts[:2] == ("adventures", "library"):
            template = await db.get(AdventureTemplate, parts[2])
            if template is None or template.owner_id not in (None, user.id):
                raise HTTPException(403, "Access denied")
