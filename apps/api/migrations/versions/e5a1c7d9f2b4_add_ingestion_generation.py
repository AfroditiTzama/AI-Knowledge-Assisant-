"""add ingestion generation and active-job constraint

Revision ID: e5a1c7d9f2b4
Revises: d4e8f1a2b3c4
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a1c7d9f2b4"
down_revision: str | None = "d4e8f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "active_ingestion_generation",
                sa.Uuid(),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_documents_active_ingestion_generation",
            ["active_ingestion_generation"],
            unique=False,
        )

    op.execute(
        sa.text(
            "UPDATE documents "
            "SET active_ingestion_generation = "
            "'00000000000000000000000000000000' "
            "WHERE EXISTS ("
            "SELECT 1 FROM document_chunks "
            "WHERE document_chunks.document_id = documents.id"
            ")"
        )
    )

    op.execute(
        sa.text(
            "UPDATE processing_jobs AS job "
            "SET status = 'FAILED', "
            "error_message = 'Superseded during ingestion safety migration' "
            "WHERE status IN ('QUEUED', 'RUNNING') "
            "AND EXISTS ("
            "SELECT 1 FROM processing_jobs AS newer "
            "WHERE newer.document_id = job.document_id "
            "AND newer.status IN ('QUEUED', 'RUNNING') "
            "AND (newer.created_at > job.created_at "
            "OR (newer.created_at = job.created_at AND newer.id > job.id))"
            ")"
        )
    )
    op.create_index(
        "uq_processing_jobs_active_document",
        "processing_jobs",
        ["document_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_processing_jobs_active_document",
        table_name="processing_jobs",
    )
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_active_ingestion_generation")
        batch_op.drop_column("active_ingestion_generation")
