import unittest

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.core.database import Base, normalize_database_url
from app.models import admin, availability, booking, notification, payment, studio  # noqa: F401
from app.models.studio import StudioPurposeOption, StudioSetting
from app.services.spaces import seed_studio_settings


class DatabaseConfigurationTests(unittest.TestCase):
    def test_neon_url_uses_psycopg_three(self) -> None:
        url = "postgresql://studio:secret@example.neon.tech/studio?sslmode=require"

        self.assertEqual(
            normalize_database_url(url),
            "postgresql+psycopg://studio:secret@example.neon.tech/studio?sslmode=require",
        )

    def test_legacy_postgres_url_uses_psycopg_three(self) -> None:
        self.assertEqual(
            normalize_database_url("postgres://studio:secret@db.example/studio"),
            "postgresql+psycopg://studio:secret@db.example/studio",
        )

    def test_sqlite_url_is_unchanged(self) -> None:
        self.assertEqual(
            normalize_database_url("sqlite:///./studio_bookings.db"),
            "sqlite:///./studio_bookings.db",
        )

    def test_models_compile_for_postgresql(self) -> None:
        dialect = postgresql.dialect()
        for table in Base.metadata.sorted_tables:
            statement = str(CreateTable(table).compile(dialect=dialect))
            self.assertIn("CREATE TABLE", statement)

    def test_seed_orders_studios_before_foreign_key_purpose_options(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                seed_studio_settings(db)
                self.assertEqual(db.scalar(select(func.count()).select_from(StudioSetting)), 2)
                self.assertEqual(db.scalar(select(func.count()).select_from(StudioPurposeOption)), 16)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
