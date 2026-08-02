from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, PaymentMode
from app.models.payment import PaymentRecord, PaymentStatus
from app.services.spaces import get_space_by_id


class PaymentLifecycleError(ValueError):
    pass


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def amount_for(self, booking: Booking) -> int:
        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        return int(round((space.hourly_rate if space else 0) * (booking.duration_hours or 0)))

    def get(self, booking_id: int) -> PaymentRecord | None:
        return self.db.scalar(select(PaymentRecord).where(PaymentRecord.booking_id == booking_id))

    def ensure(self, booking: Booking) -> PaymentRecord:
        if booking.id is None:
            self.db.flush()
        record = self.get(booking.id)
        if record is None:
            record = PaymentRecord(
                booking_id=booking.id,
                mode=booking.payment_mode or PaymentMode.PAY_AT_STUDIO,
                amount=self.amount_for(booking),
                status=PaymentStatus.PENDING,
            )
            self.db.add(record)
            self.db.flush()
        return record

    def sync_pending_amount(self, booking: Booking) -> PaymentRecord:
        record = self.ensure(booking)
        new_amount = self.amount_for(booking)
        if record.amount != new_amount and record.status != PaymentStatus.PENDING:
            raise PaymentLifecycleError(
                "This booking already has payment activity. Mark the required refund before changing its price."
            )
        record.mode = booking.payment_mode or record.mode
        record.amount = new_amount
        return record

    def mark_paid(self, booking: Booking, provider_reference: str | None = None) -> PaymentRecord:
        record = self.ensure(booking)
        if record.status != PaymentStatus.PENDING:
            raise PaymentLifecycleError("Only a pending payment can be marked as paid.")
        record.status = PaymentStatus.PAID
        record.provider_reference = provider_reference.strip() if provider_reference else None
        record.paid_at = datetime.now(UTC).replace(tzinfo=None)
        return record

    def handle_cancellation(self, booking: Booking) -> PaymentRecord:
        record = self.ensure(booking)
        if record.status == PaymentStatus.PENDING:
            record.status = PaymentStatus.VOID
        elif record.status == PaymentStatus.PAID:
            record.status = PaymentStatus.REFUND_DUE
        return record

    def mark_refunded(self, booking: Booking, provider_reference: str | None = None) -> PaymentRecord:
        record = self.ensure(booking)
        if record.status != PaymentStatus.REFUND_DUE:
            raise PaymentLifecycleError("Only a refund-due payment can be marked as refunded.")
        record.status = PaymentStatus.REFUNDED
        if provider_reference:
            record.provider_reference = provider_reference.strip()
        return record
