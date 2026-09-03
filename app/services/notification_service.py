from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.notification import AdminNotification


def notify_new_booking(db: Session, booking: Booking) -> AdminNotification:
    existing = db.scalar(
        select(AdminNotification).where(AdminNotification.booking_id == booking.id)
    )
    if existing is not None:
        return existing

    notification = AdminNotification(booking_id=booking.id, kind="new_booking")
    db.add(notification)
    return notification


def notify_payment_issue(db: Session, booking: Booking) -> AdminNotification:
    """Surface captured payments that need an owner decision or refund."""
    existing = db.scalar(
        select(AdminNotification).where(AdminNotification.booking_id == booking.id)
    )
    if existing is not None:
        if existing.kind == "payment_issue":
            return existing
        existing.kind = "payment_issue"
        existing.read_at = None
        return existing

    notification = AdminNotification(booking_id=booking.id, kind="payment_issue")
    db.add(notification)
    return notification
