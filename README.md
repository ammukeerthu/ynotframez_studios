# WhatsApp Booking Bot MVP

Minimal FastAPI MVP for a two-space photography studio rental business.

## Features

- WhatsApp-style webhook endpoint
- Booking state machine
- SQLite persistence
- Two rental spaces:
  - Standard Small Space
  - Premium Large Space
- Google Calendar availability and event service stub
- Razorpay Payment Links service stub
- Email confirmation service stub

## Project Structure

```text
whatsapp-booking-bot/
  app/
    api/
      routes/
        whatsapp.py
    core/
      config.py
      database.py
    models/
      booking.py
    schemas/
      booking.py
      whatsapp.py
    services/
      booking_state.py
      calendar_service.py
      email_service.py
      razorpay_service.py
      spaces.py
    main.py
  .env.example
  requirements.txt
  README.md
```

## Setup

1. Create a virtual environment:

```bash
python -m venv .venv
```

2. Activate it:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Copy env defaults:

```bash
cp .env.example .env
```

5. Run the API:

```bash
uvicorn app.main:app --reload
```

6. Open docs:

```text
http://127.0.0.1:8000/docs
```

## WhatsApp Webhook

For MVP testing, post messages directly:

```bash
curl -X POST http://127.0.0.1:8000/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -d "{\"from_number\":\"919999999999\",\"message\":\"hi\"}"
```

Response:

```json
{
  "to": "919999999999",
  "message": "Welcome..."
}
```

## Conversation Flow

1. Customer starts WhatsApp chat
2. Selects space
3. Bot shows selected space brochure/details
4. Bot shows rules
5. Bot asks date, time, duration
6. Bot checks Google Calendar availability
7. Bot collects name, email, purpose
8. Bot asks terms acceptance
9. Bot asks payment mode: Pay Now or Pay at Studio
10. If Pay Now, bot creates Razorpay payment link
11. Bot creates Google Calendar event
12. Bot sends email confirmation

## MVP Notes

- SQLite is stored at `studio_bookings.db` by default.
- Google Calendar sync is a stub with deterministic availability checks.
- Razorpay Payment Links are placeholder URLs.
- Email confirmation logs to the console.
- Replace service methods in `app/services/` with real provider SDK calls when ready.

