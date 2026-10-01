from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, utc_now
from app.models.notification import AdminNotification


def _upsert_booking_notification(
    db: Session,
    booking: Booking,
    kind: str,
    *,
    mark_unread_on_change: bool = True,
) -> AdminNotification:
    existing = db.scalar(
        select(AdminNotification).where(AdminNotification.booking_id == booking.id)
    )
    if existing is not None:
        if existing.kind != kind:
            existing.kind = kind
            existing.created_at = utc_now()
            if mark_unread_on_change:
                existing.read_at = None
        return existing

    notification = AdminNotification(booking_id=booking.id, kind=kind)
    db.add(notification)
    return notification


def notify_booking_request(db: Session, booking: Booking) -> AdminNotification:
    """Alert the dashboard after a payment hold and its Calendar event are stored."""
    return _upsert_booking_notification(db, booking, "booking_request")


def notify_new_booking(db: Session, booking: Booking) -> AdminNotification:
    return _upsert_booking_notification(db, booking, "new_booking")


def notify_booking_expired(db: Session, booking: Booking) -> AdminNotification:
    """Bring an expired unpaid hold back to the owner's attention."""
    return _upsert_booking_notification(db, booking, "booking_expired")


def notify_payment_issue(db: Session, booking: Booking) -> AdminNotification:
    """Surface captured payments that need an owner decision or refund."""
    return _upsert_booking_notification(db, booking, "payment_issue")
