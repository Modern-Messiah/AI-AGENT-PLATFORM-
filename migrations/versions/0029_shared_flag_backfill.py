"""backfill is_shared for owner-NULL rows; sharing is flag-only

Revision ID: 0029_shared_flag_backfill
Revises: 0028_per_user_knowledge_base
Create Date: 2026-10-01

0028 treated owner_user_id IS NULL as "tenant-shared" so pre-existing
documents stayed visible to everyone. That rule has a hole: users.owner
FKs are ON DELETE SET NULL, so deleting a person would silently flip
their private documents to tenant-shared.

From now on sharing is decided by is_shared alone:
- legacy owner-NULL rows are backfilled to is_shared = true here;
- owner set + is_shared = false → private to the owner;
- owner NULL + is_shared = false → orphaned private document (e.g. its
  owner was deleted): invisible to members, still reachable by unbound
  tenant keys and admins.

No schema change — a data backfill plus the matching access-rule update
in apps/api/services/access.py.
"""

from alembic import op

revision: str = "0029_shared_flag_backfill"
down_revision: str | None = "0028_per_user_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE documents SET is_shared = true WHERE owner_user_id IS NULL AND NOT is_shared"
    )
    op.execute(
        "UPDATE notebooks SET is_shared = true WHERE owner_user_id IS NULL AND NOT is_shared"
    )


def downgrade() -> None:
    # Orphaned rows would become tenant-shared again under the 0028 rule;
    # only un-share rows that never had an owner (the 0028-era population).
    op.execute("UPDATE notebooks SET is_shared = false WHERE owner_user_id IS NULL AND is_shared")
    op.execute("UPDATE documents SET is_shared = false WHERE owner_user_id IS NULL AND is_shared")
