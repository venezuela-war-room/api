"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "unaccent"')

    op.create_table(
        "hospitals",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )

    op.create_table(
        "servicios",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("hospital_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hospital_id", "normalized_name", name="uq_servicio_hospital"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("team_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )

    op.create_table(
        "found_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("hospital_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("servicio_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lugar_procedencia", sa.String(), nullable=True),
        sa.Column("relevant_info", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="verified", nullable=False),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"]),
        sa.ForeignKeyConstraint(["servicio_id"], ["servicios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_hash"),
    )

    op.create_index("idx_found_people_document_id", "found_people", ["document_id"])
    op.create_index("idx_found_people_status", "found_people", ["status"])
    op.create_index("idx_found_people_updated_at", "found_people", [sa.text("updated_at DESC")])
    op.create_index("idx_found_people_hospital_id", "found_people", ["hospital_id"])
    op.create_index("idx_found_people_api_key_id", "found_people", ["api_key_id"])
    op.create_index(
        "idx_found_people_full_name_trgm",
        "found_people",
        [sa.text("full_name gin_trgm_ops")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("found_people")
    op.drop_table("api_keys")
    op.drop_table("servicios")
    op.drop_table("hospitals")
    op.execute('DROP EXTENSION IF EXISTS "unaccent"')
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
