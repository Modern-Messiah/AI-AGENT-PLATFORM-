"""resize embedding vector 1024 -> 384 (bge-small-en-v1.5)

Revision ID: 0003
Revises: 0002_rls_api_keys
Create Date: 2026-04-29
"""

from alembic import op

revision = "0003"
down_revision = "0002_rls_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DELETE FROM chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(384)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DELETE FROM chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
