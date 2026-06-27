from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    description="Returns `{\"ok\": true, \"db\": \"connected\"}` when the API can reach the database.",
)
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"ok": True, "db": "connected"}
