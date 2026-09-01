"""Synchronize an existing database with the committed studio defaults.

Run without ``--apply`` for a rollback-only dry run. Set DATABASE_URL in the
current process before running this script against a deployed database.
"""

import argparse

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.spaces import SPACES, overwrite_studio_settings_with_defaults


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the studio defaults. Without this flag, all changes are rolled back.",
    )
    args = parser.parse_args()

    database = make_url(settings.database_url)
    print(f"Database: {database.render_as_string(hide_password=True)}")
    print("Studios: " + ", ".join(space.name for space in SPACES.values()))

    with SessionLocal() as db:
        overwrite_studio_settings_with_defaults(db, commit=False)
        if args.apply:
            db.commit()
            print("Studio defaults synchronized successfully.")
        else:
            db.rollback()
            print("Dry run completed; no database changes were saved. Add --apply to commit them.")


if __name__ == "__main__":
    main()
