from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.booking_rules import CURRENT_TERMS_VERSION
from app.core.config import settings


def normalize_database_url(database_url: str) -> str:
    """Select Psycopg 3 for provider-issued PostgreSQL connection strings."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


database_url = normalize_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args}
if not database_url.startswith("sqlite"):
    # Neon can suspend an idle compute. Validate pooled connections before use
    # so the first request after wake-up transparently replaces a stale one.
    engine_options["pool_pre_ping"] = True

engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def apply_schema_compatibility_updates(target_engine: Engine | None = None) -> None:
    """Apply the small additive migrations required by existing MVP databases."""
    migration_engine = target_engine or engine
    transaction_table = Base.metadata.tables.get("payment_transactions")
    if transaction_table is not None:
        transaction_table.create(bind=migration_engine, checkfirst=True)
    inspector = inspect(migration_engine)
    table_names = set(inspector.get_table_names())
    if migration_engine.dialect.name == "postgresql" and "bookings" in table_names:
        # SQLAlchemy stores Python Enum member names in PostgreSQL's native enum.
        # This DDL must commit before application requests can write the new value.
        with migration_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("ALTER TYPE bookingstate ADD VALUE IF NOT EXISTS 'EXPIRED'"))
            if "payment_records" in table_names:
                connection.execute(
                    text("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'PARTIALLY_PAID'")
                )
    if "admin_users" in table_names:
        admin_columns = {column["name"] for column in inspector.get_columns("admin_users")}
        if "role" not in admin_columns:
            with migration_engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE admin_users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'owner'")
                )
    if "studio_settings" in table_names:
        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS app_migrations ("
                    "migration_key VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            migration_key = "studio_minimum_duration_1_hour"
            claimed = connection.execute(
                text(
                    "INSERT INTO app_migrations (migration_key) VALUES (:migration_key) "
                    "ON CONFLICT (migration_key) DO NOTHING"
                ),
                {"migration_key": migration_key},
            )
            if claimed.rowcount:
                connection.execute(
                    text(
                        "UPDATE studio_settings SET min_duration_hours = 1 "
                        "WHERE min_duration_hours = 2"
                    )
                )
    if "bookings" in table_names:
        booking_columns = {column["name"] for column in inspector.get_columns("bookings")}
        with migration_engine.begin() as connection:
            if "expiration_reminder_sent_at" not in booking_columns:
                connection.execute(
                    text(
                        "ALTER TABLE bookings "
                        "ADD COLUMN expiration_reminder_sent_at TIMESTAMP"
                    )
                )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS app_migrations ("
                    "migration_key VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            migration_key = "classify_existing_booking_payment_flows"
            claimed = connection.execute(
                text(
                    "INSERT INTO app_migrations (migration_key) VALUES (:migration_key) "
                    "ON CONFLICT (migration_key) DO NOTHING"
                ),
                {"migration_key": migration_key},
            )
            if claimed.rowcount:
                connection.execute(
                    text(
                        "UPDATE bookings SET payment_mode = 'PAY_NOW' "
                        "WHERE payment_mode IS NULL AND terms_accepted IS NOT NULL "
                        "AND state IN ('PAYMENT_PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED')"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE bookings SET payment_mode = 'PAY_AT_STUDIO' "
                        "WHERE payment_mode IS NULL AND terms_accepted IS NULL "
                        "AND state IN ('CONFIRMED', 'CANCELLED')"
                    )
                )
            migration_key = "accept_terms_for_existing_offline_bookings"
            claimed = connection.execute(
                text(
                    "INSERT INTO app_migrations (migration_key) VALUES (:migration_key) "
                    "ON CONFLICT (migration_key) DO NOTHING"
                ),
                {"migration_key": migration_key},
            )
            if claimed.rowcount:
                connection.execute(
                    text(
                        "UPDATE bookings SET terms_accepted = :terms_version "
                        "WHERE terms_accepted IS NULL AND payment_mode = 'PAY_AT_STUDIO' "
                        "AND state IN ('CONFIRMED', 'CANCELLED')"
                    ),
                    {"terms_version": CURRENT_TERMS_VERSION},
                )
            if {"space_id", "purpose"} <= booking_columns:
                migration_key = "rename_arena_family_shoots_booking_purpose"
                claimed = connection.execute(
                    text(
                        "INSERT INTO app_migrations (migration_key) VALUES (:migration_key) "
                        "ON CONFLICT (migration_key) DO NOTHING"
                    ),
                    {"migration_key": migration_key},
                )
                if claimed.rowcount:
                    connection.execute(
                        text(
                            "UPDATE bookings SET purpose = 'Family Portraits' "
                            "WHERE space_id = 'premium_large' AND purpose = 'Family Shoots'"
                        )
                    )
    if "availability_blocks" in table_names:
        block_columns = {
            column["name"] for column in inspector.get_columns("availability_blocks")
        }
        if "calendar_event_id" not in block_columns:
            with migration_engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE availability_blocks "
                        "ADD COLUMN calendar_event_id VARCHAR(120)"
                    )
                )
    if "payment_records" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("payment_records")}
    additions = {
        "razorpay_order_id": "VARCHAR(180)",
        "razorpay_payment_id": "VARCHAR(180)",
        "razorpay_method": "VARCHAR(40)",
        "payment_method": "VARCHAR(40)",
    }
    with migration_engine.begin() as connection:
        for name, sql_type in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE payment_records ADD COLUMN {name} {sql_type}"))
        connection.execute(
            text(
                "UPDATE payment_records SET payment_method = razorpay_method "
                "WHERE payment_method IS NULL AND razorpay_method IS NOT NULL"
            )
        )
        if "bookings" in table_names:
            connection.execute(
                text(
                    "UPDATE payment_records SET mode = ("
                    "SELECT bookings.payment_mode FROM bookings "
                    "WHERE bookings.id = payment_records.booking_id) "
                    "WHERE EXISTS (SELECT 1 FROM bookings "
                    "WHERE bookings.id = payment_records.booking_id "
                    "AND bookings.payment_mode IS NOT NULL)"
                )
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_records_razorpay_order_id "
                "ON payment_records (razorpay_order_id)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_records_razorpay_payment_id "
                "ON payment_records (razorpay_payment_id)"
            )
        )
        effective_columns = columns | set(additions)
        ledger_source_columns = {
            "booking_id",
            "mode",
            "amount",
            "status",
            "provider_reference",
            "razorpay_order_id",
            "razorpay_payment_id",
            "payment_method",
            "paid_at",
            "created_at",
            "updated_at",
        }
        if "payment_transactions" in table_names and ledger_source_columns <= effective_columns:
            migration_key = "backfill_payment_transaction_ledger"
            claimed = connection.execute(
                text(
                    "INSERT INTO app_migrations (migration_key) VALUES (:migration_key) "
                    "ON CONFLICT (migration_key) DO NOTHING"
                ),
                {"migration_key": migration_key},
            )
            if claimed.rowcount:
                connection.execute(
                    text(
                        "INSERT INTO payment_transactions ("
                        "booking_id, transaction_type, amount, mode, payment_method, "
                        "provider_reference, razorpay_order_id, razorpay_payment_id, "
                        "occurred_at, created_at) "
                        "SELECT booking_id, 'PAYMENT', amount, mode, payment_method, "
                        "CASE WHEN status = 'REFUNDED' THEN NULL ELSE provider_reference END, "
                        "razorpay_order_id, razorpay_payment_id, "
                        "COALESCE(paid_at, updated_at, created_at), "
                        "COALESCE(paid_at, updated_at, created_at) "
                        "FROM payment_records "
                        "WHERE status IN ('PAID', 'REFUND_DUE', 'REFUNDED')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO payment_transactions ("
                        "booking_id, transaction_type, amount, mode, payment_method, "
                        "provider_reference, occurred_at, created_at) "
                        "SELECT booking_id, 'REFUND', amount, mode, payment_method, "
                        "provider_reference, COALESCE(updated_at, created_at), "
                        "COALESCE(updated_at, created_at) "
                        "FROM payment_records WHERE status = 'REFUNDED'"
                    )
                )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

