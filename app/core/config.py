from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "YNotFramez Studios Booking"
    database_url: str = "sqlite:///./studio_bookings.db"
    studio_email: str = "studio@example.com"
    public_booking_enabled: bool = False
    email_mode: str = "console"
    email_from_name: str = "YNotFramez Studios"
    email_reply_to: str = ""
    email_bcc: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 15
    studio_timezone: str = "Asia/Kolkata"
    studio_opening_hour: int = 9
    studio_closing_hour: int = 21
    future_booking_days: int = 90
    admin_session_secret: str = ""
    admin_session_secret_file: str = ".admin_session_secret"
    admin_session_hours: int = 12
    admin_cookie_secure: bool = False
    razorpay_mode: str = "stub"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_api_base_url: str = "https://api.razorpay.com/v1"
    razorpay_payment_link_base_url: str = "https://rzp.io/i/demo"
    razorpay_callback_base_url: str = ""
    razorpay_payment_hold_minutes: int = 120
    razorpay_timeout_seconds: int = 15
    calendar_mode: str = "stub"
    google_calendar_id: str = ""
    google_calendar_standard_small_id: str = ""
    google_calendar_premium_large_id: str = ""
    google_service_account_file: str = "./google-service-account.json"
    google_calendar_timeout_seconds: int = 8

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
