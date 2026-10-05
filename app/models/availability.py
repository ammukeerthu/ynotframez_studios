from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.booking import utc_now


class AvailabilityBlock(Base):
    """Owner-created time during which a studio space cannot be booked."""

    __tablename__ = "availability_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    space_id: Mapped[str] = mapped_column(String(64), index=True)
    booking_date: Mapped[str] = mapped_column(String(16), index=True)
    start_time: Mapped[str] = mapped_column(String(8))
    duration_hours: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(240), default="Owner blocked")
    collaboration_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    collaboration_contact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collaboration_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    collaboration_recorded_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    collaboration_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
