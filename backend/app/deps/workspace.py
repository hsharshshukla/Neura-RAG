from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps.auth import get_current_user_obj
from app.integrations.tkp.config import TKPSettings, get_tkp_settings
from app.models import User, Workspace, WorkspaceMembership


@dataclass(frozen=True)
class WorkspaceAccess:
    user: User
    workspace_id: UUID
    role: str


def require_tkp_workspace_access(
    user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_session),
    settings: TKPSettings = Depends(get_tkp_settings),
) -> WorkspaceAccess:
    workspace_id = str(settings.staging_workspace_id)
    membership = db.exec(
        select(WorkspaceMembership)
        .join(Workspace, col(Workspace.id) == col(WorkspaceMembership.workspace_id))
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
            col(WorkspaceMembership.active).is_(True),
            col(Workspace.active).is_(True),
        )
    ).first()
    if membership is None or membership.role.lower() not in {
        "reader",
        "admin",
        "owner",
    }:
        # Do not reveal whether the configured workspace or a membership exists.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Knowledge workspace access denied",
        )
    return WorkspaceAccess(
        user=user,
        workspace_id=settings.staging_workspace_id,
        role=membership.role.lower(),
    )
