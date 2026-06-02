from fastapi import FastAPI

from app.api.routes.whatsapp import router as whatsapp_router
from app.core.config import settings
from app.core.database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)
app.include_router(whatsapp_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

