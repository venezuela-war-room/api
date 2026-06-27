import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.auth import require_admin
from app.database import get_db
from app.models import ApiKey
from app.schemas import (
    BulkUpsertResponse,
    DeleteBySourceUrl,
    PaginatedResponse,
    PersonBulkCreate,
    PersonCreate,
    PersonResponse,
    PersonStatusUpdate,
    SearchParams,
)

router = APIRouter(prefix="/api/v1/found-people", tags=["found-people"])


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="Search found people",
    description=(
        "Public, paginated search. Combine any filters; they are ANDed together. "
        "Text filters are accent-insensitive. By default soft-removed records "
        "(`status=removed`) are hidden unless you pass `status=removed` explicitly."
    ),
)
async def search_people(
    q: str | None = Query(default=None, min_length=2, max_length=100, description="Free-text match against full name."),
    name: str | None = Query(default=None, min_length=2, max_length=100, description="Match against full name only."),
    document_id: str | None = Query(default=None, min_length=1, max_length=12, description="Exact cédula/document match; non-digits are stripped."),
    ubicacion: str | None = Query(default=None, min_length=2, max_length=200, description="Match against the current facility name."),
    tipo_instalacion: str | None = Query(default=None, description="Facility type: hospital, albergue, morgue, punto_concentracion, centro_medico, unknown."),
    procedencia: str | None = Query(default=None, min_length=2, max_length=200, description="Match against place of origin (lugar_procedencia)."),
    fallecido: bool | None = Query(default=None, description="Filter by deceased flag."),
    status_filter: str | None = Query(default=None, alias="status", description="Filter by record status; pass `removed` to see soft-deleted records."),
    page: int = Query(default=1, ge=1, le=500),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    params = SearchParams(
        q=q,
        name=name,
        document_id=document_id,
        ubicacion=ubicacion,
        tipo_instalacion=tipo_instalacion,
        procedencia=procedencia,
        fallecido=fallecido,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    people, total = await crud.search_people(db, params)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return PaginatedResponse(
        data=[PersonResponse.model_validate(p) for p in people],
        pagination={"page": page, "page_size": page_size, "total": total, "total_pages": total_pages},
    )


@router.get(
    "/{person_id}",
    response_model=PersonResponse,
    summary="Get a found person by ID",
    description="Public lookup of a single record by its UUID.",
    responses={404: {"description": "No record with that ID exists."}},
)
async def get_person(person_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> PersonResponse:
    person = await crud.get_person_by_id(db, person_id)
    if not person:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    return PersonResponse.model_validate(person)


@router.post(
    "",
    response_model=PersonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or upsert a found person",
    description=(
        "Ingest a single record. Idempotent on `source_hash`: re-sending the same hash "
        "updates the existing record instead of duplicating it. Requires `X-Admin-Key`."
    ),
    responses={401: {"description": "Missing, invalid, or revoked `X-Admin-Key`."}},
)
async def create_person(
    payload: PersonCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> PersonResponse:
    person, _ = await crud.upsert_person(db, payload, api_key_id=api_key.id)
    await db.commit()
    return PersonResponse.model_validate(person)


@router.post(
    "/bulk",
    response_model=BulkUpsertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create or upsert found people",
    description=(
        "Ingest 1–500 records in one call. Each record is upserted on `source_hash`; "
        "the response reports how many were `created` vs `updated`. Requires `X-Admin-Key`."
    ),
    responses={401: {"description": "Missing, invalid, or revoked `X-Admin-Key`."}},
)
async def bulk_upsert(
    payload: PersonBulkCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> BulkUpsertResponse:
    results = []
    for p in payload.people:
        person, inserted = await crud.upsert_person(db, p, api_key_id=api_key.id)
        results.append((person, inserted))
    await db.commit()

    created = sum(1 for _, ins in results if ins)
    updated = len(results) - created
    return BulkUpsertResponse(
        created=created,
        updated=updated,
        data=[PersonResponse.model_validate(p) for p, _ in results],
    )


@router.patch(
    "/{person_id}",
    response_model=PersonResponse,
    summary="Update a found person's status",
    description=(
        "Change the `status` of a record (e.g. `verified`, `needs_review`, `removed`). "
        "Setting `removed` soft-deletes it. Requires `X-Admin-Key`."
    ),
    responses={
        401: {"description": "Missing, invalid, or revoked `X-Admin-Key`."},
        404: {"description": "No record with that ID exists."},
    },
)
async def update_status(
    person_id: uuid.UUID,
    payload: PersonStatusUpdate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> PersonResponse:
    person = await crud.update_person_status(db, person_id, payload.status)
    if not person:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    await db.commit()
    return PersonResponse.model_validate(person)


@router.delete(
    "",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete records by source URL",
    description=(
        "Soft-delete (set `status=removed`) every record originating from a given "
        "`source_url`. Returns the count of affected rows. Requires `X-Admin-Key`."
    ),
    responses={401: {"description": "Missing, invalid, or revoked `X-Admin-Key`."}},
)
async def delete_by_source_url(
    payload: DeleteBySourceUrl,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> dict:
    deleted = await crud.soft_delete_by_source_url(db, payload.source_url)
    await db.commit()
    return {"deleted": deleted}
