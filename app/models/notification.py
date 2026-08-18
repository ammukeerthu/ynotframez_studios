from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.booking import utc_now


class AdminNotification(Base):
    """Persistent owner notification for an important booking event."""

    __tablename__ = "admin_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="new_booking")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
