from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.booking import utc_now


class StudioSetting(Base):
    """Owner-managed catalogue and booking rules for a studio space."""

    __tablename__ = "studio_settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    short_description: Mapped[str] = mapped_column(String(300))
    brochure: Mapped[str] = mapped_column(Text)
    rules: Mapped[str] = mapped_column(Text)
    hourly_rate: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    dimensions: Mapped[str] = mapped_column(String(180))
    equipment_json: Mapped[str] = mapped_column(Text, default="[]")
    amenities_json: Mapped[str] = mapped_column(Text, default="[]")
    cover_image: Mapped[str] = mapped_column(String(1000))
    opening_time: Mapped[str] = mapped_column(String(5), default="09:00")
    closing_time: Mapped[str] = mapped_column(String(5), default="20:00")
    min_duration_hours: Mapped[float] = mapped_column(Float, default=2.0)
    max_duration_hours: Mapped[float] = mapped_column(Float, default=12.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class StudioPurposeOption(Base):
    """A customer-selectable shoot purpose configured for one studio."""

    __tablename__ = "studio_purpose_options"
    __table_args__ = (UniqueConstraint("space_id", "label", name="uq_studio_purpose_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    space_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("studio_settings.id", ondelete="CASCADE"),
        index=True,
    )
    label: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
