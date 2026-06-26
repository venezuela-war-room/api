import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.auth import require_master
from app.database import get_db
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyListItem

router = APIRouter(prefix="/api/v1/admin/api-keys", tags=["admin"], dependencies=[Depends(require_master)])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyCreate, db: AsyncSession = Depends(get_db)) -> ApiKeyCreated:
    api_key, raw_key = await crud.create_api_key(db, payload.team_name, payload.description)
    await db.commit()
    return ApiKeyCreated(
        id=api_key.id,
        key=raw_key,
        key_prefix=api_key.key_prefix,
        team_name=api_key.team_name,
        description=api_key.description,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[ApiKeyListItem])
async def list_api_keys(db: AsyncSession = Depends(get_db)) -> list[ApiKeyListItem]:
    keys = await crud.list_api_keys(db)
    return [ApiKeyListItem.model_validate(k) for k in keys]


@router.delete("/{key_id}", status_code=status.HTTP_200_OK)
async def revoke_api_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    revoked = await crud.revoke_api_key(db, key_id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await db.commit()
    return {"revoked": True, "id": str(key_id)}
