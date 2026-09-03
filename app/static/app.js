const form = document.querySelector("#booking-form");
const message = document.querySelector("#global-message");
document.querySelector("#year").textContent = new Date().getFullYear();
const state = {
  step: 1,
  spaces: [],
  selectedSpace: null,
  slots: [],
  selectedSlots: [],
  slotChecked: false,
  currentBooking: null,
  paymentNotice: "",
};

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

function showMessage(text = "") {
  message.textContent = text;
  message.hidden = !text;
  if (text) message.scrollIntoView({ behavior: "smooth", block: "center" });
}

function escapeText(value) {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
}

function escapeAttribute(value) {
  return escapeText(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg).join(". ")
      : payload.detail;
    throw new Error(detail || "Something went wrong. Please try again.");
  }
  return payload;
}

async function loadSpaces() {
  try {
    state.spaces = await request("/api/spaces");
    renderSpaces();
    const requestedSpace = new URLSearchParams(window.location.search).get("space");
    if (requestedSpace && state.spaces.some((space) => space.id === requestedSpace)) {
      const input = document.querySelector(`input[name="space_id"][value="${requestedSpace}"]`);
      if (input) input.checked = true;
      selectSpace(requestedSpace);
    }
  } catch (error) {
    document.querySelector("#space-list").innerHTML = "";
    showMessage(`Could not load studio spaces. ${error.message}`);
  }
}

function renderSpaces() {
  const list = document.querySelector("#space-list");
  list.innerHTML = state.spaces.map((space) => `
    <label class="space-card" data-space-id="${escapeAttribute(space.id)}">
      <input type="radio" name="space_id" value="${escapeAttribute(space.id)}" required>
      <div class="space-visual"><img src="${escapeAttribute(space.cover_image)}" alt="${escapeAttribute(space.name)} photography studio" loading="lazy" decoding="async"></div>
      <div class="card-top"><h3>${escapeText(space.name)}</h3><span class="selector">✓</span></div>
      <p>${escapeText(space.brochure)}</p>
      <div class="rate">${currency.format(space.hourly_rate)} <small>/ hour</small></div>
    </label>
  `).join("");

  list.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => selectSpace(input.value));
  });
}

function selectSpace(id) {
  state.selectedSpace = state.spaces.find((space) => space.id === id);
  state.slotChecked = false;
  state.slots = [];
  state.selectedSlots = [];
  syncSelectedSlots();
  document.querySelectorAll(".space-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.spaceId === id);
  });
  const rules = document.querySelector("#space-rules");
  rules.querySelector("p").textContent = state.selectedSpace.rules;
  rules.hidden = false;
  const purposeSelect = form.elements.purpose;
  const purposeOptions = state.selectedSpace.booking_purposes.map((purpose) => new Option(purpose, purpose));
  purposeSelect.replaceChildren(new Option("Choose a purpose", ""), ...purposeOptions);
  purposeSelect.value = "";
  updatePrice();
  updateLiveSummary();
  showMessage();
}

function goToStep(step) {
  state.step = step;
  document.querySelectorAll(".form-step").forEach((section) => {
    const active = Number(section.dataset.step) === step;
    section.hidden = !active;
    section.classList.toggle("active", active);
  });
  document.querySelectorAll("[data-progress]").forEach((item) => {
    const progressStep = Number(item.dataset.progress);
    const active = progressStep === step;
    item.classList.toggle("active", active);
    item.classList.toggle("complete", progressStep < step);
    if (active) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
    const circle = item.querySelector(":scope > span");
    circle.textContent = progressStep < step ? "✓" : String(progressStep).padStart(2, "0");
  });
  showMessage();
  updateLiveSummary();
  if (step === 2 && form.elements.booking_date.value && state.slots.length === 0) loadDaySlots();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fieldsForStep(step) {
  return [...document.querySelector(`[data-step="${step}"]`).querySelectorAll("input, select, textarea")]
    .filter((field) => field.type !== "button" && field.type !== "radio");
}

function validateStep(step) {
  if (step === 1 && !state.selectedSpace) {
    showMessage("Choose one of the studio spaces to continue.");
    return false;
  }
  if (step === 2 && state.selectedSlots.length === 0) {
    showMessage("Select a start time with at least 2 consecutive hours available.");
    return false;
  }
  if (step === 2 && state.selectedSpace) {
    const duration = state.selectedSlots.length * 0.5;
    if (duration < state.selectedSpace.min_duration_hours || duration > state.selectedSpace.max_duration_hours) {
      showMessage(`Choose between ${state.selectedSpace.min_duration_hours} and ${state.selectedSpace.max_duration_hours} hours for this studio.`);
      return false;
    }
  }
  const invalid = fieldsForStep(step).find((field) => !field.checkValidity());
  fieldsForStep(step).forEach((field) => field.classList.toggle("invalid", !field.checkValidity()));
  if (invalid) {
    invalid.reportValidity();
    showMessage("Please complete the highlighted details before continuing.");
    return false;
  }
  return true;
}

function schedulePayload() {
  return {
    space_id: state.selectedSpace.id,
    booking_date: form.elements.booking_date.value,
    start_time: form.elements.start_time.value,
    duration_hours: Number(form.elements.duration_hours.value),
  };
}

function displayTime(value) {
  const [hours, minutes] = value.split(":").map(Number);
  const period = hours >= 12 ? "PM" : "AM";
  const displayHours = hours % 12 || 12;
  return `${displayHours}:${String(minutes).padStart(2, "0")} ${period}`;
}

async function loadDaySlots() {
  const bookingDate = form.elements.booking_date.value;
  if (!bookingDate || !state.selectedSpace) return;
  const slotGrid = document.querySelector("#slot-grid");
  slotGrid.innerHTML = Array.from({ length: 12 }, () => '<span class="slot-button loading"></span>').join("");
  state.selectedSlots = [];
  syncSelectedSlots();
  try {
    const query = new URLSearchParams({ space_id: state.selectedSpace.id, booking_date: bookingDate });
    const result = await request(`/api/availability/day?${query}`);
    state.slots = result.slots;
    document.querySelector("#operating-hours").textContent =
      `${displayTime(result.opening_time)} – ${displayTime(result.closing_time)} · Asia/Kolkata`;
    renderSlots();
  } catch (error) {
    state.slots = [];
    slotGrid.innerHTML = `<p>${escapeText(error.message)}</p>`;
    showMessage(error.message);
  }
}

function renderSlots() {
  const slotGrid = document.querySelector("#slot-grid");
  slotGrid.innerHTML = state.slots.map((slot) => {
    const selected = state.selectedSlots.some((item) => item.start_time === slot.start_time);
    const available = slot.status === "available";
    return `<button type="button" class="slot-button${selected ? " selected" : ""}" data-start="${slot.start_time}" ${available ? "" : "disabled"} aria-pressed="${selected}">${displayTime(slot.start_time)}</button>`;
  }).join("");
  slotGrid.querySelectorAll(".slot-button:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => toggleSlot(button.dataset.start));
  });
}

function minimumSelectionFrom(startTime) {
  const startIndex = state.slots.findIndex((slot) => slot.start_time === startTime);
  const minimumHours = state.selectedSpace?.min_duration_hours || 2;
  const requiredSlots = Math.ceil(minimumHours / 0.5);
  const candidate = state.slots.slice(startIndex, startIndex + requiredSlots);
  const consecutive = candidate.every(
    (slot, index) => slot.status === "available"
      && (index === 0 || candidate[index - 1].end_time === slot.start_time),
  );
  return startIndex >= 0 && candidate.length === requiredSlots && consecutive ? candidate : null;
}

function selectMinimumDuration(startTime) {
  const candidate = minimumSelectionFrom(startTime);
  if (!candidate) {
    const minimumHours = state.selectedSpace?.min_duration_hours || 2;
    showMessage(`Choose a start time with at least ${minimumHours} consecutive hours available.`);
    return false;
  }
  state.selectedSlots = candidate;
  return true;
}

function toggleSlot(startTime) {
  const slot = state.slots.find((item) => item.start_time === startTime);
  if (!slot || slot.status !== "available") return;
  showMessage();
  const minimumSlots = Math.ceil((state.selectedSpace?.min_duration_hours || 2) / 0.5);
  const existingIndex = state.selectedSlots.findIndex((item) => item.start_time === startTime);
  if (existingIndex >= 0) {
    if (existingIndex === 0 || existingIndex === state.selectedSlots.length - 1) {
      if (state.selectedSlots.length > minimumSlots) state.selectedSlots.splice(existingIndex, 1);
      else showMessage(`The minimum booking duration is ${minimumSlots * 0.5} hours.`);
    } else {
      if (selectMinimumDuration(startTime)) {
        showMessage("A new minimum-duration selection has been started from this time.");
      }
    }
  } else if (state.selectedSlots.length === 0) {
    selectMinimumDuration(startTime);
  } else {
    const candidate = [...state.selectedSlots, slot].sort((a, b) => a.start_time.localeCompare(b.start_time));
    const consecutive = candidate.every((item, index) => index === 0 || candidate[index - 1].end_time === item.start_time);
    if (consecutive && candidate.length * 0.5 <= state.selectedSpace.max_duration_hours) state.selectedSlots = candidate;
    else if (consecutive) showMessage(`This studio allows bookings up to ${state.selectedSpace.max_duration_hours} hours.`);
    else if (selectMinimumDuration(startTime)) {
      showMessage("Half-hour slots must be consecutive. A new selection has been started.");
    }
  }
  state.slotChecked = false;
  syncSelectedSlots();
  renderSlots();
}

function syncSelectedSlots() {
  const first = state.selectedSlots[0];
  form.elements.start_time.value = first?.start_time || "";
  const duration = state.selectedSlots.length * 0.5;
  form.elements.duration_hours.value = state.selectedSlots.length ? String(duration) : "";
  const note = document.querySelector("#slot-note");
  note.className = "";
  note.textContent = state.selectedSlots.length
    ? `${duration} hour${duration === 1 ? "" : "s"} selected. This studio allows ${state.selectedSpace?.min_duration_hours || 2}–${state.selectedSpace?.max_duration_hours || 12} hours.`
    : `Select a start time. The minimum ${state.selectedSpace?.min_duration_hours || 2}-hour window will be highlighted automatically.`;
  updatePrice();
  updateLiveSummary();
}

async function checkSlot(button) {
  const note = document.querySelector("#slot-note");
  button.disabled = true;
  button.firstChild.textContent = "Checking… ";
  try {
    const result = await request("/api/availability", {
      method: "POST",
      body: JSON.stringify(schedulePayload()),
    });
    state.slotChecked = result.available;
    note.textContent = result.message;
    note.className = result.available ? "available" : "unavailable";
    if (result.available) goToStep(3);
    else showMessage(result.message);
  } catch (error) {
    state.slotChecked = false;
    note.textContent = error.message;
    note.className = "unavailable";
    showMessage(error.message);
  } finally {
    button.disabled = false;
    button.firstChild.textContent = "Check availability ";
  }
}

function updatePrice() {
  const duration = Number(form.elements.duration_hours.value || 0);
  const amount = state.selectedSpace ? state.selectedSpace.hourly_rate * duration : 0;
  document.querySelector("#estimated-total").textContent = currency.format(amount);
}

function updateLiveSummary() {
  const duration = Number(form.elements.duration_hours.value || 0);
  const first = state.selectedSlots[0];
  const last = state.selectedSlots[state.selectedSlots.length - 1];
  document.querySelector('[data-summary="space"]').textContent = state.selectedSpace?.name || "Not selected";
  document.querySelector('[data-summary="date"]').textContent = formatDate(form.elements.booking_date.value) || "—";
  document.querySelector('[data-summary="time"]').textContent = first && last
    ? `${displayTime(first.start_time)} – ${displayTime(last.end_time)}`
    : "—";
  document.querySelector('[data-summary="price"]').textContent = currency.format(
    (state.selectedSpace?.hourly_rate || 0) * duration
  );
}

function formatDate(rawDate) {
  if (!rawDate) return "";
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" })
    .format(new Date(`${rawDate}T12:00:00`));
}

function renderSummary() {
  const data = new FormData(form);
  const first = state.selectedSlots[0];
  const last = state.selectedSlots[state.selectedSlots.length - 1];
  document.querySelector("#booking-summary").innerHTML = `
    <div><small>STUDIO</small><strong>${escapeText(state.selectedSpace.name)}</strong></div>
    <div><small>DATE</small><strong>${escapeText(formatDate(data.get("booking_date")))}</strong></div>
    <div><small>TIME</small><strong>${escapeText(`${displayTime(first.start_time)} – ${displayTime(last.end_time)}`)}</strong></div>
    <div><small>TOTAL</small><strong>${escapeText(currency.format(state.selectedSpace.hourly_rate * Number(data.get("duration_hours"))))}</strong></div>
  `;
}

document.querySelectorAll("[data-next]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!validateStep(state.step)) return;
    if (state.step === 2) {
      await checkSlot(button);
      return;
    }
    if (state.step === 3) renderSummary();
    goToStep(state.step + 1);
  });
});

document.querySelectorAll("[data-back]").forEach((button) => {
  button.addEventListener("click", () => goToStep(state.step - 1));
});

form.elements.booking_date.addEventListener("change", () => {
  state.slotChecked = false;
  updateLiveSummary();
  loadDaySlots();
});

form.addEventListener("input", (event) => {
  if (event.target.matches("input, select, textarea")) event.target.classList.remove("invalid");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!validateStep(4) || !state.slotChecked) {
    if (!state.slotChecked) {
      showMessage("Your slot needs to be checked again. Please return to the date step.");
      goToStep(2);
    }
    return;
  }

  const submitButton = document.querySelector("#submit-booking");
  const data = new FormData(form);
  const payload = {
    ...schedulePayload(),
    customer_name: data.get("customer_name"),
    customer_email: data.get("customer_email"),
    phone_number: data.get("phone_number"),
    purpose: data.get("purpose"),
    terms_accepted: data.get("terms_accepted") === "on",
    payment_mode: data.get("payment_mode"),
  };

  submitButton.disabled = true;
  submitButton.firstChild.textContent = "Preparing checkout… ";
  try {
    const booking = await request("/api/bookings", { method: "POST", body: JSON.stringify(payload) });
    showConfirmation(booking);
    if (booking.checkout?.key_id) openStandardCheckout(booking);
  } catch (error) {
    showMessage(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.firstChild.textContent = "Proceed to payment ";
  }
});

async function prepareCheckout() {
  const booking = state.currentBooking;
  if (!booking) return;
  if (booking.checkout?.key_id) {
    openStandardCheckout(booking);
    return;
  }
  const paymentButton = document.querySelector("#payment-button");
  paymentButton.disabled = true;
  paymentButton.firstChild.textContent = "Preparing checkout… ";
  try {
    const updated = await request("/api/bookings/checkout", {
      method: "POST",
      body: JSON.stringify({ reference: booking.reference, customer_email: booking.customer_email }),
    });
    state.currentBooking = updated;
    showConfirmation(updated);
    openStandardCheckout(updated);
  } catch (error) {
    showConfirmation(booking, error.message);
  } finally {
    paymentButton.disabled = false;
    paymentButton.firstChild.textContent = "Complete payment ";
  }
}

function openStandardCheckout(booking) {
  state.paymentNotice = "";
  window.YNFPayments.open(booking, {
    onVerifying: () => showConfirmation(
      state.currentBooking,
      "Payment received. We are confirming it securely. Please wait and do not pay again.",
      true,
    ),
    onVerified: (updated) => showConfirmation(updated),
    onProcessing: (updated) => showConfirmation(
      updated,
      "Your payment is authorised and awaiting confirmation. Please do not pay again. This can take a few minutes.",
      true,
    ),
    onFailure: (detail) => {
      state.paymentNotice = `${detail} Your temporary studio hold remains active, so you can retry payment.`;
    },
    onDismiss: () => showConfirmation(
      state.currentBooking,
      state.paymentNotice || "Checkout was closed before payment. Your temporary studio hold remains active, and you can retry below.",
    ),
    onVerificationError: (detail) => showConfirmation(
      state.currentBooking,
      `${detail} Please do not pay again. Check Find My Booking shortly or contact the studio team with your reference.`,
      true,
    ),
    onError: (detail) => showConfirmation(state.currentBooking, detail),
  });
}

function showConfirmation(booking, notice = "", paymentProcessing = false) {
  state.currentBooking = booking;
  form.hidden = true;
  document.querySelector(".progress").hidden = true;
  const confirmation = document.querySelector("#confirmation");
  confirmation.hidden = false;
  const confirmed = booking.status === "confirmed";
  const checkoutReady = Boolean(booking.checkout?.key_id);
  const successMark = document.querySelector(".success-mark");
  successMark.textContent = confirmed ? "✓" : "…";
  successMark.classList.toggle("pending", !confirmed);
  document.querySelector("#confirmation-kicker").textContent = confirmed
    ? "BOOKING CONFIRMED"
    : paymentProcessing ? "PAYMENT CONFIRMING" : "PAYMENT REQUIRED";
  document.querySelector("#confirmation-title").textContent = confirmed
    ? "Your booking has been confirmed."
    : paymentProcessing ? "Confirming your payment…" : "Complete payment to reserve.";
  document.querySelector("#confirmation-copy").textContent = notice || (confirmed
    ? `Your confirmation has been emailed to ${booking.customer_email}. Your studio time is now reserved.`
    : checkoutReady
      ? "Your studio time is temporarily held for two hours. Complete Razorpay Checkout below to confirm it."
      : `Online checkout could not be prepared. Your booking is not confirmed; retry shortly or contact the studio team with ${booking.reference}.`);
  document.querySelector("#confirmation-details").innerHTML = `
    <div><small>REFERENCE</small><strong>${escapeText(booking.reference)}</strong></div>
    <div><small>DATE & TIME</small><strong>${escapeText(formatDate(booking.booking_date))} · ${escapeText(displayTime(booking.start_time))}–${escapeText(displayTime(booking.end_time))}</strong></div>
    <div><small>AMOUNT</small><strong>${escapeText(currency.format(booking.total_amount))}</strong></div>
  `;
  const paymentButton = document.querySelector("#payment-button");
  paymentButton.hidden = confirmed || paymentProcessing;
  paymentButton.disabled = paymentProcessing;
  const calendarContent = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//YNotFramez Studios//Studio Booking//EN",
    "BEGIN:VEVENT", `UID:${booking.reference}@ynotframez`,
    `DTSTART;TZID=Asia/Kolkata:${booking.booking_date.replaceAll("-", "")}T${booking.start_time.replace(":", "")}00`,
    `DTEND;TZID=Asia/Kolkata:${booking.booking_date.replaceAll("-", "")}T${booking.end_time.replace(":", "")}00`,
    `SUMMARY:${booking.space_name} — ${booking.reference}`,
    `DESCRIPTION:Studio booking for ${booking.customer_name}`,
    "END:VEVENT", "END:VCALENDAR",
  ].join("\r\n");
  const calendarLink = document.querySelector("#calendar-link");
  calendarLink.hidden = !confirmed;
  calendarLink.href = `data:text/calendar;charset=utf-8,${encodeURIComponent(calendarContent)}`;
  calendarLink.download = `${booking.reference}.ics`;
  const shareText = `My YNotFramez Studios booking ${booking.reference} is confirmed: ${booking.space_name}, ${formatDate(booking.booking_date)}, ${displayTime(booking.start_time)}–${displayTime(booking.end_time)}.`;
  const whatsappShare = document.querySelector("#whatsapp-share");
  whatsappShare.hidden = !confirmed;
  whatsappShare.href = `https://wa.me/?text=${encodeURIComponent(shareText)}`;
  document.querySelector("#print-booking").hidden = !confirmed;
  document.querySelector("#retrieve-booking").href = `/my-booking?reference=${encodeURIComponent(booking.reference)}`;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelector("#payment-button").addEventListener("click", prepareCheckout);
document.querySelector("#new-booking").addEventListener("click", () => window.location.reload());
document.querySelector("#print-booking").addEventListener("click", () => window.print());

const today = new Date();
const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().split("T")[0];
form.elements.booking_date.min = localToday;
const maxBookingDate = new Date(today);
maxBookingDate.setDate(maxBookingDate.getDate() + 90);
form.elements.booking_date.max = new Date(maxBookingDate.getTime() - maxBookingDate.getTimezoneOffset() * 60000).toISOString().split("T")[0];
loadSpaces();
