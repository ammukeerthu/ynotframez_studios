from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.admin import router as admin_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.whatsapp import router as whatsapp_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, apply_schema_compatibility_updates, engine
from app.services.spaces import seed_studio_settings

Base.metadata.create_all(bind=engine)
apply_schema_compatibility_updates()
with SessionLocal() as seed_session:
    seed_studio_settings(seed_session)

app = FastAPI(
    title=settings.app_name,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(admin_router)
app.include_router(bookings_router)
app.include_router(whatsapp_router)

web_directory = Path(__file__).parent / "web"
static_directory = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_directory), name="static")


@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    return FileResponse(web_directory / "home.html")


@app.get("/studios", include_in_schema=False)
def studios_page() -> FileResponse:
    return FileResponse(web_directory / "home.html")


@app.get("/studios/{slug}", include_in_schema=False)
def studio_detail_page(slug: str) -> FileResponse:
    return FileResponse(web_directory / "studio.html")


@app.get("/book", include_in_schema=False)
def booking_page() -> FileResponse:
    page = "index.html" if settings.public_booking_enabled else "maintenance.html"
    return FileResponse(web_directory / page)


@app.get("/admin", include_in_schema=False)
def admin_page() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/my-booking", include_in_schema=False)
def my_booking_page() -> FileResponse:
    return FileResponse(web_directory / "my_booking.html")


@app.get("/payment/return", include_in_schema=False)
def payment_return(reference: str = "") -> RedirectResponse:
    target = "/my-booking"
    if reference:
        target += f"?reference={reference}"
    return RedirectResponse(url=target)


@app.get("/payment/return/{reference}", include_in_schema=False)
def payment_return_with_reference(reference: str) -> RedirectResponse:
    return RedirectResponse(url=f"/my-booking?reference={reference}")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page() -> FileResponse:
    return FileResponse(web_directory / "admin.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

