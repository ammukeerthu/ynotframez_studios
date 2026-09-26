# YNotFramez Studios Booking

A FastAPI website and booking application for the Cube and Arena photography studios. Customers can explore the studios, reserve a live-checked time slot, pay through Razorpay, receive email updates, and retrieve a booking later. The owner dashboard manages bookings, availability, studio content, payments, and operational alerts. SQLite is used locally and Neon PostgreSQL is used by the Render deployment.

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
- Versioned booking Terms and Conditions with an in-page modal and downloadable PDF
- Public-booking maintenance gate with studio contact and directions
- Responsive studio galleries, branding, and dedicated Cube and Arena photography
- Production API documentation and schema routes intentionally disabled

## Project structure

```text
app/
  api/routes/
    admin.py             # Owner setup, login, and dashboard API
    bookings.py          # Web booking JSON API
    whatsapp.py          # WhatsApp webhook
  core/
    booking_rules.py      # Shared duration and Terms version constants
    config.py
    database.py
  models/
    admin.py
    availability.py
    booking.py
    notification.py
    payment.py
    studio.py
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
    notification_service.py
    payment_service.py
    razorpay_service.py
    spaces.py
  static/
    admin.css
    admin.js
    app.js
    customer_booking.css
    home.js
    maintenance.css
    marketing.css
    my_booking.js
    razorpay_checkout.js
    studio.js
    styles.css
    brand/               # Website and opaque email logos
    legal/               # Published booking Terms PDF
    studio/              # Homepage and studio gallery images
  web/
    admin.html
    home.html
    index.html
    maintenance.html
    my_booking.html
    studio.html
  main.py
scripts/
  clear_bookings.py
  migrate_stub_calendar_events.py
  refresh_google_calendar_events.py
  reset_admin_password.py
  sync_admin_password.py
  sync_studio_defaults.py
  verify_google_calendars.py
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
- Health check: `http://127.0.0.1:8000/health`

SQLite data is created in `studio_bookings.db` by default.

The copied `.env.example` starts in safe local modes: `EMAIL_MODE=console`, `RAZORPAY_MODE=stub`, `CALENDAR_MODE=stub`, and `PUBLIC_BOOKING_ENABLED=false`. Set `PUBLIC_BOOKING_ENABLED=true` to open the local booking wizard. Switch an integration to its live implementation only after replacing its placeholder values in the ignored `.env` file.

Run the automated checks with:

```powershell
python -m unittest discover -s tests -v
```

## Environment configuration

`.env.example` groups settings by application, email, payments, admin security, Calendar integration, and Render overrides. Copy it to `.env` for local work; never put secrets into `.env.example`.

The principal mode switches are:

| Setting | Safe local value | Integrated value | Purpose |
| --- | --- | --- | --- |
| `PUBLIC_BOOKING_ENABLED` | `false` | `true` | Shows the booking wizard instead of the maintenance page and permits public booking creation. Render manages this operational switch in the service dashboard. |
| `EMAIL_MODE` | `console` | `smtp` | Prints email summaries locally or sends through the configured SMTP relay. |
| `RAZORPAY_MODE` | `stub` | `api` | Uses placeholder orders or Razorpay Standard Checkout and API verification. |
| `CALENDAR_MODE` | `stub` | `google` | Uses placeholder event IDs or the two configured Google Calendars. |

`RAZORPAY_MODE=api` does not itself select Test or Live Mode. The `rzp_test_...` or `rzp_live_...` key pair determines which Razorpay environment is used. The key ID, key secret, and webhook secret must all belong to the same environment.

`STUDIO_OPENING_HOUR` and `STUDIO_CLOSING_HOUR` are startup fallbacks. Once studio rows exist, the operating hours and booking-duration limits saved in Studio Settings are authoritative. `FUTURE_BOOKING_DAYS` controls the furthest date accepted by the booking API. Timeout values bound external SMTP, Razorpay, and Google Calendar requests.

FastAPI's `/docs`, `/redoc`, and `/openapi.json` routes are disabled intentionally so the public deployment does not expose interactive API documentation.

## Public website content

The homepage, Cube page, and Arena page load studio descriptions, rates, dimensions, equipment, amenities, operating hours, cover images, and galleries from the public spaces API. The homepage intentionally previews the first five amenities saved for each studio. Most owner-editable copy comes from Studio Settings; the homepage hero, contact block, navigation labels, and booking-maintenance message are code-managed website content.

Public studio metadata is optimized separately from live availability. Catalogue requests batch studio-purpose reads, individual detail requests query only the requested studio, and the single Render worker warms its metadata cache during startup and keeps responses in memory for up to five minutes. Public pages also reuse the most recently loaded catalogue from browser storage so studio cards and details can appear immediately during navigation, then refresh them from the API in the background. Saving Studio Settings clears the server cache and the dashboard browser's cached copy. Booking, payment, and calendar availability responses are never stored in this metadata cache.

The published contact details are:

- Phone: `+91 72005 77341`
- Email: `ynotframezstudios@gmail.com`
- Address: Survey No 712, 1A1, Poonamallee - Avadi High Rd, Paruthippattu, Selva Nagar, Govarthanagiri, Avadi, Chennai, Tamil Nadu 600071
- Directions: `https://maps.app.goo.gl/k3ZhASzdAr66mNFM6`

Studio and homepage photographs are tracked under `app/static/studio/`. The regular PNG logo has transparency for the website; email uses `ynotframez-logo-email.png`, which has an opaque white background for visibility in dark-mode mail clients.

## Owner dashboard

Open `http://127.0.0.1:8000/dashboard`. On the first visit, the setup screen lets you create the owner username and password. The account is saved in SQLite's `admin_users` table with a unique salt and a one-way password hash; the plain password is not stored.

After signing in, use **Change password** in the dashboard sidebar. A successful password change invalidates older signed sessions and keeps the current browser signed in with a fresh session.

Clicking the owner-only **Settings** menu expands or collapses its **Staff Access** and **Studio Catalogue** submenus without changing the current page. Each submenu opens a separate dashboard page containing only that feature. The owner can create up to two staff accounts from **Settings → Staff Access**. Staff can view dashboard data and booking details, export filtered bookings, and block or reopen studio time. They cannot create, edit, cancel, or reconcile bookings, and all Settings menus and pages are hidden from them. These permissions are enforced by the admin API as well as by the dashboard interface. The owner can reset a staff password or remove a staff account; resetting a password invalidates that staff user's existing sessions.

The owner can upgrade a confirmed Cube booking to Arena after live availability is checked. Historical Cube bookings can also be corrected to Arena while retaining their original past date and time; conflicts, blocks, operating hours, and calendar availability are still validated. Any amount already received remains as its own payment-history entry, the higher Arena total becomes partially paid, and each later balance payment is stored with its own amount, method, and reference. References are not combined into one comma-separated field. Arena-to-Cube downgrades remain blocked so the dashboard does not create an automatic repayment case. Existing paid and refunded records are copied into this transaction ledger once during deployment startup.

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

Keep `ADMIN_COOKIE_SECURE="false"` for local HTTP and set it to `true` when the deployed site uses HTTPS. Back up both the SQLite database and the session secret for a stable deployed installation. Password recovery is intentionally an offline, local command rather than a public web endpoint.

To copy the password hash for the local `admin` account into an already initialized Render/Neon database, temporarily load the remote `DATABASE_URL` and run the guarded synchronization. The command never reads or prints the plain-text password:

```powershell
$env:DATABASE_URL = (Get-Clipboard).Trim()
.\.venv\Scripts\python.exe -m scripts.sync_admin_password
.\.venv\Scripts\python.exe -m scripts.sync_admin_password --apply
Remove-Item Env:DATABASE_URL
Set-Clipboard -Value "cleared"
```

The first command is a dry run. `--apply` copies the local salt and password hash, increments the remote session version, and invalidates existing remote sessions. Both databases must already contain the selected username. Use `--username owner_name` on both commands for a different account.

The dashboard's **Overview** menu expands into three independent pages. **Funds** shows all-time estimated confirmed-booking amount, net collected amount, and pending amount, with an All Spaces/Cube/Arena filter. It also includes a selected-month collected-versus-pending donut chart and a selected-year Jan-Dec stacked bar chart showing both collected and pending amounts; values refresh when a picker changes. Finance reporting is grouped by the booked studio-session date, not booking creation or payment date. Only confirmed bookings count: cancelled, expired, refunded/refund-due records and studio availability blocks are excluded. Collected values come from net payment transactions (payments less recorded refunds), while pending is the unpaid balance of confirmed pending or partially paid bookings. **Bookings** shows the confirmed booking count and Studio/Date & Time/Customer table for Yesterday, Today, or Tomorrow, plus a selected-month bar chart of each studio's confirmed booked hours divided by its configured operating hours. **Unavailability** charts owner-blocked hours by reason for a selected month. These analytics are read-only and available to both the owner and view-only staff.

The dashboard lets the owner search/filter customer bookings. **Create offline booking** records a past, current, or future booking without sending a checkout link or customer email; it creates the matching Google Calendar event and leaves payment pending until reconciled. Its start-time dropdown labels each choice as a 30-minute range, while only the selected range's start time is stored. The owner must confirm that the current booking terms were shared and accepted offline. Payment flow is assigned automatically: admin-created offline bookings are **Pay at studio**, while bookings created through the public interface are **Online**. Pay-at-studio methods are Cash, UPI, Card, Bank transfer, Cheque, or Other; online methods are UPI, Card, Net banking, Wallet, Bank transfer, or Other. A method can be recorded immediately or left undecided, but it is mandatory whenever a payment is recorded. Existing completed bookings with a missing flow are classified during startup, their payment records are synchronized to the booking flow, and confirmed or cancelled offline bookings missing a terms marker are backfilled to the current terms version. Confirmed rows include a **Manage** action for reviewing payment history, changing studios, rescheduling in 30-minute increments, updating the customer email, or cancelling the booking. Reschedules and studio changes validate the full booking interval against bookings, owner blocks, business hours, and Google Calendar before saving. Studio changes support Cube-to-Arena upgrades only; Arena-to-Cube downgrades are blocked to avoid refund or credit handling. An upgrade recalculates the total at Arena's hourly rate and moves the Calendar event. Any amount already received stays in the payment history, the remaining balance becomes due, and each later payment keeps its own amount, method, and reference. Cancellation retains a red `DECLINED` event in Google Calendar while releasing the studio time. Cancelling a paid booking marks its payment `refund_due`; it does not call Razorpay's Refund API or return money automatically. Complete the refund in Razorpay, then use **Mark refunded** in the dashboard with the provider reference.

The **Studio alerts** panel stores new bookings as unread until the owner marks them seen. It also refreshes every 30 seconds and shows operational reminders during the 15 minutes before a booking starts and the final 15 minutes of a current booking. When another session follows within 30 minutes, the ending reminder includes the next customer. Optional desktop notifications work while the dashboard is open and browser permission is granted.

Every booking has a local payment summary and a transaction history for received payments and refunds. New customer requests remain in `payment_pending` and hold the selected time for two hours. A single payment-pending email states the exact hold deadline and links to **Find My Booking**; failed checkout retries do not generate repeated emails. Each active hold also creates an opaque **PAYMENT HOLD** event in that studio's Google Calendar. Payment confirmation updates the same event into the final booking; expiry deletes it, marks the booking `expired`, marks its payment `void`, and releases the time. PostgreSQL transaction advisory locks serialize booking creation for each studio day so parallel website requests cannot both create a hold. Website payments are confirmed using both the Razorpay checkout signature and the provider's payment status; signed webhooks provide an idempotent fallback. The confirmation email is sent only after captured payment is verified. The dashboard's manual **Record payment** action captures the amount, method, and optional provider reference; payments below the total leave the booking partially paid with its balance visible. **Find My Booking** shows the booking total, amount received, and remaining balance.

The booking directory opens with its date range set to the current calendar week from Monday through Sunday, while the Availability schedule opens on the current date. The directory supports customer search, booking-status filtering, and inclusive from/to date filters. Its table defaults to scheduled booking date and start time in descending order, with the latest sessions first and unscheduled records last. The default columns are Date & Time, Customer, Purpose, Payment Status, Booking Status, and Actions in that order; Customer shows the name and phone number, while payment and booking states use distinct color-coded badges. Because the directory is already selected by studio, Studio is not repeated as a table option. The Columns menu can enable Reference, a version-neutral Terms Accepted indicator, or Amount; each newly enabled column is appended immediately before Actions. The selected layout and order are saved in the current browser, while Actions remains visible and last. The current column-layout version intentionally ignores preferences saved by the earlier all-columns layout so the six-column default takes effect once after deployment. When a confirmed booking is managed, its rescheduling controls load live availability while excluding only that booking and its own calendar event. Other bookings, active payment holds, owner blocks, and external Google Calendar conflicts remain disabled. Customer name, phone number, duration, and purpose are immutable; each offered reschedule time must accommodate the complete original duration. Studio, date, start time, and customer email remain editable. **Export CSV** downloads the complete filtered records independently of the visible table layout for Excel or reconciliation, including the studio, payment flow, method, total, amount received, balance, latest reference, and payment history. The export requires an authenticated admin session and neutralizes spreadsheet-formula prefixes in customer-entered text.

The **Availability** section shows a studio's schedule in 30-minute intervals. Selecting a booked tile opens a read-only summary with its reference, date and time, customer, studio, purpose, payment, and status; this does not expose the booking edit controls. The owner can block an available period on a past, current, or future date starting from 30 minutes; staff can block only current or future time. This admin-only minimum does not change the one-hour minimum for customer bookings. Historical blocks cannot overlap a recorded booking or another block. Block reasons can be selected from Maintenance, Power Shutdown, Technical Issue, Mandatory Holiday, and Collaboration. Each blocked calendar tile displays `BLOCKED` with its reason directly underneath. A blocked tile can be right-clicked or tapped to reopen only that half-hour; if it belongs to a longer block, the stored block is safely shortened or split around the reopened slot. Blocks are stored in the configured database; current and future blocks immediately affect availability checks in both the web and WhatsApp booking flows. They do not create separate Google Calendar events.

The **Studio settings** section stores the two studio profiles in the configured database. The owner can update public descriptions, rules, rates, capacity, equipment, amenities, customer booking-purpose dropdown options, cover images, operating hours, booking-duration limits, and whether a studio accepts new bookings. Saved values are immediately shared by the public website, web booking flow, dashboard, and WhatsApp state machine. Existing payment records retain their recorded amounts; new bookings use the latest hourly rate.

### Synchronize committed studio defaults

The committed Cube and Arena defaults live in `app/services/spaces.py`. Normal application startup seeds missing studio rows and does not perform a full overwrite of owner-managed settings. Narrow compatibility migrations may update a field only when its saved value exactly matches a superseded application default. The current migrations change the old 9 AM to 8 PM schedule to 9 AM to 9 PM, Arena capacity from 10 to 8, Arena's exact legacy Cyclorama list label to `Cyclorama`, rename the previous `Family Shoots` Arena purpose to `Family Portraits` and place it after `Fashion Shoot`, add `Fine Arts` to both studios after `Creative / Conceptual Shoot` while retaining custom purpose options, and move the previous two-hour studio minimum to one hour once while preserving later owner changes. Other custom values and all operational data remain untouched. This lets the same guarded changes reach SQLite and Render/Neon during normal startup without copying one database into another.

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

### Remove booking test data

The guarded cleanup command removes all bookings from the selected database together with their payment summaries, payment transaction histories, and booking notifications. When Google Calendar mode is active, it deletes every linked booking or payment-hold event before deleting database records. Studio settings, owner availability blocks, purpose options, and admin users remain intact.

Always inspect the dry-run counts and database label first:

```powershell
.\.venv\Scripts\python.exe -m scripts.clear_bookings
.\.venv\Scripts\python.exe -m scripts.clear_bookings --apply
```

To clean Neon, temporarily load its `DATABASE_URL` into the same terminal before running both commands. If any Calendar deletion fails, the database deletion is stopped. This command deletes every booking in the selected database, not an individual reference.

### Booking Terms and Conditions

The current published booking terms are identified internally as `v2` in `app/core/booking_rules.py`; the version is deliberately not displayed in the customer interface. During public booking, the customer opens the Terms and Conditions in an accessible modal, can view the published PDF, and must explicitly accept before continuing. For an offline booking, the owner confirms in the dashboard that the same terms were shared and accepted. The accepted version is stored with the booking so future wording changes do not erase which terms applied.

The source displayed by the booking flow is in `app/web/index.html`, and the downloadable copy is `app/static/legal/ynotframez-studio-booking-terms.pdf`. When publishing a later revision, update both together and then increment `CURRENT_TERMS_VERSION`.

Owner-created blocks are currently application-managed: they prevent bookings even when Google Calendar mode is enabled, but they are not exported as separate Google Calendar events.

## Calendar modes

The default in `.env.example` is safe for local development:

```env
CALENDAR_MODE="stub"
```

Stub mode enforces the database-backed studio hours (9:00 AM to 9:00 PM by default), checks confirmed SQLite bookings for clashes, and returns placeholder Calendar event IDs. It does not call Google.

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
GOOGLE_CALENDAR_TIMEOUT_SECONDS="8"
```

Studio hours continue to come from Studio Dashboard settings. Any normal busy event placed on a dedicated studio calendar blocks that time for only that studio; events marked **Free** remain bookable. Confirmed bookings are created on the selected studio's calendar, and rescheduling or cancellation updates the same event. Each day view loads studio settings, bookings, blocks, and Google events once, then evaluates its half-hour slots in memory; this avoids accumulating cross-region database latency for every slot. Calendar API transports are isolated per request worker, reuse a shared service-account token, and are bounded by `GOOGLE_CALENDAR_TIMEOUT_SECONDS`, so one stalled Google connection cannot queue every public and admin availability view. The legacy `GOOGLE_CALENDAR_ID` setting remains available when both studios intentionally share one calendar.

Useful Calendar maintenance commands are:

```powershell
# Creates, reads, and removes one temporary event in each configured calendar.
.\.venv\Scripts\python.exe -m scripts.verify_google_calendars

# Replaces stub IDs on confirmed bookings with real Google events.
.\.venv\Scripts\python.exe -m scripts.migrate_stub_calendar_events

# Recreates or updates events from confirmed and cancelled booking records.
.\.venv\Scripts\python.exe -m scripts.refresh_google_calendar_events
```

Run these only after confirming `CALENDAR_MODE=google`, the selected `DATABASE_URL`, the service-account file, and both studio Calendar IDs. The verification command performs a real temporary write and removes it. Migration and refresh modify live studio calendars and should be used only for a deliberate repair or environment transition.

## Web API

Interactive OpenAPI pages are disabled. The customer-facing routes used by the bundled frontend are:

| Method and path | Purpose |
| --- | --- |
| `GET /api/spaces` | List active studio profiles. |
| `GET /api/spaces/{slug}` | Load one public studio profile and gallery. |
| `POST /api/availability` | Check one proposed booking window. |
| `GET /api/availability/day` | Load all half-hour slots for a studio and date. |
| `POST /api/bookings` | Create a payment-pending booking and checkout order. Disabled by the maintenance gate. |
| `POST /api/bookings/checkout` | Create or retrieve a retry checkout for an active hold. |
| `POST /api/payments/razorpay/verify` | Verify checkout signature, provider status, amount, currency, and availability before confirming. |
| `POST /api/payments/razorpay/webhook` | Process signed Razorpay payment fallback events idempotently. |
| `POST /api/bookings/lookup` | Retrieve one booking using its reference and customer email. |

Owner routes use the `/api/admin` prefix and require the signed HttpOnly admin-session cookie. The WhatsApp-style state-machine webhook is `POST /webhooks/whatsapp`.

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
  "booking_date": "2026-10-15",
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
  "booking_date": "2026-10-15",
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

All bookings require a minimum duration of 1 hour. Longer bookings can use 30-minute increments.

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

The webhook returns the next bot message as JSON. It is provider-neutral for development; connecting Meta WhatsApp Cloud API still requires signature verification, payload adaptation, and outbound-message delivery.

## Razorpay payment-first setup

Create Razorpay Test Mode API keys and configure the `RAZORPAY_*` values shown in `.env.example`. Keep `RAZORPAY_MODE="stub"` until the code and secrets are deployed together, then change it to `api` for an end-to-end Test Mode payment. Never mix Test and Live credentials. Configure a webhook in the same Razorpay mode, pointing to:

```text
https://your-public-domain.example/api/payments/razorpay/webhook
```

Use the same webhook secret in Razorpay and `RAZORPAY_WEBHOOK_SECRET`. This secret is chosen while creating the webhook; it is not the API key secret. Subscribe to `payment.captured`, `payment.failed`, and `order.paid`. If WhatsApp Payment Links are being tested, also subscribe to `payment_link.paid`, `payment_link.expired`, and `payment_link.cancelled`. Razorpay must be able to reach this HTTPS endpoint; `127.0.0.1` cannot receive provider webhooks.

For offline UI development only, use `RAZORPAY_MODE="stub"`. Stub mode records deterministic test order/link identifiers but intentionally supplies no checkout key, so it cannot take payment or confirm a booking automatically.

Standard Checkout uses Razorpay's hosted `checkout.js`; the app does not need the Python Razorpay SDK. Order creation and payment-status retrieval use the existing server-side HTTP client. A new request creates a database hold and an opaque Google Calendar `PAYMENT HOLD` event. A failed attempt remains retryable until the hold deadline, and failed attempts do not release the time to another customer. Captured payment is confirmed only after checking the signature, Razorpay status, order, amount, currency, and final slot availability.

If money is captured after the hold expires or the slot can no longer be reserved, the booking is not confirmed, the payment is marked `refund_due`, and the dashboard shows an unread payment-review alert. Refunds are currently operational rather than automatic: process the refund in Razorpay first, then record it with **Mark refunded** in the dashboard. Never mark a payment refunded before Razorpay confirms the refund.

### Razorpay Test-to-Live cutover

Complete and verify the full flow in Test Mode before changing Render:

1. Keep `PUBLIC_BOOKING_ENABLED=false` while configuring production.
2. In Razorpay Live Mode, create or obtain a matching `rzp_live_...` key ID and key secret.
3. In Razorpay Live Mode, create and enable the production webhook at `https://ynotframezstudios.com/api/payments/razorpay/webhook` with the required events above.
4. Update Render's `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` together. Do not reuse the Test webhook secret.
5. Set Render's `RAZORPAY_MODE=api` and keep `RAZORPAY_CALLBACK_BASE_URL=https://ynotframezstudios.com`.
6. Deploy while the maintenance gate remains closed. Verify `/health`, the homepage, studio pages, dashboard, email delivery, both calendars, and existing-booking lookup.
7. Perform one controlled real booking and payment. Confirm the Razorpay payment is captured, the database booking is confirmed, the Calendar hold becomes a confirmed event, the email arrives, and the booking lookup shows the actual payment method.
8. Cancel/refund that controlled booking manually if required and reconcile the dashboard with Razorpay.
9. Clear only deliberate test data, then set `PUBLIC_BOOKING_ENABLED=true` in the Render service environment and deploy to open public booking.

Switching Razorpay modes changes which provider data is visible; Test Mode transactions are simulated and do not appear in Live Mode. Keep the Live credentials only in Render or the ignored local `.env`, never in Git or documentation.

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
EMAIL_BCC="owner@example.com,manager@example.com"
SMTP_HOST="smtp.your-provider.com"
SMTP_PORT="587"
SMTP_USERNAME="your-smtp-username"
SMTP_PASSWORD="your-smtp-password-or-app-password"
SMTP_USE_TLS="true"
SMTP_USE_SSL="false"
```

Port 587 normally uses STARTTLS (`SMTP_USE_TLS=true`). Providers using implicit TLS commonly use port 465 with `SMTP_USE_SSL=true` and `SMTP_USE_TLS=false`. Do not enable both. SMTP credentials belong only in the ignored `.env` file or deployment environment, never in Git.

Emails contain both plain-text and HTML versions. The HTML version embeds the YNotFramez Studios PNG logo on an opaque white background so it does not depend on a remote image URL and remains visible in dark-mode mail clients. Booking messages include the reference, booked studio, date, time, duration, purpose, and recorded amount. Payment-hold emails clearly say the booking is not confirmed, show the exact expiry in the studio timezone, and provide retry/contact guidance. Confirmation and update emails also include the selected studio's latest rules. `EMAIL_BCC` accepts comma-separated internal addresses and silently copies every booking email to them; duplicate addresses and the customer's own address are omitted. Delivery failures are logged without cancelling an otherwise valid booking.

## Security note

Never commit `.env` or `google-service-account.json`. If a service-account key was committed previously, removing the file from the current branch is not enough: disable/delete that key in Google Cloud, create a replacement, and consider purging the old file from Git history before sharing the repository further.

## Render and Neon deployment

The repository includes `render.yaml` for a Render Free web service in Singapore. Deployed data is stored in Neon PostgreSQL because Render Free's local filesystem is ephemeral and would discard a SQLite database whenever the service sleeps, restarts, or redeploys.

Public online booking has a production-safe maintenance switch:

```env
PUBLIC_BOOKING_ENABLED="false"
```

When disabled, `/book` shows the branded maintenance page and direct public booking creation returns HTTP 503. Studio pages, the dashboard, existing-booking lookup, payment verification, webhooks, and administrative booking tools remain available. Local `.env` may use `true` for testing. In `render.yaml`, this key uses `sync: false`, so the production value is owned by the Render service environment and is preserved during Blueprint syncs. Change the Render value and deploy whenever public booking needs to be opened or placed under maintenance.

This setup has no required hosting charge within the providers' free allowances, but it does not provide a production uptime or response-time SLA. Render Free sleeps after periods without inbound traffic, so the first visit after an idle period can take about a minute. Neon Free can also suspend idle compute and wakes when the app reconnects. The bounded, worker-isolated Calendar client prevents a slow Google request from queuing every public and admin availability view, but it cannot remove a Render or database cold start.

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
7. The deployed database starts empty. Open `/dashboard` and create the deployment's admin account. This does not change the local admin account. Alternatively, after both accounts exist, use `scripts.sync_admin_password` to copy the local password hash safely.

The Blueprint sets `ADMIN_COOKIE_SECURE=true`, generates a stable admin-session signing secret, and runs one Uvicorn worker. Its committed baseline deliberately keeps Razorpay in stub mode until Test or Live Mode is explicitly enabled in Render. In stub mode, a submitted booking stays payment-pending and holds its slot; use **Record payment** in the Studio Dashboard to complete the test booking, convert its Calendar hold into a confirmed event, and send its confirmation email.

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
