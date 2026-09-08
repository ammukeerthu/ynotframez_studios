from datetime import date, time

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.booking_rules import BOOKING_DURATION_INCREMENT_HOURS, MINIMUM_BOOKING_DURATION_HOURS


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)


class AdminSetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=500)


class AdminChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_password: str = Field(min_length=10, max_length=500)


class AdminSessionResponse(BaseModel):
    authenticated: bool
    username: str | None = None
    setup_required: bool = False


class AdminOverviewResponse(BaseModel):
    bookings_today: int
    upcoming_bookings: int
    confirmed_bookings: int
    estimated_value: int
    collected_value: int
    outstanding_value: int
    refund_due_value: int


class AdminAlertItem(BaseModel):
    id: str
    notification_id: int | None = None
    kind: str
    priority: str
    title: str
    message: str
    booking_id: int
    reference: str
    space_id: str
    space_name: str
    booking_date: str
    start_time: str
    end_time: str
    minutes_remaining: int | None = None
    created_at: str | None = None
    is_read: bool = False


class AdminAlertsResponse(BaseModel):
    unread_count: int
    new_bookings: list[AdminAlertItem]
    operational: list[AdminAlertItem]
    generated_at: str


class AdminStudioResponse(BaseModel):
    id: str
    slug: str
    name: str
    short_description: str
    brochure: str
    rules: str
    hourly_rate: int
    capacity: int
    dimensions: str
    equipment: list[str]
    amenities: list[str]
    cover_image: str
    opening_time: str
    closing_time: str
    min_duration_hours: float
    max_duration_hours: float
    is_active: bool
    booking_purposes: list[str]


class AdminStudioUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    short_description: str = Field(min_length=10, max_length=300)
    brochure: str = Field(min_length=10, max_length=3000)
    rules: str = Field(min_length=10, max_length=3000)
    hourly_rate: int = Field(ge=0, le=1_000_000)
    capacity: int = Field(ge=1, le=500)
    dimensions: str = Field(min_length=2, max_length=180)
    equipment: list[str] = Field(default_factory=list, max_length=50)
    amenities: list[str] = Field(default_factory=list, max_length=50)
    cover_image: str = Field(min_length=1, max_length=1000)
    opening_time: time
    closing_time: time
    min_duration_hours: float = Field(ge=MINIMUM_BOOKING_DURATION_HOURS, le=12, multiple_of=0.5)
    max_duration_hours: float = Field(ge=MINIMUM_BOOKING_DURATION_HOURS, le=12, multiple_of=0.5)
    is_active: bool
    booking_purposes: list[str] = Field(min_length=1, max_length=50)

    @field_validator("opening_time", "closing_time")
    @classmethod
    def require_half_hour(cls, value: time) -> time:
        if value.minute not in {0, 30} or value.second or value.microsecond:
            raise ValueError("Studio hours must use 30-minute increments.")
        return value

    @field_validator("equipment", "amenities")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        cleaned = list(dict.fromkeys(cleaned))
        if any(len(value) > 120 for value in cleaned):
            raise ValueError("List items must be 120 characters or fewer.")
        return cleaned

    @field_validator("booking_purposes")
    @classmethod
    def clean_booking_purposes(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("At least one booking purpose is required.")
        if any(len(value) > 120 for value in cleaned):
            raise ValueError("Booking purposes must be 120 characters or fewer.")
        return cleaned

    @model_validator(mode="after")
    def validate_ranges(self) -> "AdminStudioUpdate":
        if self.closing_time <= self.opening_time:
            raise ValueError("Closing time must be later than opening time.")
        available_hours = (
            self.closing_time.hour * 60 + self.closing_time.minute
            - self.opening_time.hour * 60 - self.opening_time.minute
        ) / 60
        if self.max_duration_hours < self.min_duration_hours:
            raise ValueError("Maximum duration cannot be shorter than minimum duration.")
        if self.max_duration_hours > available_hours:
            raise ValueError("Maximum duration cannot exceed the studio's open hours.")
        return self


class AdminBookingResponse(BaseModel):
    id: int
    reference: str
    status: str
    space_id: str | None
    space_name: str
    booking_date: str | None
    start_time: str | None
    end_time: str | None
    duration_hours: float | None
    customer_name: str | None
    customer_email: str | None
    phone_number: str
    purpose: str | None
    terms_accepted: str | None
    payment_mode: str | None
    payment_status: str
    payment_reference: str | None
    total_amount: int
    created_at: str


class AdminBookingUpdate(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    booking_date: date
    start_time: time
    duration_hours: float = Field(ge=MINIMUM_BOOKING_DURATION_HOURS, le=12, multiple_of=0.5)
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: EmailStr
    phone_number: str = Field(min_length=7, max_length=32)
    purpose: str = Field(min_length=3, max_length=1000)

    @field_validator("start_time")
    @classmethod
    def require_half_hour(cls, value: time) -> time:
        if value.minute not in {0, 30} or value.second or value.microsecond:
            raise ValueError("Start time must be on the hour or half hour.")
        return value


class AdminPaymentUpdate(BaseModel):
    status: str
    provider_reference: str | None = Field(default=None, max_length=180)

    @field_validator("status")
    @classmethod
    def require_owner_transition(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"paid", "refunded"}:
            raise ValueError("Payment status must be paid or refunded.")
        return normalized


class AdminAvailabilityBlockCreate(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    booking_date: date
    start_time: time
    duration_hours: float = Field(
        ge=BOOKING_DURATION_INCREMENT_HOURS,
        le=12,
        multiple_of=BOOKING_DURATION_INCREMENT_HOURS,
    )
    reason: str = Field(default="Owner blocked", max_length=240)

    @field_validator("start_time")
    @classmethod
    def require_half_hour(cls, value: time) -> time:
        if value.minute not in {0, 30} or value.second or value.microsecond:
            raise ValueError("Start time must be on the hour or half hour.")
        return value


class AdminAvailabilityBlockResponse(BaseModel):
    id: int
    space_id: str
    booking_date: str
    start_time: str
    end_time: str
    duration_hours: float
    reason: str


class AdminAvailabilitySlotResponse(BaseModel):
    start_time: str
    end_time: str
    status: str
    booking_reference: str | None = None
    customer_name: str | None = None
    block_id: int | None = None
    reason: str | None = None


class AdminDayAvailabilityResponse(BaseModel):
    space_id: str
    space_name: str
    booking_date: str
    opening_time: str
    closing_time: str
    slots: list[AdminAvailabilitySlotResponse]
