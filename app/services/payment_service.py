from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, PaymentMode
from app.models.payment import (
    PaymentRecord,
    PaymentStatus,
    PaymentTransaction,
    PaymentTransactionType,
)
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

    def transactions(self, booking_id: int) -> list[PaymentTransaction]:
        return list(
            self.db.scalars(
                select(PaymentTransaction)
                .where(PaymentTransaction.booking_id == booking_id)
                .order_by(PaymentTransaction.occurred_at, PaymentTransaction.id)
            )
        )

    def payment_total(self, booking_id: int) -> int:
        return sum(
            transaction.amount
            for transaction in self.transactions(booking_id)
            if transaction.transaction_type == PaymentTransactionType.PAYMENT
        )

    def refund_total(self, booking_id: int) -> int:
        return sum(
            transaction.amount
            for transaction in self.transactions(booking_id)
            if transaction.transaction_type == PaymentTransactionType.REFUND
        )

    def net_received(self, booking_id: int) -> int:
        return max(0, self.payment_total(booking_id) - self.refund_total(booking_id))

    def balance_due(self, booking_id: int, total_amount: int | None = None) -> int:
        record = self.get(booking_id)
        expected = total_amount if total_amount is not None else (record.amount if record else 0)
        return max(0, expected - self.payment_total(booking_id))

    def _has_payment_transaction(
        self,
        booking_id: int,
        *,
        razorpay_payment_id: str | None = None,
        provider_reference: str | None = None,
    ) -> bool:
        statement = select(PaymentTransaction.id).where(
            PaymentTransaction.booking_id == booking_id,
            PaymentTransaction.transaction_type == PaymentTransactionType.PAYMENT,
        )
        if razorpay_payment_id:
            statement = statement.where(
                PaymentTransaction.razorpay_payment_id == razorpay_payment_id.strip()
            )
        elif provider_reference:
            statement = statement.where(
                PaymentTransaction.provider_reference == provider_reference.strip()
            )
        else:
            return False
        return self.db.scalar(statement) is not None

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
        received = self.payment_total(booking.id)
        if record.status in {PaymentStatus.REFUND_DUE, PaymentStatus.REFUNDED, PaymentStatus.VOID}:
            raise PaymentLifecycleError(
                "This booking's payment lifecycle is closed and its price cannot be changed."
            )
        if new_amount < received:
            raise PaymentLifecycleError(
                "The new booking total cannot be lower than the amount already received."
            )
        record.mode = booking.payment_mode or record.mode
        record.amount = new_amount
        if received == 0:
            record.status = PaymentStatus.PENDING
        elif received < new_amount:
            record.status = PaymentStatus.PARTIALLY_PAID
        else:
            record.status = PaymentStatus.PAID
        return record

    def mark_paid(
        self,
        booking: Booking,
        provider_reference: str | None = None,
        *,
        razorpay_order_id: str | None = None,
        razorpay_payment_id: str | None = None,
        razorpay_method: str | None = None,
        payment_method: str | None = None,
        amount: int | None = None,
    ) -> PaymentRecord:
        record = self.ensure(booking)
        if record.status not in {PaymentStatus.PENDING, PaymentStatus.PARTIALLY_PAID}:
            raise PaymentLifecycleError("Only a pending or partially paid booking can receive payment.")
        normalized_reference = provider_reference.strip() if provider_reference else None
        normalized_payment_id = razorpay_payment_id.strip() if razorpay_payment_id else None
        if self._has_payment_transaction(
            booking.id,
            razorpay_payment_id=normalized_payment_id,
            provider_reference=normalized_reference,
        ):
            return record
        received = self.payment_total(booking.id)
        outstanding = max(0, record.amount - received)
        payment_amount = outstanding if amount is None else amount
        if payment_amount <= 0:
            raise PaymentLifecycleError("Payment amount must be greater than zero.")
        if payment_amount > outstanding:
            raise PaymentLifecycleError(
                f"Payment amount cannot exceed the outstanding balance of ₹{outstanding:,}."
            )
        record.mode = booking.payment_mode or record.mode
        record.provider_reference = normalized_reference
        if razorpay_order_id:
            record.razorpay_order_id = razorpay_order_id.strip()
        if razorpay_payment_id:
            record.razorpay_payment_id = razorpay_payment_id.strip()
        if razorpay_method:
            normalized_razorpay_method = razorpay_method.strip().lower()
            record.razorpay_method = normalized_razorpay_method
            record.payment_method = normalized_razorpay_method
        elif payment_method:
            record.payment_method = payment_method.strip().lower()
        occurred_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.add(
            PaymentTransaction(
                booking_id=booking.id,
                transaction_type=PaymentTransactionType.PAYMENT,
                amount=payment_amount,
                mode=record.mode,
                payment_method=record.payment_method,
                provider_reference=normalized_reference,
                razorpay_order_id=razorpay_order_id.strip() if razorpay_order_id else None,
                razorpay_payment_id=normalized_payment_id,
                occurred_at=occurred_at,
            )
        )
        record.status = (
            PaymentStatus.PAID
            if received + payment_amount >= record.amount
            else PaymentStatus.PARTIALLY_PAID
        )
        record.paid_at = occurred_at
        return record

    def mark_refund_due(
        self,
        booking: Booking,
        *,
        razorpay_order_id: str | None = None,
        razorpay_payment_id: str | None = None,
        razorpay_method: str | None = None,
    ) -> PaymentRecord:
        """Record captured money that cannot safely confirm its studio booking."""
        record = self.ensure(booking)
        normalized_payment_id = razorpay_payment_id.strip() if razorpay_payment_id else None
        if not self._has_payment_transaction(
            booking.id,
            razorpay_payment_id=normalized_payment_id,
            provider_reference=normalized_payment_id,
        ):
            received = self.payment_total(booking.id)
            captured_amount = max(0, record.amount - received)
            if captured_amount:
                occurred_at = datetime.now(UTC).replace(tzinfo=None)
                method = razorpay_method.strip().lower() if razorpay_method else record.payment_method
                self.db.add(
                    PaymentTransaction(
                        booking_id=booking.id,
                        transaction_type=PaymentTransactionType.PAYMENT,
                        amount=captured_amount,
                        mode=booking.payment_mode or record.mode,
                        payment_method=method,
                        provider_reference=normalized_payment_id,
                        razorpay_order_id=razorpay_order_id.strip() if razorpay_order_id else None,
                        razorpay_payment_id=normalized_payment_id,
                        occurred_at=occurred_at,
                    )
                )
        if record.status != PaymentStatus.REFUNDED:
            record.status = PaymentStatus.REFUND_DUE
        if razorpay_order_id:
            record.razorpay_order_id = razorpay_order_id.strip()
        if razorpay_payment_id:
            record.razorpay_payment_id = razorpay_payment_id.strip()
            record.provider_reference = razorpay_payment_id.strip()
        if razorpay_method:
            normalized_razorpay_method = razorpay_method.strip().lower()
            record.razorpay_method = normalized_razorpay_method
            record.payment_method = normalized_razorpay_method
        if record.paid_at is None:
            record.paid_at = datetime.now(UTC).replace(tzinfo=None)
        return record

    def handle_cancellation(self, booking: Booking) -> PaymentRecord:
        record = self.ensure(booking)
        if record.status == PaymentStatus.PENDING:
            record.status = PaymentStatus.VOID
        elif record.status in {PaymentStatus.PARTIALLY_PAID, PaymentStatus.PAID}:
            record.status = PaymentStatus.REFUND_DUE
        return record

    def void_pending(self, booking: Booking) -> PaymentRecord:
        """Close an unpaid payment record after its temporary studio hold expires."""
        record = self.ensure(booking)
        if record.status == PaymentStatus.PENDING:
            record.status = PaymentStatus.VOID
        return record

    def mark_refunded(self, booking: Booking, provider_reference: str | None = None) -> PaymentRecord:
        record = self.ensure(booking)
        if record.status != PaymentStatus.REFUND_DUE:
            raise PaymentLifecycleError("Only a refund-due payment can be marked as refunded.")
        record.status = PaymentStatus.REFUNDED
        refundable_amount = self.net_received(booking.id)
        if refundable_amount:
            self.db.add(
                PaymentTransaction(
                    booking_id=booking.id,
                    transaction_type=PaymentTransactionType.REFUND,
                    amount=refundable_amount,
                    mode=record.mode,
                    payment_method=record.payment_method,
                    provider_reference=provider_reference.strip() if provider_reference else None,
                    occurred_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        if provider_reference:
            record.provider_reference = provider_reference.strip()
        return record
