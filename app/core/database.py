from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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
    inspector = inspect(migration_engine)
    if migration_engine.dialect.name == "postgresql" and "bookings" in inspector.get_table_names():
        # SQLAlchemy stores Python Enum member names in PostgreSQL's native enum.
        # This DDL must commit before application requests can write the new value.
        with migration_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("ALTER TYPE bookingstate ADD VALUE IF NOT EXISTS 'EXPIRED'"))
    if "admin_users" in inspector.get_table_names():
        admin_columns = {column["name"] for column in inspector.get_columns("admin_users")}
        if "role" not in admin_columns:
            with migration_engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE admin_users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'owner'")
                )
    if "payment_records" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("payment_records")}
    additions = {
        "razorpay_order_id": "VARCHAR(180)",
        "razorpay_payment_id": "VARCHAR(180)",
        "razorpay_method": "VARCHAR(40)",
    }
    with migration_engine.begin() as connection:
        for name, sql_type in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE payment_records ADD COLUMN {name} {sql_type}"))
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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

