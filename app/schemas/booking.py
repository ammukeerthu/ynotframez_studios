from datetime import date, time

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.booking_rules import MINIMUM_BOOKING_DURATION_HOURS


def normalize_booking_reference(value: str) -> str:
    normalized = value.strip().upper()
    numeric_id = normalized.removeprefix("YNF-")
    if not normalized.startswith("YNF-") or len(numeric_id) < 6 or not numeric_id.isdigit():
        raise ValueError("Enter a valid booking reference such as YNF-000123.")
    return normalized


class BookingDetails(BaseModel):
    space_id: str
    booking_date: str
    start_time: str
    duration_hours: float
    customer_name: str
    customer_email: EmailStr
    purpose: str
    payment_mode: str


class SpaceResponse(BaseModel):
    id: str
    slug: str
    name: str
    short_description: str
    brochure: str
    rules: str
    hourly_rate: int
    capacity: int
    dimensions: str
    equipment: tuple[str, ...]
    amenities: tuple[str, ...]
    cover_image: str
    opening_time: str
    closing_time: str
    min_duration_hours: float
    max_duration_hours: float
    booking_purposes: tuple[str, ...]


class AvailabilityRequest(BaseModel):
    space_id: str
    booking_date: date
    start_time: time
    duration_hours: float = Field(ge=0.5, le=12, multiple_of=0.5)

    @field_validator("start_time")
    @classmethod
    def require_half_hour_start(cls, value: time) -> time:
        if value.minute not in {0, 30} or value.second or value.microsecond:
            raise ValueError("Start time must be on the hour or half hour.")
        return value


class AvailabilityResponse(BaseModel):
    available: bool
    message: str


class AvailabilitySlot(BaseModel):
    start_time: str
    end_time: str
    status: str


class DayAvailabilityResponse(BaseModel):
    space_id: str
    booking_date: str
    opening_time: str
    closing_time: str
    slots: list[AvailabilitySlot]


class WebBookingCreate(AvailabilityRequest):
    duration_hours: float = Field(ge=MINIMUM_BOOKING_DURATION_HOURS, le=12, multiple_of=0.5)
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: EmailStr
    phone_number: str = Field(min_length=7, max_length=32)
    purpose: str = Field(min_length=3, max_length=1000)
    terms_accepted: bool
    payment_mode: str

    @field_validator("payment_mode")
    @classmethod
    def validate_payment_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "pay_now":
            raise ValueError("Online payment is required for new bookings.")
        return normalized


class RazorpayCheckoutResponse(BaseModel):
    key_id: str
    order_id: str
    amount: int
    currency: str = "INR"


class BookingResponse(BaseModel):
    id: int
    reference: str
    status: str
    space_name: str
    booking_date: str
    start_time: str
    end_time: str
    duration_hours: float
    total_amount: int
    customer_name: str
    customer_email: EmailStr
    phone_number: str
    payment_mode: str
    payment_link: str | None = None
    checkout: RazorpayCheckoutResponse | None = None
    calendar_event_id: str | None = None


class BookingLookupRequest(BaseModel):
    reference: str = Field(min_length=10, max_length=32)
    customer_email: EmailStr

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return normalize_booking_reference(value)


class PaymentCheckoutRequest(BookingLookupRequest):
    pass


class RazorpayPaymentVerification(BaseModel):
    reference: str = Field(min_length=10, max_length=32)
    razorpay_payment_id: str = Field(min_length=1, max_length=180)
    razorpay_order_id: str = Field(min_length=1, max_length=180)
    razorpay_signature: str = Field(min_length=1, max_length=256)

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return normalize_booking_reference(value)


class CustomerBookingStatusResponse(BaseModel):
    reference: str
    booking_status: str
    payment_status: str
    space_name: str
    booking_date: str
    start_time: str
    end_time: str
    duration_hours: float
    total_amount: int
    customer_name: str
    customer_email: EmailStr
    payment_mode: str
    payment_method: str
    payment_link: str | None = None
    checkout: RazorpayCheckoutResponse | None = None

