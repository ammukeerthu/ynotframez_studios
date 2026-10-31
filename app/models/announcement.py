from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.booking import utc_now


class AnnouncementSetting(Base):
    """Singleton configuration for the public website announcement bar."""

    __tablename__ = "announcement_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(16), default="news")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
