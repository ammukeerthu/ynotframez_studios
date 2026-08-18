r"""Offline password recovery for the local Studio Dashboard.

Run from the project root with:

    .\.venv\Scripts\python.exe -m scripts.reset_admin_password

The password and confirmation are read with ``getpass``, so they are not shown
on screen or saved in terminal history. Only the selected admin user's salted
password hash and session version are changed; bookings and studio data are
left untouched.
"""

import argparse
from getpass import getpass

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.admin import AdminUser
from app.services.admin_auth import hash_admin_password


def reset_password(username: str, new_password: str) -> None:
    """Replace one admin user's password hash and invalidate signed sessions."""
    if len(new_password) < 10:
        raise ValueError("The new password must contain at least 10 characters.")
    if len(new_password) > 500:
        raise ValueError("The new password is too long.")

    with SessionLocal() as db:
        user = db.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            raise ValueError(f"Admin user '{username}' was not found.")

        # Store a newly salted one-way hash. The plain password is never saved.
        salt, password_hash = hash_admin_password(new_password)
        user.password_salt = salt
        user.password_hash = password_hash
        # Existing cookies contain the previous version and become invalid.
        user.session_version += 1
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the local Studio Dashboard password.")
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    args = parser.parse_args()

    password = getpass("New dashboard password: ")
    confirmation = getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match. Nothing was changed.")

    try:
        reset_password(args.username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    print(f"Password reset for '{args.username}'. Existing dashboard sessions were signed out.")


if __name__ == "__main__":
    main()
