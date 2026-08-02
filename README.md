# YNotFramez Studios Booking MVP

A minimal FastAPI booking application for a two-space photography studio. Customers can book through the new responsive web interface or through the existing WhatsApp-style webhook. Both channels store bookings in the same SQLite database.

## What is included

- Editorial public website at `/`
- Dedicated studio pages at `/studios/standard-small-space` and `/studios/premium-large-space`
- Customer web booking flow at `/book`
- Customer booking retrieval at `/my-booking` using reference plus email
- Protected studio-owner dashboard at `/dashboard` (`/admin` redirects there)
- Owner-managed studio availability blocks and day schedule
- Owner-managed studio details, rates, hours, booking limits, equipment, amenities, booking purposes, and active status
- JSON APIs for spaces, availability, and bookings
- WhatsApp conversation state machine at `/webhooks/whatsapp`
- SQLite booking persistence and overlapping-slot protection
- Half-hour start times, durations, and proportional pricing
- Two studio spaces with individual details, rules, and hourly rates
- Google Calendar integration with a local stub mode
- Razorpay Payment Link placeholder
- Multipart booking emails with safe console and SMTP delivery modes
- Interactive API documentation at `/docs`

## Project structure

```text
app/
  api/routes/
    admin.py             # Owner setup, login, and dashboard API
    bookings.py          # Web booking JSON API
    whatsapp.py          # WhatsApp webhook
  core/
    config.py
    database.py
  models/
    admin.py
    availability.py
    booking.py
    payment.py
  schemas/
    admin.py
    booking.py
    whatsapp.py
  services/
    booking_service.py   # Web booking orchestration
    booking_state.py     # WhatsApp conversation flow
    admin_auth.py        # Signed admin sessions
    availability_service.py
    calendar_service.py
    email_service.py
    payment_service.py
    razorpay_service.py
    spaces.py
  static/
    admin.css
    admin.js
    app.js
    customer_booking.css
    home.js
    marketing.css
    my_booking.js
    studio.js
    styles.css
  web/
    admin.html
    home.html
    index.html
    my_booking.html
    studio.html
  main.py
```

## Local setup (Windows PowerShell)

Using Python 3.11 or newer, run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

If PowerShell blocks `Activate.ps1`, activation is not required. Use the virtual environment directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Alternatively, allow activation only in the current PowerShell process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Open:

- Studio landing page: `http://127.0.0.1:8000/`
- Booking wizard: `http://127.0.0.1:8000/book`
- Find an existing booking: `http://127.0.0.1:8000/my-booking`
- Owner dashboard: `http://127.0.0.1:8000/dashboard`
- API documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

SQLite data is created in `studio_bookings.db` by default.

Run the automated checks with:

```powershell
python -m unittest discover -s tests -v
```

## Owner dashboard

Open `http://127.0.0.1:8000/dashboard`. On the first visit, the setup screen lets you create the owner username and password. The account is saved in SQLite's `admin_users` table with a unique salt and a one-way password hash; the plain password is not stored.

After signing in, use **Change password** in the dashboard sidebar. A successful password change invalidates older signed sessions and keeps the current browser signed in with a fresh session.

The session secret is not an admin password. It is a private random key used by the server to sign the browser's HttpOnly login cookie, preventing a visitor from forging a cookie or changing its username, version, or expiry. For local development, the app generates it once in the ignored `.admin_session_secret` file. You do not need to type or edit it.

For deployment, supply a stable secret through the environment so sessions continue to work across restarts or multiple application instances:

```env
ADMIN_SESSION_SECRET="use-a-random-secret-with-at-least-32-characters"
ADMIN_COOKIE_SECURE="true"
```

Keep `ADMIN_COOKIE_SECURE="false"` for local HTTP and set it to `true` when the deployed site uses HTTPS. Back up both the SQLite database and the session secret for a stable deployed installation. There is intentionally no password-recovery flow in this MVP yet.

The dashboard shows confirmed activity and estimated value and lets the owner search/filter customer bookings. Confirmed rows include a **Manage** action for editing customer details, changing studios, rescheduling in 30-minute increments, or cancelling the booking. Reschedules use the same live overlap checks as customer bookings. Cancellation removes the Calendar event and releases the studio time.

Every confirmed booking also has a local payment record. The dashboard shows collected, outstanding, and refund-due totals. In **Manage**, the owner can record a payment reference and mark a pending payment as paid. Cancelling an unpaid booking voids its payment; cancelling a paid booking creates a refund-due state that the owner can later mark refunded. These are manual MVP controls until a real Razorpay webhook is connected.

The booking directory supports customer search, booking-status filtering, and inclusive from/to date filters. **Export CSV** downloads the currently filtered records with schedule, customer, payment, and value columns for Excel or reconciliation. The export requires an authenticated admin session and neutralizes spreadsheet-formula prefixes in customer-entered text.

The **Availability** section shows a studio's schedule in 30-minute intervals. Available time can be blocked with a reason and reopened later. Blocks are stored in SQLite and immediately affect availability checks in both the web and WhatsApp booking flows.

The **Studio settings** section stores the two studio profiles in SQLite. The owner can update public descriptions, rules, rates, capacity, equipment, amenities, customer booking-purpose dropdown options, cover images, operating hours, booking-duration limits, and whether a studio accepts new bookings. Saved values are immediately shared by the public website, web booking flow, dashboard, and WhatsApp state machine. Existing payment records retain their recorded amounts; new bookings use the latest hourly rate.

Owner-created blocks are currently application-managed: they prevent bookings even when Google Calendar mode is enabled, but they are not exported as separate Google Calendar events.

## Calendar modes

The default in `.env.example` is safe for local development:

```env
CALENDAR_MODE="stub"
```

Stub mode enforces studio hours (9:00 AM–8:00 PM), checks confirmed SQLite bookings for clashes, and returns placeholder Calendar event IDs. It does not call Google.

To use Google Calendar:

1. Create a Google Cloud service account with Calendar API access.
2. Share the target calendar with the service account email and allow it to add events.
3. Store the downloaded key as `google-service-account.json` locally. This file is ignored by Git.
4. Configure `.env`:

```env
CALENDAR_MODE="google"
GOOGLE_CALENDAR_ID="your-calendar-id"
GOOGLE_SERVICE_ACCOUNT_FILE="./google-service-account.json"
```

The live Calendar availability logic expects events named with a phrase such as `Business Hours` or `Studio Open` to define bookable periods. Events associated with a `space_id` block only that space; closure, holiday, unavailable, and out-of-office events block both.

## Web API

### List spaces

```http
GET /api/spaces
```

Rich studio details are also available by public slug:

```http
GET /api/spaces/standard-small-space
GET /api/spaces/premium-large-space
```

### Check availability

```http
POST /api/availability
Content-Type: application/json

{
  "space_id": "standard_small",
  "booking_date": "2026-08-15",
  "start_time": "14:30",
  "duration_hours": 1.5
}
```

### Create a booking

```http
POST /api/bookings
Content-Type: application/json

{
  "space_id": "standard_small",
  "booking_date": "2026-08-15",
  "start_time": "14:30",
  "duration_hours": 1.5,
  "customer_name": "Sample Customer",
  "customer_email": "customer@example.com",
  "phone_number": "+919999999999",
  "purpose": "Fashion Shoot",
  "terms_accepted": true,
  "payment_mode": "pay_now"
}
```

`purpose` must match one of the selected studio's owner-configured booking-purpose options.

`pay_now` returns a placeholder Razorpay URL. `pay_at_studio` confirms without a link.

### Retrieve a customer booking

```http
POST /api/bookings/lookup
Content-Type: application/json

{
  "reference": "YNF-000001",
  "customer_email": "customer@example.com"
}
```

Both values must match. The response includes the current booking and payment status, schedule, total, and a pending payment link when applicable. It does not expose a public booking directory.

## WhatsApp webhook testing

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/webhooks/whatsapp `
  -ContentType application/json `
  -Body '{"from_number":"919999999999","message":"hi"}'
```

The webhook returns the next bot message as JSON. It is provider-neutral for MVP testing; connecting Meta WhatsApp Cloud API still requires signature verification, payload adaptation, and outbound-message delivery.

## Provider placeholders

- Razorpay creates a deterministic placeholder URL from the configured base URL.
- WhatsApp remains provider-neutral until the Meta Cloud API adapter is connected.

## Email delivery

Local development defaults to console mode. Confirmation, reschedule, and cancellation emails are fully rendered but only summarized in the server console:

```env
EMAIL_MODE="console"
```

For a production SMTP provider, set:

```env
EMAIL_MODE="smtp"
STUDIO_EMAIL="bookings@your-domain.com"
EMAIL_FROM_NAME="YNotFramez Studios"
EMAIL_REPLY_TO="bookings@your-domain.com"
SMTP_HOST="smtp.your-provider.com"
SMTP_PORT="587"
SMTP_USERNAME="your-smtp-username"
SMTP_PASSWORD="your-smtp-password-or-app-password"
SMTP_USE_TLS="true"
SMTP_USE_SSL="false"
```

Port 587 normally uses STARTTLS (`SMTP_USE_TLS=true`). Providers using implicit TLS commonly use port 465 with `SMTP_USE_SSL=true` and `SMTP_USE_TLS=false`. Do not enable both. SMTP credentials belong only in the ignored `.env` file or deployment environment, never in Git.

Emails contain both plain-text and HTML versions, including the booking reference, booked studio, date, time, duration, purpose, payment mode, recorded amount, and pending payment link. Confirmation and update emails also include the selected studio's latest rules. Delivery failures are logged without cancelling an otherwise valid booking.

## Security note

Never commit `.env` or `google-service-account.json`. If a service-account key was committed previously, removing the file from the current branch is not enough: disable/delete that key in Google Cloud, create a replacement, and consider purging the old file from Git history before sharing the repository further.
