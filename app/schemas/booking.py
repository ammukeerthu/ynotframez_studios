from pydantic import BaseModel, EmailStr


class BookingDetails(BaseModel):
    space_id: str
    booking_date: str
    start_time: str
    duration_hours: int
    customer_name: str
    customer_email: EmailStr
    purpose: str
    payment_mode: str

