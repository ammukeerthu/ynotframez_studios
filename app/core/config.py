from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "WhatsApp Studio Booking Bot"
    database_url: str = "sqlite:///./studio_bookings.db"
    studio_email: str = "studio@example.com"
    studio_timezone: str = "Asia/Kolkata"
    razorpay_payment_link_base_url: str = "https://rzp.io/i/demo"
    google_calendar_id: str = ""
    google_service_account_file: str = "./google-service-account.json"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
