from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.availability import AvailabilityBlock
from app.models.booking import Booking, BookingState
from app.core.config import settings


def interval_for(booking_date: date, start_time: time, duration_hours: float) -> tuple[datetime, datetime]:
    start = datetime.combine(booking_date, start_time)
    return start, start + timedelta(hours=duration_hours)


def intervals_overlap(
    requested_start: datetime,
    requested_end: datetime,
    existing_start: datetime,
    existing_end: datetime,
) -> bool:
    return requested_start < existing_end and existing_start < requested_end


def overlapping_block(
    db: Session,
    space_id: str,
    booking_date: date,
    requested_start: datetime,
    requested_end: datetime,
    blocks: Iterable[AvailabilityBlock] | None = None,
) -> AvailabilityBlock | None:
    matching_blocks = blocks
    if matching_blocks is None:
        statement = select(AvailabilityBlock).where(
            AvailabilityBlock.space_id == space_id,
            AvailabilityBlock.booking_date == booking_date.isoformat(),
        )
        matching_blocks = db.scalars(statement)
    for block in matching_blocks:
        block_start, block_end = interval_for(
            date.fromisoformat(block.booking_date),
            time.fromisoformat(block.start_time),
            block.duration_hours,
        )
        if intervals_overlap(requested_start, requested_end, block_start, block_end):
            return block
    return None


def overlapping_booking(
    db: Session,
    space_id: str,
    booking_date: date,
    requested_start: datetime,
    requested_end: datetime,
    exclude_booking_id: int | None = None,
    bookings: Iterable[Booking] | None = None,
) -> Booking | None:
    matching_bookings = bookings
    if matching_bookings is None:
        statement = select(Booking).where(
            Booking.space_id == space_id,
            Booking.booking_date == booking_date.isoformat(),
            Booking.state.in_([BookingState.CONFIRMED, BookingState.PAYMENT_PENDING]),
        )
        matching_bookings = db.scalars(statement)
    hold_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        minutes=settings.razorpay_payment_hold_minutes
    )
    for booking in matching_bookings:
        if booking.id == exclude_booking_id:
            continue
        if booking.state == BookingState.PAYMENT_PENDING and booking.updated_at < hold_cutoff:
            continue
        if not booking.start_time or not booking.duration_hours:
            continue
        booking_start, booking_end = interval_for(
            booking_date,
            time.fromisoformat(booking.start_time),
            booking.duration_hours,
        )
        if intervals_overlap(requested_start, requested_end, booking_start, booking_end):
            return booking
    return None
