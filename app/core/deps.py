from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_TOKEN_COOKIE_NAME, decode_access_token
from app.db.models import User
from app.db.session import get_db

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
)


async def get_current_user_optional(request: Request, db: AsyncSession) -> User | None:
    """For page routes that redirect instead of returning a 401 JSON error."""
    token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user_optional(request, db)
    if user is None:
        raise CREDENTIALS_ERROR
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
