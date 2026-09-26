from datetime import date, time

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.booking_rules import BOOKING_DURATION_INCREMENT_HOURS, MINIMUM_BOOKING_DURATION_HOURS

ADMIN_PAYMENT_METHODS_BY_MODE = {
    "pay_at_studio": {"cash", "upi", "card", "bank_transfer", "cheque", "other"},
    "pay_now": {"upi", "card", "netbanking", "wallet", "bank_transfer", "other"},
}


def _normalized_admin_payment_method(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized not in set().union(*ADMIN_PAYMENT_METHODS_BY_MODE.values()):
        raise ValueError("Please choose a valid payment method.")
    return normalized


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
    role: str | None = None
    setup_required: bool = False


class AdminStaffUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=500)


class AdminStaffPasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=500)


class AdminStaffUserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


class AdminOverviewResponse(BaseModel):
    bookings_today: int
    upcoming_bookings: int
    confirmed_bookings: int
    estimated_value: int
    collected_value: int
    outstanding_value: int
    refund_due_value: int


class AdminFundsMonthlyCollection(BaseModel):
    month: int
    estimated_amount: int
    collected_amount: int
    pending_amount: int


class AdminFundsOverviewResponse(BaseModel):
    month: str | None
    year: int
    space_id: str | None
    estimated_amount: int
    collected_amount: int
    outstanding_amount: int
    summary_estimated_amount: int
    summary_collected_amount: int
    summary_pending_amount: int
    month_estimated_amount: int
    month_collected_amount: int
    month_pending_amount: int
    yearly_collections: list[AdminFundsMonthlyCollection]


class AdminOverviewBookingItem(BaseModel):
    id: int
    reference: str
    space_name: str
    booking_date: str
    start_time: str
    end_time: str
    customer_name: str
    phone_number: str


class AdminStudioUtilizationItem(BaseModel):
    space_id: str
    space_name: str
    booked_hours: float
    available_hours: float
    utilization_percent: float


class AdminBookingsOverviewResponse(BaseModel):
    selected_date: str
    total_bookings: int
    bookings: list[AdminOverviewBookingItem]
    utilization_month: str
    studio_utilization: list[AdminStudioUtilizationItem]


class AdminUnavailabilityReasonItem(BaseModel):
    reason: str
    blocked_hours: float


class AdminUpcomingBlockItem(BaseModel):
    id: int
    space_id: str
    space_name: str
    booking_date: str
    start_time: str
    end_time: str
    duration_hours: float
    reason: str


class AdminUnavailabilityOverviewResponse(BaseModel):
    month: str
    year: int
    space_id: str | None
    blocked_date_from: str
    blocked_date_to: str
    upcoming_blocks: list[AdminUpcomingBlockItem]
    total_blocked_hours: float
    reasons: list[AdminUnavailabilityReasonItem]
    summary_total_blocked_hours: float
    month_total_blocked_hours: float
    year_total_blocked_hours: float
    month_reasons: list[AdminUnavailabilityReasonItem]
    year_reasons: list[AdminUnavailabilityReasonItem]


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


class AdminPaymentTransactionResponse(BaseModel):
    id: int
    transaction_type: str
    amount: int
    payment_mode: str
    payment_method: str | None
    provider_reference: str | None
    occurred_at: str


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
    payment_method: str | None
    payment_status: str
    payment_reference: str | None
    total_amount: int
    amount_paid: int
    balance_due: int
    payment_transactions: list[AdminPaymentTransactionResponse]
    created_at: str


class AdminOfflineBookingCreate(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    booking_date: date
    start_time: time
    duration_hours: float = Field(ge=MINIMUM_BOOKING_DURATION_HOURS, le=12, multiple_of=0.5)
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: EmailStr
    phone_number: str = Field(min_length=7, max_length=32)
    purpose: str = Field(min_length=3, max_length=1000)
    total_amount: int = Field(ge=0, le=10_000_000)
    payment_method: str | None = Field(default=None, max_length=40)
    terms_accepted: bool

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, value: str | None) -> str | None:
        return _normalized_admin_payment_method(value)

    @field_validator("terms_accepted")
    @classmethod
    def require_offline_terms_acceptance(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirm that the booking terms were shared and accepted offline.")
        return value

    @field_validator("start_time")
    @classmethod
    def require_half_hour(cls, value: time) -> time:
        if value.minute not in {0, 30} or value.second or value.microsecond:
            raise ValueError("Start time must be on the hour or half hour.")
        return value


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
    payment_method: str | None = Field(default=None, max_length=40)
    amount: int | None = Field(default=None, ge=1, le=10_000_000)

    @field_validator("status")
    @classmethod
    def require_owner_transition(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"paid", "refunded"}:
            raise ValueError("Payment status must be paid or refunded.")
        return normalized

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, value: str | None) -> str | None:
        return _normalized_admin_payment_method(value)

    @model_validator(mode="after")
    def require_paid_method(self) -> "AdminPaymentUpdate":
        if self.status == "paid" and self.payment_method is None:
            raise ValueError("Choose the payment method before marking this booking as paid.")
        return self


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
    booking_id: int | None = None
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
