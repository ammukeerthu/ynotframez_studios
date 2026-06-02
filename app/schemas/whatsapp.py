from pydantic import BaseModel, Field


class WhatsAppIncomingMessage(BaseModel):
    from_number: str = Field(..., examples=["919999999999"])
    message: str = Field(..., examples=["hi"])


class WhatsAppOutgoingMessage(BaseModel):
    to: str
    message: str

