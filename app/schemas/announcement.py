from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AnnouncementCategory = Literal["news", "alert", "offer", "event"]


class AnnouncementResponse(BaseModel):
    enabled: bool
    category: AnnouncementCategory
    message: str


class AnnouncementUpdate(BaseModel):
    enabled: bool
    category: AnnouncementCategory = "news"
    message: str = Field(default="", max_length=300)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_enabled_message(self) -> "AnnouncementUpdate":
        if self.enabled and not self.message:
            raise ValueError("Enter announcement text before enabling the bar.")
        return self
