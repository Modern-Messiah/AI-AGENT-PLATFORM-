"""Per-user knowledge-base access rules.

Documents and notebooks are tenant-scoped by RLS; on top of that, sharing
is decided by is_shared alone (migration 0029 backfilled legacy owner-NULL
rows to is_shared=true, so an owner FK nulled by user deletion yields an
invisible orphan instead of a tenant-shared document). Unbound tenant API
keys (user_id is None — operational scripts, reindex, evals) keep full
tenant access, matching the Actor.can_destroy convention.
"""

from __future__ import annotations

import uuid

from packages.auth import Actor
from packages.storage import Document, DocumentStatus, Notebook
from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


def _owner_condition(
    model: type[Document] | type[Notebook], user_id: uuid.UUID
) -> ColumnElement[bool]:
    return or_(
        model.owner_user_id == user_id,
        model.is_shared.is_(True),
    )


def accessible_condition(
    model: type[Document] | type[Notebook], actor: Actor
) -> ColumnElement[bool] | None:
    """SQL condition for rows the actor may see; None = no extra filtering."""
    if actor.user_id is None:
        return None
    return _owner_condition(model, actor.user_id)


def scope_condition(
    model: type[Document] | type[Notebook],
    actor: Actor,
    scope: str,
) -> ColumnElement[bool] | None:
    """List filter for ?scope=mine|shared|all (all = everything accessible)."""
    if scope == "mine":
        # An unbound key has no personal documents.
        if actor.user_id is None:
            return false()
        return model.owner_user_id == actor.user_id
    if scope == "shared":
        return model.is_shared.is_(True)
    return accessible_condition(model, actor)


def can_access(actor: Actor, resource: Document | Notebook) -> bool:
    if actor.user_id is None:
        return True
    owner_id = getattr(resource, "owner_user_id", None)
    return owner_id == actor.user_id or bool(resource.is_shared)


def can_manage(actor: Actor, resource: Document | Notebook) -> bool:
    """Who may delete/modify: unbound keys, admins, and the owner.

    Extends Actor.can_destroy (which gates shared data) so members can
    manage their own private documents.
    """
    if actor.user_id is None or actor.is_admin:
        return True
    return getattr(resource, "owner_user_id", None) == actor.user_id


async def accessible_document_ids(
    db: AsyncSession,
    tenant_id: str,
    actor: Actor,
    *,
    done_only: bool = True,
) -> list[uuid.UUID] | None:
    """Retrieval scope for the actor: None = whole tenant (unbound key).

    Only indexed documents matter for retrieval, hence done_only by default.
    """
    if actor.user_id is None:
        return None
    stmt = select(Document.id).where(
        Document.tenant_id == tenant_id,
        _owner_condition(Document, actor.user_id),
    )
    if done_only:
        stmt = stmt.where(Document.status == DocumentStatus.done)
    return list((await db.execute(stmt)).scalars().all())
