from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BookingState(StrEnum):
    SELECT_SPACE = "select_space"
    SHOW_DETAILS = "show_details"
    SHOW_RULES = "show_rules"
    ASK_SCHEDULE = "ask_schedule"
    ASK_NAME = "ask_name"
    ASK_EMAIL = "ask_email"
    ASK_PURPOSE = "ask_purpose"
    ASK_TERMS = "ask_terms"
    ASK_PAYMENT_MODE = "ask_payment_mode"
    PAYMENT_PENDING = "payment_pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class PaymentMode(StrEnum):
    PAY_NOW = "pay_now"
    PAY_AT_STUDIO = "pay_at_studio"


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[BookingState] = mapped_column(Enum(BookingState), default=BookingState.SELECT_SPACE)
    space_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    booking_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    duration_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_accepted: Mapped[str | None] = mapped_column(String(8), nullable=True)
    payment_mode: Mapped[PaymentMode | None] = mapped_column(Enum(PaymentMode), nullable=True)
    payment_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

