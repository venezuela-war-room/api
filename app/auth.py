import hashlib

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ApiKey

admin_key_header = APIKeyHeader(name="X-Admin-Key", scheme_name="AdminKey", auto_error=False)
master_key_header = APIKeyHeader(name="X-Master-Key", scheme_name="MasterKey", auto_error=False)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def require_admin(
    request: Request,
    raw_key: str | None = Security(admin_key_header),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Admin-Key header required")

    key_hash = _hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    request.state.api_key = api_key
    return api_key


def require_master(raw_key: str | None = Security(master_key_header)) -> None:
    if not raw_key or raw_key != settings.master_admin_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Master-Key required")
