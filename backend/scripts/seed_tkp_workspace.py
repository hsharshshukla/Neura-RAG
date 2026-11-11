from __future__ import annotations

import argparse
from uuid import UUID

from sqlmodel import Session, select

from app.db import engine
from app.models import User, Workspace, WorkspaceMembership


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grant explicit reader membership in the isolated TKP staging workspace."
    )
    parser.add_argument("workspace_id", type=UUID)
    parser.add_argument("workspace_name")
    parser.add_argument("emails", nargs="+")
    args = parser.parse_args()

    workspace_id = str(args.workspace_id)
    with Session(engine) as db:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            workspace = Workspace(id=workspace_id, name=args.workspace_name, active=True)
            db.add(workspace)
        for raw_email in args.emails:
            email = raw_email.strip().lower()
            user = db.exec(select(User).where(User.email == email)).first()
            if user is None:
                raise SystemExit(f"Unknown Neura user: {email}")
            membership = db.exec(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == user.id,
                )
            ).first()
            if membership is None:
                db.add(
                    WorkspaceMembership(
                        workspace_id=workspace_id,
                        user_id=user.id,
                        role="reader",
                        active=True,
                    )
                )
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
