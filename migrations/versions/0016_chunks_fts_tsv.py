"""full-text search column on chunks for hybrid retrieval

Revision ID: 0016_chunks_fts_tsv
Revises: 0014_chunk_unique_constraint
Create Date: 2026-09-18

Adds a stored generated tsvector column combining 'simple' (exact tokens,
identifiers, codes) and 'russian' (morphology) lexemes, plus a GIN index.
The table rewrite happens in-place; chunks stay untouched.
"""

from alembic import op

revision: str = "0016_chunks_fts_tsv"
down_revision: str | None = "0014_chunk_unique_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content) "
        "|| to_tsvector('russian', content)) STORED"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
