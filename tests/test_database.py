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
                        "id INTEGER PRIMARY KEY, booking_id INTEGER, amount INTEGER, "
                        "razorpay_method VARCHAR(40))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO payment_records "
                        "(id, booking_id, amount, razorpay_method) VALUES (1, 1, 2000, 'upi')"
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
            self.assertIn("payment_method", columns)
            self.assertTrue(indexes["ix_payment_records_razorpay_order_id"]["unique"])
            self.assertTrue(indexes["ix_payment_records_razorpay_payment_id"]["unique"])
            with engine.connect() as connection:
                method = connection.scalar(
                    text("SELECT payment_method FROM payment_records WHERE id = 1")
                )
            self.assertEqual(method, "upi")
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

    def test_existing_bookings_receive_derived_payment_flows(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE bookings ("
                        "id INTEGER PRIMARY KEY, state VARCHAR(40), terms_accepted VARCHAR(8), "
                        "payment_mode VARCHAR(40))"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE payment_records ("
                        "id INTEGER PRIMARY KEY, booking_id INTEGER, mode VARCHAR(40), "
                        "amount INTEGER, razorpay_method VARCHAR(40))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO bookings (id, state, terms_accepted, payment_mode) VALUES "
                        "(1, 'CONFIRMED', NULL, NULL), "
                        "(2, 'PAYMENT_PENDING', 'v1', NULL), "
                        "(3, 'CONFIRMED', 'v1', 'PAY_NOW')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO payment_records (id, booking_id, mode, amount) VALUES "
                        "(1, 1, 'PAY_NOW', 1000), (2, 2, 'PAY_AT_STUDIO', 2000)"
                    )
                )

            apply_schema_compatibility_updates(engine)
            apply_schema_compatibility_updates(engine)

            with engine.connect() as connection:
                booking_modes = dict(
                    connection.execute(
                        text("SELECT id, payment_mode FROM bookings ORDER BY id")
                    ).tuples().all()
                )
                payment_modes = dict(
                    connection.execute(
                        text("SELECT booking_id, mode FROM payment_records ORDER BY booking_id")
                    ).tuples().all()
                )
            self.assertEqual(
                booking_modes,
                {1: "PAY_AT_STUDIO", 2: "PAY_NOW", 3: "PAY_NOW"},
            )
            self.assertEqual(payment_modes, {1: "PAY_AT_STUDIO", 2: "PAY_NOW"})
        finally:
            engine.dispose()

    def test_existing_payments_are_backfilled_into_the_transaction_ledger_once(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE bookings ("
                        "id INTEGER PRIMARY KEY, payment_mode VARCHAR(40), state VARCHAR(40), "
                        "terms_accepted VARCHAR(8))"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE payment_records ("
                        "id INTEGER PRIMARY KEY, booking_id INTEGER, mode VARCHAR(40), "
                        "amount INTEGER, status VARCHAR(40), provider_reference VARCHAR(180), "
                        "razorpay_order_id VARCHAR(180), razorpay_payment_id VARCHAR(180), "
                        "razorpay_method VARCHAR(40), payment_method VARCHAR(40), "
                        "paid_at DATETIME, created_at DATETIME, updated_at DATETIME)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO bookings "
                        "(id, payment_mode, state, terms_accepted) VALUES "
                        "(1, 'PAY_NOW', 'CONFIRMED', 'v1'), "
                        "(2, 'PAY_AT_STUDIO', 'CANCELLED', NULL)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO payment_records ("
                        "id, booking_id, mode, amount, status, provider_reference, "
                        "razorpay_order_id, razorpay_payment_id, payment_method, "
                        "paid_at, created_at, updated_at) VALUES "
                        "(1, 1, 'PAY_NOW', 2000, 'PAID', 'pay_original', "
                        "'order_original', 'pay_original', 'upi', "
                        "'2026-09-01 10:00:00', '2026-09-01 09:55:00', '2026-09-01 10:00:00'), "
                        "(2, 2, 'PAY_AT_STUDIO', 3000, 'REFUNDED', 'refund_original', "
                        "NULL, NULL, 'bank_transfer', "
                        "'2026-09-02 10:00:00', '2026-09-02 09:55:00', '2026-09-03 10:00:00')"
                    )
                )

            apply_schema_compatibility_updates(engine)
            apply_schema_compatibility_updates(engine)

            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT booking_id, transaction_type, amount, provider_reference "
                        "FROM payment_transactions ORDER BY booking_id, id"
                    )
                ).tuples().all()
                migration_count = connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM app_migrations "
                        "WHERE migration_key = 'backfill_payment_transaction_ledger'"
                    )
                )
            self.assertEqual(
                rows,
                [
                    (1, "PAYMENT", 2000, "pay_original"),
                    (2, "PAYMENT", 3000, None),
                    (2, "REFUND", 3000, "refund_original"),
                ],
            )
            self.assertEqual(migration_count, 1)
        finally:
            engine.dispose()

    def test_existing_default_minimum_is_migrated_to_one_hour_once(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE studio_settings ("
                        "id VARCHAR(64) PRIMARY KEY, min_duration_hours FLOAT NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO studio_settings (id, min_duration_hours) VALUES "
                        "('standard_small', 2), ('premium_large', 1.5)"
                    )
                )

            apply_schema_compatibility_updates(engine)
            with engine.connect() as connection:
                minimums = dict(
                    connection.execute(
                        text("SELECT id, min_duration_hours FROM studio_settings")
                    ).tuples().all()
                )
            self.assertEqual(minimums, {"standard_small": 1.0, "premium_large": 1.5})

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE studio_settings SET min_duration_hours = 2 "
                        "WHERE id = 'standard_small'"
                    )
                )
            apply_schema_compatibility_updates(engine)
            with engine.connect() as connection:
                owner_selected_minimum = connection.scalar(
                    text(
                        "SELECT min_duration_hours FROM studio_settings "
                        "WHERE id = 'standard_small'"
                    )
                )
            self.assertEqual(owner_selected_minimum, 2.0)
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
