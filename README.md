# YNotFramez Studios Booking MVP

A minimal FastAPI booking application for a two-space photography studio. Customers can book through the responsive web interface or through the existing WhatsApp-style webhook. Both channels share the same relational database: SQLite for local development and Neon PostgreSQL for the deployed testing environment.

## What is included

- Editorial public website at `/`
- Dedicated studio pages at `/studios/cube` and `/studios/arena`
- Customer web booking flow at `/book`
- Customer booking retrieval at `/my-booking` using reference plus email
- Protected studio-owner dashboard at `/dashboard` (`/admin` redirects there)
- Persistent new-booking alerts and live 15-minute start/end handover reminders
- Owner-managed studio availability blocks and day schedule
- Owner-managed studio details, rates, hours, booking limits, equipment, amenities, booking purposes, and active status
- JSON APIs for spaces, availability, and bookings
- WhatsApp conversation state machine at `/webhooks/whatsapp`
- SQLAlchemy persistence with SQLite locally or PostgreSQL in deployment
- Half-hour start times, durations, and proportional pricing
- Two studio spaces with individual details, rules, and hourly rates
- Google Calendar integration with a local stub mode
- Razorpay Standard Checkout for the website, Payment Links for WhatsApp, signed verification, and a local stub mode
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
    notification.py
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

### Forgotten admin password

The original password cannot be retrieved because the application stores only a salted one-way hash. To set a new password, open PowerShell in the project root and run:

```powershell
.\.venv\Scripts\python.exe -m scripts.reset_admin_password
```

The default username is `admin`. Enter and confirm a password containing at least 10 characters. Input is hidden while typing and is not placed in terminal history. A successful reset updates only the admin password hash, increments the session version, and signs out previously authenticated dashboard sessions. Bookings, payments, calendars, availability, and studio settings are not changed.

To reset a differently named owner account, use:

```powershell
.\.venv\Scripts\python.exe -m scripts.reset_admin_password --username owner_name
```

The session secret is not an admin password. It is a private random key used by the server to sign the browser's HttpOnly login cookie, preventing a visitor from forging a cookie or changing its username, version, or expiry. For local development, the app generates it once in the ignored `.admin_session_secret` file. You do not need to type or edit it.

For deployment, supply a stable secret through the environment so sessions continue to work across restarts or multiple application instances:

```env
ADMIN_SESSION_SECRET="use-a-random-secret-with-at-least-32-characters"
ADMIN_COOKIE_SECURE="true"
```

Keep `ADMIN_COOKIE_SECURE="false"` for local HTTP and set it to `true` when the deployed site uses HTTPS. Back up both the SQLite database and the session secret for a stable deployed installation. Password recovery is intentionally an offline, local command for this MVP rather than a public web endpoint.

The dashboard shows confirmed activity and estimated value and lets the owner search/filter customer bookings. Confirmed rows include a **Manage** action for editing customer details, changing studios, rescheduling in 30-minute increments, or cancelling the booking. Reschedules use the same live overlap checks as customer bookings. Cancellation retains a red `DECLINED` event in Google Calendar while releasing the studio time.

The **Studio alerts** panel stores new bookings as unread until the owner marks them seen. It also refreshes every 30 seconds and shows operational reminders during the 15 minutes before a booking starts and the final 15 minutes of a current booking. When another session follows within 30 minutes, the ending reminder includes the next customer. Optional desktop notifications work while the dashboard is open and browser permission is granted.

Every booking has a local payment record. New customer requests remain in `payment_pending` and hold the selected time for two hours. Website payments are confirmed using both the Razorpay checkout signature and the provider's payment status; signed webhooks provide an idempotent fallback. The studio is reserved, its Google Calendar event is created, and its confirmation email is sent only after captured payment is verified. The dashboard retains a manual **Mark paid** action for studio follow-up and payment-provider exceptions.

The booking directory supports customer search, booking-status filtering, and inclusive from/to date filters. **Export CSV** downloads the currently filtered records with schedule, customer, payment, and value columns for Excel or reconciliation. The export requires an authenticated admin session and neutralizes spreadsheet-formula prefixes in customer-entered text.

The **Availability** section shows a studio's schedule in 30-minute intervals. Available time can be blocked with a reason and reopened later. Blocks are stored in the configured database and immediately affect availability checks in both the web and WhatsApp booking flows.

The **Studio settings** section stores the two studio profiles in the configured database. The owner can update public descriptions, rules, rates, capacity, equipment, amenities, customer booking-purpose dropdown options, cover images, operating hours, booking-duration limits, and whether a studio accepts new bookings. Saved values are immediately shared by the public website, web booking flow, dashboard, and WhatsApp state machine. Existing payment records retain their recorded amounts; new bookings use the latest hourly rate.

### Synchronize committed studio defaults

The committed Cube and Arena defaults live in `app/services/spaces.py`. Normal application startup seeds missing studio rows but deliberately does not overwrite owner-managed settings in an existing database.

Use the guarded maintenance command when an existing database must be explicitly reset to the committed profiles and purpose options. Running it without `--apply` opens a transaction and rolls it back:

```powershell
.\.venv\Scripts\python.exe -m scripts.sync_studio_defaults
```

Confirm that the masked `Database:` line identifies the intended database. Then commit the synchronization:

```powershell
.\.venv\Scripts\python.exe -m scripts.sync_studio_defaults --apply
```

For the deployed Neon database, copy `DATABASE_URL` from Render and load it into only the current PowerShell process before running the commands:

```powershell
$env:DATABASE_URL = (Get-Clipboard).Trim()
if ($env:DATABASE_URL -match "neon\.tech") { "Neon DATABASE_URL loaded" } else { "Neon URL was not loaded" }
.\.venv\Scripts\python.exe -m scripts.sync_studio_defaults
.\.venv\Scripts\python.exe -m scripts.sync_studio_defaults --apply
Remove-Item Env:DATABASE_URL
Set-Clipboard -Value "cleared"
```

Never paste the connection string into chat, source files, or a command that will be retained in shell history. The synchronization replaces studio profiles and purpose options only; it does not alter bookings, payments, calendar events, availability blocks, or admin credentials.

Owner-created blocks are currently application-managed: they prevent bookings even when Google Calendar mode is enabled, but they are not exported as separate Google Calendar events.

## Calendar modes

The default in `.env.example` is safe for local development:

```env
CALENDAR_MODE="stub"
```

Stub mode enforces studio hours (9:00 AM–8:00 PM), checks confirmed SQLite bookings for clashes, and returns placeholder Calendar event IDs. It does not call Google.

To use Google Calendar:

1. Create a Google Cloud service account with Calendar API access.
2. In the studio owner's Google account, create one calendar for each physical studio space.
3. Share both calendars with the service account email and grant **Make changes to events** access.
4. Copy each ID from the calendar's **Settings and sharing > Integrate calendar** section.
5. Store the downloaded key as `google-service-account.json` locally. This file is ignored by Git.
6. Configure `.env`:

```env
CALENDAR_MODE="google"
GOOGLE_CALENDAR_STANDARD_SMALL_ID="standard-space-calendar-id"
GOOGLE_CALENDAR_PREMIUM_LARGE_ID="premium-space-calendar-id"
GOOGLE_SERVICE_ACCOUNT_FILE="./google-service-account.json"
```

Studio hours continue to come from Studio Dashboard settings. Any normal busy event placed on a dedicated studio calendar blocks that time for only that studio; events marked **Free** remain bookable. Confirmed bookings are created on the selected studio's calendar, and rescheduling or cancellation updates the same event. The legacy `GOOGLE_CALENDAR_ID` setting remains available when both studios intentionally share one calendar.

## Web API

### List spaces

```http
GET /api/spaces
```

Rich studio details are also available by public slug:

```http
GET /api/spaces/cube
GET /api/spaces/arena
```

### Check availability

```http
POST /api/availability
Content-Type: application/json

{
  "space_id": "standard_small",
  "booking_date": "2026-08-15",
  "start_time": "14:30",
  "duration_hours": 2
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
  "duration_hours": 2,
  "customer_name": "Sample Customer",
  "customer_email": "customer@example.com",
  "phone_number": "+919999999999",
  "purpose": "Fashion Shoot",
  "terms_accepted": true,
  "payment_mode": "pay_now"
}
```

`purpose` must match one of the selected studio's owner-configured booking-purpose options.

All bookings require a minimum duration of 2 hours. Longer bookings can use 30-minute increments.

New public bookings accept only `pay_now`. In `RAZORPAY_MODE=api`, the server calculates the amount, creates a unique Razorpay Order in INR, and returns only the public key and order metadata needed by Standard Checkout. The secret key never reaches the browser. The legacy WhatsApp flow continues to create a hosted Razorpay Payment Link. `pay_at_studio` is retained only as an internal owner/follow-up mode and is not a customer-selectable option.

### Retrieve a customer booking

```http
POST /api/bookings/lookup
Content-Type: application/json

{
  "reference": "YNF-000001",
  "customer_email": "customer@example.com"
}
```

Both values must match. The response includes the current booking and payment status, actual verified Razorpay method (`upi`, `netbanking`, `card`, `emi`, and so on), schedule, total, and a retryable Standard Checkout order while an unpaid booking hold remains active. Older captured payments are backfilled from Razorpay when possible. It does not expose a public booking directory.

## WhatsApp webhook testing

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/webhooks/whatsapp `
  -ContentType application/json `
  -Body '{"from_number":"919999999999","message":"hi"}'
```

The webhook returns the next bot message as JSON. It is provider-neutral for MVP testing; connecting Meta WhatsApp Cloud API still requires signature verification, payload adaptation, and outbound-message delivery.

## Razorpay payment-first setup

Create Razorpay Test Mode API keys and configure the `RAZORPAY_*` values shown in `.env.example`. Keep `RAZORPAY_MODE="stub"` until the code and secrets are deployed together, then change it to `api` for an end-to-end Test Mode payment. Configure a Razorpay webhook pointing to:

```text
https://your-public-domain.example/api/payments/razorpay/webhook
```

Use the same secret in Razorpay and `RAZORPAY_WEBHOOK_SECRET`. Subscribe to `payment.captured`, `payment.failed`, and `order.paid`. If WhatsApp Payment Links are being tested, also subscribe to `payment_link.paid`, `payment_link.expired`, and `payment_link.cancelled`. Razorpay must be able to reach this HTTPS endpoint; `127.0.0.1` cannot receive provider webhooks.

For offline UI development only, use `RAZORPAY_MODE="stub"`. Stub mode records deterministic test order/link identifiers but intentionally supplies no checkout key, so it cannot take payment or confirm a booking automatically.

Standard Checkout uses Razorpay's hosted `checkout.js`; the app does not need the Python Razorpay SDK. Order creation and payment-status retrieval use the existing server-side HTTP client. A failed attempt remains retryable during the temporary hold. If money is captured after the slot can no longer be reserved, the booking is cancelled, the payment is marked `refund_due`, and the dashboard shows an unread payment-review alert.

WhatsApp remains provider-neutral until the Meta Cloud API adapter is connected.

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

Emails contain both plain-text and HTML versions. The HTML version embeds the YNotFramez Studios PNG logo so it does not depend on a remote image URL. Booking messages include the reference, booked studio, date, time, duration, purpose, and recorded amount. Confirmation and update emails also include the selected studio's latest rules. Payment-failure emails highlight the amount and follow-up instructions. Delivery failures are logged without cancelling an otherwise valid booking.

## Security note

Never commit `.env` or `google-service-account.json`. If a service-account key was committed previously, removing the file from the current branch is not enough: disable/delete that key in Google Cloud, create a replacement, and consider purging the old file from Git history before sharing the repository further.

## Free team-testing deployment

The repository includes `render.yaml` for a Render Free web service in Singapore. Deployed data is stored in Neon PostgreSQL because Render Free's local filesystem is ephemeral and would discard a SQLite database whenever the service sleeps, restarts, or redeploys.

Public online booking has a production-safe maintenance switch:

```env
PUBLIC_BOOKING_ENABLED="false"
```

When disabled, `/book` shows the branded maintenance page and direct public booking creation returns HTTP 503. Studio pages, the dashboard, existing-booking lookup, payment verification, webhooks, and administrative booking tools remain available. Local `.env` may use `true` for testing. Change the Render value to `true` only when the public payment and booking flow is ready to launch.

This setup has no required hosting charge within the providers' free allowances, but it is a testing environment rather than a production SLA. Render Free sleeps after 15 minutes without inbound traffic, so the first visit after an idle period can take about a minute. Neon Free suspends idle compute and wakes it automatically when the app reconnects.

### 1. Create the free Neon database

1. Create a Neon account and a project named **YNotFramez Studios Testing**.
2. Open the project and select **Connect**.
3. Copy the PostgreSQL connection string. Keep the included `sslmode=require` and `channel_binding=require` parameters.
4. Treat the complete connection string as a password. Never commit it or paste it into `.env.example`.

The application automatically selects Psycopg 3 for both `postgresql://` and legacy `postgres://` URLs. Tables and initial studio settings are created on the first successful application startup.

### 2. Create free transactional email credentials

Render Free blocks outbound SMTP ports 25, 465, and 587. Brevo supports port 2525 as an alternative and its Free plan includes transactional email.

1. Create a Brevo account.
2. Add `ynotframezstudios@gmail.com` as a transactional sender and complete the verification message sent to that address.
3. Open **Settings > SMTP & API** and create an SMTP key.
4. Copy the Brevo SMTP **Login** and the newly created SMTP key. The login is not necessarily the Brevo account email, and the SMTP key is not the account password or an API key.

The Blueprint already supplies `smtp-relay.brevo.com` and port `2525`. Brevo's Free plan adds its branding to sent email.

### 3. Create the Render Blueprint

1. Push the deployment commit to GitHub.
2. Sign in to Render and choose **New > Blueprint**.
3. Connect the `ammukeerthu/ynotframez_studios` repository and select the branch containing `render.yaml`.
4. During the initial Blueprint setup, provide these protected values:
   - `DATABASE_URL`: the complete Neon connection string.
   - `SMTP_USERNAME`: the Brevo SMTP Login.
   - `SMTP_PASSWORD`: the Brevo SMTP key.
   - `GOOGLE_CALENDAR_STANDARD_SMALL_ID`: the Cube calendar ID.
   - `GOOGLE_CALENDAR_PREMIUM_LARGE_ID`: the Arena calendar ID.
5. In the new service's **Environment > Secret Files**, add a file named `google-service-account.json` and paste the complete contents of the local ignored file. It is exposed to the app at `/etc/secrets/google-service-account.json`.
6. Deploy and verify these addresses before inviting testers:
   - `https://<service-name>.onrender.com/health`
   - `https://<service-name>.onrender.com/`
   - `https://<service-name>.onrender.com/dashboard`
7. The deployed database starts empty. Open `/dashboard` and create the deployment's admin account. This does not change the local admin account.

The Blueprint sets `ADMIN_COOKIE_SECURE=true`, generates a stable admin-session signing secret, and runs one Uvicorn worker. Razorpay deliberately remains in stub mode until Test Mode is explicitly enabled in Render. In stub mode, a submitted booking stays payment-pending and holds its slot; use **Mark paid** in the Studio Dashboard to complete the test booking, create its live Google Calendar event, and send its confirmation email.

### Production domains

The public domain arrangement is:

- Primary application: `https://ynotframezstudios.com`
- Secondary brand domain: `https://ynotframezstudios.in`, permanently redirected to the `.com`
- Render fallback: `https://ynotframez-studios.onrender.com`

The `.com` root domain is attached to the Render web service as a custom domain. Its root A record and `www` CNAME must use the values shown by Render. Render verifies both names, redirects `www` to the root domain, and automatically issues the managed HTTPS certificates.

The `.in` domain is not added to Render. In GoDaddy it uses an unmasked **Permanent (301)** forwarding rule whose destination is `https://ynotframezstudios.com`; its `www` CNAME points to `@`. GoDaddy forwarding requires completed WHOIS verification and can take several hours to provision HTTPS or up to 48 hours to propagate globally.

When Razorpay API mode is enabled, set this public base URL for the legacy WhatsApp Payment Link return route:

```env
RAZORPAY_CALLBACK_BASE_URL="https://ynotframezstudios.com"
```

Configure the Razorpay webhook as `https://ynotframezstudios.com/api/payments/razorpay/webhook`. Do not advertise either domain until its root and `www` addresses work over HTTPS and the `.in` addresses redirect to `.com` without masking.
