"""add lat/lon + geocoding queue to instalaciones

Revision ID: 002
Revises: 001
Create Date: 2026-06-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Coordinates returned by OpenStreetMap Nominatim alongside the address.
    # `direccion` already exists from migration 001 — only the coordinates are new.
    op.add_column("instalaciones", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("instalaciones", sa.Column("lon", sa.Float(), nullable=True))

    # Geocoding queue marker. `geocoded_at IS NULL` ⟺ "still needs geocoding".
    # The background worker (app/geocoding_worker.py) claims NULL rows, geocodes
    # them, and stamps this column. Migrations stay offline — no network here.
    op.add_column(
        "instalaciones",
        sa.Column("geocoded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )

    # Facilities that already carry an address don't need geocoding — mark them done
    # so the worker never picks them up.
    op.execute("UPDATE instalaciones SET geocoded_at = now() WHERE direccion IS NOT NULL")

    # Partial index backing the worker's claim query (WHERE geocoded_at IS NULL).
    op.create_index(
        "ix_instalaciones_pending_geocode",
        "instalaciones",
        ["created_at"],
        postgresql_where=sa.text("geocoded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_instalaciones_pending_geocode", table_name="instalaciones")
    op.drop_column("instalaciones", "geocoded_at")
    op.drop_column("instalaciones", "lon")
    op.drop_column("instalaciones", "lat")
