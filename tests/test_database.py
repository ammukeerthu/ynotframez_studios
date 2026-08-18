import unittest

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.core.database import Base, normalize_database_url
from app.models import admin, availability, booking, notification, payment, studio  # noqa: F401


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


if __name__ == "__main__":
    unittest.main()
