from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.booking import PaymentMode, utc_now


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REFUND_DUE = "refund_due"
    REFUNDED = "refunded"
    VOID = "void"


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    booking_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    provider_reference: Mapped[str | None] = mapped_column(String(180), nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(
        String(180), nullable=True, unique=True, index=True
    )
    razorpay_payment_id: Mapped[str | None] = mapped_column(
        String(180), nullable=True, unique=True, index=True
    )
    razorpay_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class PaymentTransactionType(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    booking_id: Mapped[int] = mapped_column(Integer, index=True)
    transaction_type: Mapped[PaymentTransactionType] = mapped_column(Enum(PaymentTransactionType))
    amount: Mapped[int] = mapped_column(Integer)
    mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode))
    payment_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
