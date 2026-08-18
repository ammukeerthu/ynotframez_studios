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
