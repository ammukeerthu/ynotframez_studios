const form = document.querySelector("#lookup-form");
const lookupView = document.querySelector("#lookup-view");
const resultView = document.querySelector("#booking-result");
document.querySelector("#year").textContent = new Date().getFullYear();
const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
let currentBooking = null;

async function bookingApi(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).filter(Boolean).join(" ")
      : body.detail;
    throw new Error(detail || "We could not retrieve that booking.");
  }
  return body;
}

async function lookupBooking(payload) {
  return bookingApi("/api/bookings/lookup", payload);
}

function displayTime(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return `${hours % 12 || 12}:${String(minutes).padStart(2, "0")} ${hours >= 12 ? "PM" : "AM"}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "long", year: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}

function paymentMethodLabel(method) {
  const labels = {
    upi: "UPI",
    netbanking: "Netbanking",
    card: "Card",
    emi: "EMI",
    wallet: "Wallet",
    paylater: "Pay Later",
    cardless_emi: "Cardless EMI",
    pay_at_studio: "Pay at studio",
    recorded_by_studio: "Recorded by studio",
    pending: "Online payment pending",
    online: "Online payment",
  };
  return labels[method] || method.replaceAll("_", " ");
}

function showBooking(booking) {
  currentBooking = booking;
  lookupView.hidden = true;
  resultView.hidden = false;
  document.querySelector("#result-reference").textContent = booking.reference;
  document.querySelector("#result-greeting").textContent = `Booking details for ${booking.customer_name} · ${booking.customer_email}`;
  const bookingStatus = document.querySelector("#result-booking-status");
  bookingStatus.textContent = booking.booking_status.replaceAll("_", " ");
  bookingStatus.className = booking.booking_status;
  const paymentStatus = document.querySelector("#result-payment-status");
  paymentStatus.textContent = `Payment ${booking.payment_status.replaceAll("_", " ")}`;
  paymentStatus.className = booking.payment_status;
  document.querySelector("#result-space").textContent = booking.space_name;
  document.querySelector("#result-date").textContent = formatDate(booking.booking_date);
  document.querySelector("#result-time").textContent = `${displayTime(booking.start_time)} to ${displayTime(booking.end_time)}`;
  document.querySelector("#result-duration").textContent = `${booking.duration_hours} hour${booking.duration_hours === 1 ? "" : "s"}`;
  document.querySelector("#result-total").textContent = booking.balance_due
    ? `${currency.format(booking.total_amount)} · ${currency.format(booking.balance_due)} due`
    : currency.format(booking.total_amount);
  document.querySelector("#result-payment-mode").textContent = paymentMethodLabel(booking.payment_method);

  const note = document.querySelector("#result-note");
  if (booking.booking_status === "cancelled") note.textContent = "This booking has been cancelled. Contact the studio if you need help with a refund or a new session.";
  else if (booking.booking_status === "expired" && booking.payment_status === "refund_due") note.textContent = "Payment arrived after this hold expired and requires studio review. Do not pay again; contact the studio with your booking reference.";
  else if (booking.booking_status === "expired") note.textContent = "This unpaid booking hold has expired, and the studio time is available to others. Please create a new booking.";
  else if (booking.payment_status === "partially_paid") note.textContent = `${currency.format(booking.amount_paid)} has been received. The remaining balance is ${currency.format(booking.balance_due)}.`;
  else if (booking.payment_status === "pending") note.textContent = "Your studio time is temporarily held while payment is pending.";
  else note.textContent = "Your booking is confirmed and the recorded payment is complete.";

  const paymentLink = document.querySelector("#result-payment-link");
  paymentLink.hidden = !booking.payment_link;
  if (booking.payment_link) paymentLink.href = booking.payment_link;
  const paymentButton = document.querySelector("#result-payment-button");
  paymentButton.hidden = !(
    booking.booking_status === "payment_pending"
    && booking.payment_status === "pending"
    && booking.payment_mode === "pay_now"
    && !booking.payment_link
  );
  const calendarLink = document.querySelector("#result-calendar");
  calendarLink.hidden = booking.booking_status !== "confirmed";
  if (!calendarLink.hidden) {
    const calendar = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//YNotFramez Studios//Studio Booking//EN", "BEGIN:VEVENT",
      `UID:${booking.reference}@ynotframez`,
      `DTSTART;TZID=Asia/Kolkata:${booking.booking_date.replaceAll("-", "")}T${booking.start_time.replace(":", "")}00`,
      `DTEND;TZID=Asia/Kolkata:${booking.booking_date.replaceAll("-", "")}T${booking.end_time.replace(":", "")}00`,
      `SUMMARY:${booking.space_name}: ${booking.reference}`,
      "END:VEVENT", "END:VCALENDAR",
    ].join("\r\n");
    calendarLink.href = `data:text/calendar;charset=utf-8,${encodeURIComponent(calendar)}`;
    calendarLink.download = `${booking.reference}.ics`;
  }
}

async function refreshCurrentBooking() {
  if (!currentBooking) return;
  const refreshed = await lookupBooking({
    reference: currentBooking.reference,
    customer_email: currentBooking.customer_email,
  });
  showBooking(refreshed);
}

document.querySelector("#result-payment-button").addEventListener("click", async () => {
  if (!currentBooking) return;
  const note = document.querySelector("#result-note");
  const paymentButton = document.querySelector("#result-payment-button");
  paymentButton.disabled = true;
  note.textContent = "Preparing secure checkout…";
  try {
    currentBooking = await bookingApi("/api/bookings/checkout", {
      reference: currentBooking.reference,
      customer_email: currentBooking.customer_email,
    });
    showBooking(currentBooking);
  } catch (error) {
    note.textContent = error.message;
    paymentButton.disabled = false;
    return;
  }
  paymentButton.disabled = false;
  window.YNFPayments.open(currentBooking, {
    onVerifying: () => {
      paymentButton.hidden = true;
      note.textContent = "Payment received. We are confirming it securely. Please wait and do not pay again.";
    },
    onVerified: async () => {
      try {
        await refreshCurrentBooking();
      } catch (error) {
        note.textContent = error.message;
      }
    },
    onProcessing: () => {
      paymentButton.hidden = true;
      note.textContent = "Your payment is authorised and awaiting confirmation. Please do not pay again. This can take a few minutes.";
    },
    onFailure: (detail) => {
      note.textContent = `${detail} Your temporary studio hold remains active, so you can retry safely.`;
    },
    onDismiss: () => {
      note.textContent = "Checkout was closed before payment. Your temporary studio hold remains active.";
    },
    onVerificationError: (detail) => {
      paymentButton.hidden = true;
      note.textContent = `${detail} Please do not pay again. Check this booking again shortly or contact the studio team.`;
    },
    onError: (detail) => {
      note.textContent = detail;
    },
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const button = document.querySelector("#lookup-button");
  const message = document.querySelector("#lookup-message");
  button.disabled = true;
  button.firstChild.textContent = "Finding booking… ";
  message.hidden = true;
  try {
    const booking = await lookupBooking({
      reference: data.get("reference"),
      customer_email: data.get("customer_email"),
    });
    showBooking(booking);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
    button.firstChild.textContent = "Find booking ";
  }
});

form.elements.reference.addEventListener("input", () => {
  form.elements.reference.value = form.elements.reference.value.toUpperCase();
});
document.querySelector("#new-lookup").addEventListener("click", () => {
  currentBooking = null;
  resultView.hidden = true;
  lookupView.hidden = false;
  form.elements.customer_email.value = "";
  form.elements.reference.focus();
});
document.querySelector("#result-print").addEventListener("click", () => window.print());

const reference = new URLSearchParams(window.location.search).get("reference");
if (reference) form.elements.reference.value = reference.toUpperCase();
