import unittest

from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.core.database import Base, apply_schema_compatibility_updates, normalize_database_url
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

    def test_payment_columns_are_added_to_an_existing_database(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE payment_records ("
                        "id INTEGER PRIMARY KEY, booking_id INTEGER, amount INTEGER)"
                    )
                )

            apply_schema_compatibility_updates(engine)
            apply_schema_compatibility_updates(engine)

            inspector = inspect(engine)
            columns = {column["name"] for column in inspector.get_columns("payment_records")}
            indexes = {index["name"]: index for index in inspector.get_indexes("payment_records")}
            self.assertIn("razorpay_order_id", columns)
            self.assertIn("razorpay_payment_id", columns)
            self.assertIn("razorpay_method", columns)
            self.assertTrue(indexes["ix_payment_records_razorpay_order_id"]["unique"])
            self.assertTrue(indexes["ix_payment_records_razorpay_payment_id"]["unique"])
        finally:
            engine.dispose()

    def test_existing_admin_users_are_migrated_as_owners(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE admin_users ("
                        "id INTEGER PRIMARY KEY, username VARCHAR(120), password_salt VARCHAR(64), "
                        "password_hash VARCHAR(128), session_version INTEGER, "
                        "created_at DATETIME, updated_at DATETIME)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO admin_users "
                        "(id, username, password_salt, password_hash, session_version) "
                        "VALUES (1, 'owner', 'salt', 'hash', 1)"
                    )
                )

            apply_schema_compatibility_updates(engine)
            apply_schema_compatibility_updates(engine)

            columns = {column["name"] for column in inspect(engine).get_columns("admin_users")}
            with engine.connect() as connection:
                role = connection.scalar(text("SELECT role FROM admin_users WHERE id = 1"))
            self.assertIn("role", columns)
            self.assertEqual(role, "owner")
        finally:
            engine.dispose()

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
                self.assertEqual(db.scalar(select(func.count()).select_from(StudioPurposeOption)), 23)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
