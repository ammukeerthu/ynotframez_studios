"""Synchronize an admin password hash from local SQLite to the deployed database.

The plain-text password is never read or printed. Run without ``--apply`` to
compare the selected accounts, then add ``--apply`` to copy the local salt and
hash and invalidate existing sessions in the destination database.
"""

import argparse
import hmac
import os
from urllib.parse import urlsplit

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import normalize_database_url
from app.models.admin import AdminUser


LOCAL_DATABASE_URL = "sqlite:///./studio_bookings.db"


def _remote_label(database_url: str) -> str:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return f"remote PostgreSQL ({parsed.hostname or 'unknown host'})"


def sync_admin_password(*, username: str, apply: bool) -> None:
    remote_url = os.getenv("DATABASE_URL", "").strip()
    if not remote_url.startswith(("postgres://", "postgresql://")):
        raise ValueError("DATABASE_URL must contain the remote PostgreSQL connection string.")

    local_engine = create_engine(
        LOCAL_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    remote_engine = create_engine(
        normalize_database_url(remote_url),
        pool_pre_ping=True,
    )

    try:
        with Session(local_engine) as local_db, Session(remote_engine) as remote_db:
            local_user = local_db.scalar(
                select(AdminUser).where(AdminUser.username == username)
            )
            if local_user is None:
                raise ValueError(f"Local admin user '{username}' was not found.")

            remote_user = remote_db.scalar(
                select(AdminUser).where(AdminUser.username == username)
            )
            if remote_user is None:
                raise ValueError(f"Remote admin user '{username}' was not found.")

            matches = hmac.compare_digest(local_user.password_salt, remote_user.password_salt)
            matches = matches and hmac.compare_digest(
                local_user.password_hash,
                remote_user.password_hash,
            )

            print(f"Source: local SQLite admin '{username}'")
            print(f"Destination: {_remote_label(remote_url)} admin '{username}'")
            print(f"Password already synchronized: {'yes' if matches else 'no'}")

            if not apply:
                print("Dry run completed; nothing was changed. Add --apply to continue.")
                return

            if matches:
                print("No update was required.")
                return

            remote_user.password_salt = local_user.password_salt
            remote_user.password_hash = local_user.password_hash
            remote_user.session_version += 1
            remote_db.commit()
            print("Remote admin password synchronized and existing remote sessions invalidated.")
    finally:
        local_engine.dispose()
        remote_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy an admin password hash from local SQLite to the remote database."
    )
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--apply", action="store_true", help="Commit the remote password update")
    args = parser.parse_args()

    try:
        sync_admin_password(username=args.username, apply=args.apply)
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
