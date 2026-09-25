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
  slotRequestToken: 0,
  slotRequestController: null,
};
const studioPreviewDialog = document.querySelector("#studio-preview-dialog");
const studioPreviewImage = document.querySelector("#studio-preview-image");
const studioPreviewPrevious = document.querySelector("#studio-preview-previous");
const studioPreviewNext = document.querySelector("#studio-preview-next");
const selectedSpacePreview = document.querySelector("#selected-space-preview");
let previewSpace = null;
let previewImages = [];
let previewImageIndex = 0;
let previewOpener = null;

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
  const requestedSpace = new URLSearchParams(window.location.search).get("space");
  const cachedSpaces = window.YNFStudioCache?.read();
  if (cachedSpaces) applySpaces(cachedSpaces, requestedSpace);

  try {
    const freshSpaces = await request("/api/spaces", { cache: "no-store" });
    window.YNFStudioCache?.write(freshSpaces);
    if (!cachedSpaces || JSON.stringify(freshSpaces) !== JSON.stringify(cachedSpaces)) {
      if (!cachedSpaces || state.step === 1) applySpaces(freshSpaces, state.selectedSpace?.id || requestedSpace);
    }
  } catch (error) {
    if (!cachedSpaces) {
      document.querySelector("#space-list").innerHTML = "";
      showMessage(`Could not load studio spaces. ${error.message}`);
    }
  }
}

function applySpaces(spaces, preferredSpaceId = null) {
  state.spaces = spaces;
  renderSpaces();
  if (preferredSpaceId && state.spaces.some((space) => space.id === preferredSpaceId)) {
    const input = document.querySelector(`input[name="space_id"][value="${preferredSpaceId}"]`);
    if (input) input.checked = true;
    selectSpace(preferredSpaceId);
  }
}

function updateStudioPreviewImage(index) {
  if (!previewSpace || previewImages.length === 0) return;
  previewImageIndex = (index + previewImages.length) % previewImages.length;
  studioPreviewImage.src = previewImages[previewImageIndex];
  studioPreviewImage.alt = `${previewSpace.name} studio view ${previewImageIndex + 1}`;
  document.querySelector("#studio-preview-caption").textContent =
    `${previewSpace.name} • ${previewImageIndex + 1} of ${previewImages.length}`;
  const hasMultipleImages = previewImages.length > 1;
  studioPreviewPrevious.hidden = !hasMultipleImages;
  studioPreviewNext.hidden = !hasMultipleImages;
}

function openStudioPreview(spaceId, opener) {
  const space = state.spaces.find((item) => item.id === spaceId);
  if (!space) return;
  const dialogWasOpen = studioPreviewDialog.open;
  if (typeof studioPreviewDialog.showModal !== "function") {
    window.open(`/studios/${encodeURIComponent(space.slug)}`, "_blank", "noopener");
    return;
  }

  previewSpace = space;
  if (opener) previewOpener = opener;
  previewImages = [...new Set([space.cover_image, ...(space.gallery_images || [])].filter(Boolean))];
  previewImageIndex = 0;
  const switcher = document.querySelector("#studio-preview-switcher");
  switcher.innerHTML = state.spaces.map((item) => `
    <button type="button" data-preview-switch-space="${escapeAttribute(item.id)}" aria-pressed="${item.id === space.id}">${escapeText(item.name)}</button>
  `).join("");
  switcher.querySelectorAll("[data-preview-switch-space]").forEach((button) => {
    button.addEventListener("click", () => openStudioPreview(button.dataset.previewSwitchSpace));
  });
  document.querySelector("#studio-preview-title").textContent = space.name;
  document.querySelector("#studio-preview-description").textContent = space.brochure;
  document.querySelector("#studio-preview-rate").textContent = `${currency.format(space.hourly_rate)} per hour`;
  document.querySelector("#studio-preview-capacity").textContent = `Up to ${space.capacity} people`;
  document.querySelector("#studio-preview-dimensions").textContent = space.dimensions;
  document.querySelector("#studio-preview-minimum").textContent =
    `${space.min_duration_hours} hour${space.min_duration_hours === 1 ? "" : "s"}`;
  document.querySelector("#studio-preview-amenities").innerHTML = (space.amenities || [])
    .map((item) => `<span>${escapeText(item)}</span>`)
    .join("");
  document.querySelector("#studio-preview-equipment").innerHTML = (space.equipment || [])
    .map((item) => `<li>${escapeText(item)}</li>`)
    .join("");
  document.querySelector("#studio-preview-rules").textContent = space.rules;
  const selectButton = document.querySelector("#studio-preview-select");
  selectButton.textContent = state.selectedSpace?.id === space.id
    ? `Continue with ${space.name}`
    : `Select ${space.name}`;
  updateStudioPreviewImage(0);
  if (!dialogWasOpen) {
    studioPreviewDialog.showModal();
    studioPreviewDialog.querySelector(".studio-preview-close").focus();
  } else {
    switcher.querySelector('[aria-pressed="true"]').focus();
  }
}

function closeStudioPreview() {
  if (studioPreviewDialog.open) studioPreviewDialog.close();
}

function renderSpaces() {
  const list = document.querySelector("#space-list");
  list.innerHTML = state.spaces.map((space) => `
    <article class="space-card" data-space-id="${escapeAttribute(space.id)}">
      <label class="space-card-choice">
        <input type="radio" name="space_id" value="${escapeAttribute(space.id)}" required>
        <div class="space-visual"><img src="${escapeAttribute(space.cover_image)}" alt="${escapeAttribute(space.name)} photography studio" loading="lazy" decoding="async"></div>
        <div class="card-top"><h3>${escapeText(space.name)}</h3><span class="selector">✓</span></div>
        <p>${escapeText(space.brochure)}</p>
        <div class="rate">${currency.format(space.hourly_rate)} <small>/ hour</small></div>
      </label>
      <button class="space-preview-trigger" type="button" data-preview-space-id="${escapeAttribute(space.id)}" aria-label="View photos and details for ${escapeAttribute(space.name)}">View photos &amp; details <span aria-hidden="true">→</span></button>
    </article>
  `).join("");

  list.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => selectSpace(input.value));
  });
  list.querySelectorAll("[data-preview-space-id]").forEach((button) => {
    button.addEventListener("click", () => openStudioPreview(button.dataset.previewSpaceId, button));
  });
}

function selectSpace(id) {
  state.slotRequestController?.abort();
  state.slotRequestController = null;
  state.slotRequestToken += 1;
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
  document.querySelector("#studio-hours-summary").textContent =
    `Studio hours: ${displayCompactTime(state.selectedSpace.opening_time)} to ${displayCompactTime(state.selectedSpace.closing_time)}`;
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
    showMessage("Select a start time with at least 1 consecutive hour available.");
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

function displayCompactTime(value) {
  return displayTime(value).replace(":00 ", " ");
}

async function loadDaySlots() {
  const bookingDate = form.elements.booking_date.value;
  if (!bookingDate || !state.selectedSpace) return;
  const spaceId = state.selectedSpace.id;
  const requestToken = ++state.slotRequestToken;
  state.slotRequestController?.abort();
  const controller = new AbortController();
  state.slotRequestController = controller;
  const slotGrid = document.querySelector("#slot-grid");
  slotGrid.setAttribute("aria-busy", "true");
  slotGrid.innerHTML = '<p class="slot-loading-message">Checking live calendar availability…</p>'
    + Array.from({ length: 12 }, () => '<span class="slot-button loading"></span>').join("");
  state.selectedSlots = [];
  syncSelectedSlots();
  try {
    const query = new URLSearchParams({ space_id: spaceId, booking_date: bookingDate });
    const result = await request(`/api/availability/day?${query}`, { signal: controller.signal });
    if (
      requestToken !== state.slotRequestToken
      || state.selectedSpace?.id !== spaceId
      || form.elements.booking_date.value !== bookingDate
    ) return;
    state.slots = result.slots;
    document.querySelector("#operating-hours").textContent =
      `${displayTime(result.opening_time)} to ${displayTime(result.closing_time)} · Asia/Kolkata`;
    renderSlots();
  } catch (error) {
    if (error.name === "AbortError" || requestToken !== state.slotRequestToken) return;
    state.slots = [];
    slotGrid.innerHTML = `<p>${escapeText(error.message)}</p>`;
    showMessage(error.message);
  } finally {
    if (requestToken === state.slotRequestToken) {
      slotGrid.removeAttribute("aria-busy");
      state.slotRequestController = null;
    }
  }
}

function renderSlots() {
  const slotGrid = document.querySelector("#slot-grid");
  slotGrid.innerHTML = state.slots.map((slot) => {
    const selected = state.selectedSlots.some((item) => item.start_time === slot.start_time);
    const available = slot.status === "available";
    const slotLabel = `${displayTime(slot.start_time)} - ${displayTime(slot.end_time)}`;
    return `<button type="button" class="slot-button${selected ? " selected" : ""}" data-start="${slot.start_time}" ${available ? "" : "disabled"} aria-pressed="${selected}">${escapeText(slotLabel)}</button>`;
  }).join("");
  slotGrid.querySelectorAll(".slot-button:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => toggleSlot(button.dataset.start));
  });
}

function minimumSelectionFrom(startTime) {
  const startIndex = state.slots.findIndex((slot) => slot.start_time === startTime);
  const minimumHours = state.selectedSpace?.min_duration_hours || 1;
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
    const minimumHours = state.selectedSpace?.min_duration_hours || 1;
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
  const minimumSlots = Math.ceil((state.selectedSpace?.min_duration_hours || 1) / 0.5);
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
    ? `${duration} hour${duration === 1 ? "" : "s"} selected. This studio allows ${state.selectedSpace?.min_duration_hours || 1} to ${state.selectedSpace?.max_duration_hours || 12} hours.`
    : `Select a start time. The minimum ${state.selectedSpace?.min_duration_hours || 1}-hour window will be highlighted automatically.`;
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
  document.querySelector('[data-summary="date"]').textContent = formatDate(form.elements.booking_date.value) || "Not selected";
  document.querySelector('[data-summary="time"]').textContent = first && last
    ? `${displayTime(first.start_time)} to ${displayTime(last.end_time)}`
    : "Not selected";
  document.querySelector('[data-summary="price"]').textContent = currency.format(
    (state.selectedSpace?.hourly_rate || 0) * duration
  );
  selectedSpacePreview.hidden = !state.selectedSpace;
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
    <div><small>TIME</small><strong>${escapeText(`${displayTime(first.start_time)} to ${displayTime(last.end_time)}`)}</strong></div>
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
    ? `Your confirmation has been emailed to ${booking.customer_email}.\nYour studio time is now reserved.`
    : checkoutReady
      ? "Your studio time is temporarily held for two hours. Complete Razorpay Checkout below to confirm it."
      : `Online checkout could not be prepared. Your booking is not confirmed; retry shortly or contact the studio team with ${booking.reference}.`);
  document.querySelector("#confirmation-details").innerHTML = `
    <div><small>REFERENCE</small><strong>${escapeText(booking.reference)}</strong></div>
    <div><small>DATE & TIME</small><strong>${escapeText(formatDate(booking.booking_date))} · ${escapeText(displayTime(booking.start_time))} to ${escapeText(displayTime(booking.end_time))}</strong></div>
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
    `SUMMARY:${booking.space_name}: ${booking.reference}`,
    `DESCRIPTION:Studio booking for ${booking.customer_name}`,
    "END:VEVENT", "END:VCALENDAR",
  ].join("\r\n");
  const calendarLink = document.querySelector("#calendar-link");
  calendarLink.hidden = !confirmed;
  calendarLink.href = `data:text/calendar;charset=utf-8,${encodeURIComponent(calendarContent)}`;
  calendarLink.download = `${booking.reference}.ics`;
  const shareText = `My YNotFramez Studios booking ${booking.reference} is confirmed: ${booking.space_name}, ${formatDate(booking.booking_date)}, ${displayTime(booking.start_time)} to ${displayTime(booking.end_time)}.`;
  const whatsappShare = document.querySelector("#whatsapp-share");
  whatsappShare.hidden = !confirmed;
  whatsappShare.href = `https://wa.me/?text=${encodeURIComponent(shareText)}`;
  document.querySelector("#print-booking").hidden = !confirmed;
  document.querySelector("#retrieve-booking").href = `/my-booking?reference=${encodeURIComponent(booking.reference)}`;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelector("#payment-button").addEventListener("click", prepareCheckout);

function startNewBooking() {
  state.slotRequestController?.abort();
  state.slotRequestController = null;
  state.slotRequestToken += 1;
  state.selectedSpace = null;
  state.slots = [];
  state.selectedSlots = [];
  state.slotChecked = false;
  state.currentBooking = null;
  state.paymentNotice = "";

  form.reset();
  form.querySelectorAll(".invalid").forEach((field) => field.classList.remove("invalid"));
  form.elements.purpose.replaceChildren(new Option("Choose a purpose", ""));
  document.querySelector("#space-rules").hidden = true;
  document.querySelector("#confirmation").hidden = true;
  document.querySelector(".progress").hidden = false;
  form.hidden = false;
  renderSpaces();
  syncSelectedSlots();
  goToStep(1);
  window.history.replaceState({}, "", "/book");
}

document.querySelector("#new-booking").addEventListener("click", startNewBooking);
document.querySelector("#print-booking").addEventListener("click", () => window.print());

selectedSpacePreview.addEventListener("click", () => {
  if (state.selectedSpace) openStudioPreview(state.selectedSpace.id, selectedSpacePreview);
});
studioPreviewPrevious.addEventListener("click", () => updateStudioPreviewImage(previewImageIndex - 1));
studioPreviewNext.addEventListener("click", () => updateStudioPreviewImage(previewImageIndex + 1));
studioPreviewDialog.querySelectorAll("[data-close-studio-preview]").forEach((button) => {
  button.addEventListener("click", closeStudioPreview);
});
studioPreviewDialog.addEventListener("click", (event) => {
  if (event.target === studioPreviewDialog) closeStudioPreview();
});
studioPreviewDialog.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft" && previewImages.length > 1) {
    event.preventDefault();
    updateStudioPreviewImage(previewImageIndex - 1);
  }
  if (event.key === "ArrowRight" && previewImages.length > 1) {
    event.preventDefault();
    updateStudioPreviewImage(previewImageIndex + 1);
  }
});
studioPreviewDialog.addEventListener("close", () => {
  previewOpener?.focus();
  previewOpener = null;
});
document.querySelector("#studio-preview-select").addEventListener("click", () => {
  if (!previewSpace) return;
  const isChangingStudio = state.selectedSpace && state.selectedSpace.id !== previewSpace.id;
  if (
    isChangingStudio
    && state.selectedSlots.length > 0
    && !window.confirm("Changing the studio will clear your selected time because availability and pricing may differ.")
  ) return;

  if (state.selectedSpace?.id !== previewSpace.id) {
    const input = document.querySelector(`input[name="space_id"][value="${previewSpace.id}"]`);
    if (input) input.checked = true;
    selectSpace(previewSpace.id);
    if (state.step > 1) goToStep(2);
  }
  closeStudioPreview();
});

const termsDialog = document.querySelector("#terms-dialog");
const termsOpen = document.querySelector("#terms-open");
termsOpen.addEventListener("click", (event) => {
  if (typeof termsDialog.showModal !== "function") return;
  event.preventDefault();
  termsDialog.showModal();
  termsDialog.querySelector(".terms-close").focus();
});
termsDialog.querySelectorAll("[data-close-terms]").forEach((button) => {
  button.addEventListener("click", () => termsDialog.close());
});
termsDialog.addEventListener("close", () => termsOpen.focus());

const today = new Date();
const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().split("T")[0];
form.elements.booking_date.min = localToday;
const maxBookingDate = new Date(today);
maxBookingDate.setDate(maxBookingDate.getDate() + 90);
form.elements.booking_date.max = new Date(maxBookingDate.getTime() - maxBookingDate.getTimezoneOffset() * 60000).toISOString().split("T")[0];
loadSpaces();
