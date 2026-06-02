from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.whatsapp import WhatsAppIncomingMessage, WhatsAppOutgoingMessage
from app.services.booking_state import BookingStateMachine

router = APIRouter(prefix="/webhooks", tags=["WhatsApp"])


@router.post("/whatsapp", response_model=WhatsAppOutgoingMessage)
def whatsapp_webhook(payload: WhatsAppIncomingMessage, db: Session = Depends(get_db)) -> WhatsAppOutgoingMessage:
    state_machine = BookingStateMachine(db)
    reply = state_machine.handle_message(payload.from_number, payload.message)
    return WhatsAppOutgoingMessage(to=payload.from_number, message=reply)

