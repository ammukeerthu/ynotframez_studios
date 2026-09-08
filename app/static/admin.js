const loginView = document.querySelector("#login-view");
const dashboardView = document.querySelector("#dashboard-view");
const loginForm = document.querySelector("#admin-login-form");
const setupForm = document.querySelector("#admin-setup-form");
const passwordModal = document.querySelector("#password-modal");
const bookingModal = document.querySelector("#booking-modal");
const bookingEditForm = document.querySelector("#booking-edit-form");
const bookingFilters = document.querySelector("#booking-filters");
const availabilityFilters = document.querySelector("#availability-filters");
const availabilityBlockForm = document.querySelector("#availability-block-form");
const alertCenter = document.querySelector("#alert-center");
const alertBell = document.querySelector("#alert-bell");
const alertList = document.querySelector("#alert-list");
const desktopAlertsButton = document.querySelector("#desktop-alerts-button");
const accountMenuButton = document.querySelector("#account-menu-button");
const accountMenuPanel = document.querySelector("#account-menu-panel");
const dashboardHomeLink = document.querySelector("#dashboard-home-link");
let adminBookings = [];
let studioSettings = [];
let alertPollTimer = null;
let alertsPayload = { unread_count: 0, new_bookings: [], operational: [] };
let alertFilter = "all";
let availabilityRequestToken = 0;
let availabilityRequestController = null;
const dashboardMessageTimers = new WeakMap();
const MAX_BLOCK_DURATION_HOURS = 12;
const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const adminNavLinks = Array.from(document.querySelectorAll(".admin-shell aside nav a[href^='#']"));
const adminSections = adminNavLinks
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);

function safe(value) {
  const element = document.createElement("span");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function safeAttr(value) {
  return safe(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg).filter(Boolean).join(" ")
      : payload.detail;
    const error = new Error(detail || "Something went wrong.");
    error.status = response.status;
    throw error;
  }
  return payload;
}

function showLogin(message = "") {
  if (alertPollTimer) window.clearInterval(alertPollTimer);
  alertPollTimer = null;
  alertCenter.hidden = true;
  alertBell.setAttribute("aria-expanded", "false");
  accountMenuPanel.hidden = true;
  accountMenuButton.setAttribute("aria-expanded", "false");
  dashboardView.hidden = true;
  loginView.hidden = false;
  setupForm.hidden = true;
  loginForm.hidden = false;
  const messageBox = document.querySelector("#login-message");
  messageBox.textContent = message;
  messageBox.hidden = !message;
}

function showSetup(message = "") {
  dashboardView.hidden = true;
  loginView.hidden = false;
  loginForm.hidden = true;
  setupForm.hidden = false;
  const messageBox = document.querySelector("#setup-message");
  messageBox.textContent = message;
  messageBox.hidden = !message;
}

async function showDashboard(username) {
  loginView.hidden = true;
  const initialSection = showAdminSection(window.location.hash.slice(1));
  dashboardView.hidden = false;
  document.querySelector("#admin-username").textContent = username || "admin";
  await loadStudioSettings();
  const initialLoads = [loadOverview(), loadBookings(), loadAlerts()];
  if (initialSection === "availability") initialLoads.push(loadAvailability());
  await Promise.all(initialLoads);
  startAlertPolling();
  updateDesktopAlertsButton();
}

function setActiveNavigation(sectionId) {
  adminNavLinks.forEach((link) => {
    const selected = link.getAttribute("href") === `#${sectionId}`;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function showAdminSection(sectionId, scrollToTop = false) {
  const activeSection = adminSections.find((section) => section.id === sectionId) || adminSections[0];
  if (!activeSection) return null;
  adminSections.forEach((section) => {
    section.hidden = section !== activeSection;
  });
  setActiveNavigation(activeSection.id);
  if (scrollToTop) window.scrollTo({ top: 0, behavior: "auto" });
  return activeSection.id;
}

function navigateToAdminSection(sectionId) {
  const nextHash = `#${sectionId}`;
  if (window.location.hash !== nextHash) window.history.pushState(null, "", nextHash);
  const activeSection = showAdminSection(sectionId, true);
  if (activeSection === "availability") loadAvailability();
}

adminNavLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    navigateToAdminSection(link.getAttribute("href").slice(1));
  });
});
dashboardHomeLink.addEventListener("click", (event) => {
  event.preventDefault();
  navigateToAdminSection("overview");
});
window.addEventListener("popstate", () => {
  const activeSection = showAdminSection(window.location.hash.slice(1), true);
  if (activeSection === "availability") loadAvailability();
});

async function loadOverview() {
  try {
    const overview = await api("/api/admin/overview");
    document.querySelector("#stat-today").textContent = overview.bookings_today;
    document.querySelector("#stat-upcoming").textContent = overview.upcoming_bookings;
    document.querySelector("#stat-confirmed").textContent = overview.confirmed_bookings;
    document.querySelector("#stat-value").textContent = currency.format(overview.estimated_value);
    document.querySelector("#stat-collected").textContent = currency.format(overview.collected_value);
    document.querySelector("#stat-outstanding").textContent = currency.format(overview.outstanding_value);
    document.querySelector("#stat-refunds").textContent = currency.format(overview.refund_due_value);
  } catch (error) {
    handleDashboardError(error);
  }
}

function notifiedAlertIds() {
  try {
    return new Set(JSON.parse(localStorage.getItem("ynf_notified_alerts") || "[]"));
  } catch {
    return new Set();
  }
}

function rememberNotifiedAlert(id) {
  const ids = notifiedAlertIds();
  ids.add(id);
  try {
    localStorage.setItem("ynf_notified_alerts", JSON.stringify([...ids].slice(-100)));
  } catch {
    // In-dashboard alerts still work when browser storage is unavailable.
  }
}

function updateDesktopAlertsButton() {
  if (!("Notification" in window)) {
    desktopAlertsButton.textContent = "Desktop alerts unavailable";
    desktopAlertsButton.disabled = true;
    return;
  }
  if (Notification.permission === "granted") {
    desktopAlertsButton.textContent = "Desktop alerts on";
    desktopAlertsButton.disabled = true;
  } else if (Notification.permission === "denied") {
    desktopAlertsButton.textContent = "Desktop alerts blocked";
    desktopAlertsButton.disabled = true;
  } else {
    desktopAlertsButton.textContent = "Enable desktop alerts";
    desktopAlertsButton.disabled = false;
  }
}

function sendDesktopAlerts(alerts) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const notified = notifiedAlertIds();
  alerts.forEach((alert) => {
    if (notified.has(alert.id)) return;
    new Notification(alert.title, {
      body: `${alert.message} · ${alert.reference}`,
      tag: alert.id,
    });
    rememberNotifiedAlert(alert.id);
  });
}

function alertCard(alert) {
  const kindClass = alert.kind.replaceAll("_", "-");
  const label = alert.kind === "new_booking"
    ? "New booking"
    : alert.kind === "payment_issue"
      ? "Payment issue"
      : alert.kind === "starts_soon" ? "Starting soon" : "Session ending";
  const seenButton = alert.notification_id && !alert.is_read
    ? `<button type="button" data-read-alert="${alert.notification_id}">Mark seen</button>`
    : "";
  const readClass = alert.is_read ? " is-read" : "";
  return `<article class="alert-card ${safeAttr(kindClass)}${readClass}">
    <div class="alert-card-kicker"><b>${safe(label)}</b><span>${safe(alert.reference)}</span></div>
    <h3>${safe(alert.title)}</h3>
    <p>${safe(alert.message)}</p>
    <footer><small>${safe(formatDate(alert.booking_date))} · ${safe(displayTime(alert.start_time))} to ${safe(displayTime(alert.end_time))}</small><div class="alert-card-controls"><button type="button" data-view-alert-booking="${alert.booking_id}" data-alert-space="${safeAttr(alert.space_id)}" data-notification-id="${alert.notification_id || ""}">View</button>${seenButton}</div></footer>
  </article>`;
}

function filteredAlerts() {
  const bookings = alertFilter === "unread"
    ? alertsPayload.new_bookings.filter((alert) => !alert.is_read)
    : alertsPayload.new_bookings;
  return [...alertsPayload.operational, ...bookings];
}

function renderAlertList() {
  const alerts = filteredAlerts();
  alertList.innerHTML = alerts.length
    ? alerts.map(alertCard).join("")
    : '<p class="alerts-clear">No notifications</p>';
}

function renderAlerts(payload) {
  alertsPayload = payload;
  renderAlertList();
  const activeAlerts = [...payload.operational, ...payload.new_bookings.filter((alert) => !alert.is_read)];
  const count = document.querySelector("#alert-count");
  count.textContent = activeAlerts.length;
  count.hidden = activeAlerts.length === 0;
  alertBell.classList.toggle("has-alerts", activeAlerts.length > 0);
  alertBell.setAttribute(
    "aria-label",
    activeAlerts.length ? `Open notifications, ${activeAlerts.length} unread` : "Open notifications",
  );
  document.querySelector("#read-all-alerts").hidden = payload.unread_count === 0;
  sendDesktopAlerts(activeAlerts);
}

async function loadAlerts() {
  try {
    renderAlerts(await api("/api/admin/alerts"));
  } catch (error) {
    if (error.status === 401) handleDashboardError(error);
    else alertList.innerHTML = `<p class="alerts-clear">Alerts could not be refreshed. ${safe(error.message)}</p>`;
  }
}

function startAlertPolling() {
  if (alertPollTimer) window.clearInterval(alertPollTimer);
  alertPollTimer = window.setInterval(loadAlerts, 30000);
}

function setAlertPanel(open) {
  alertCenter.hidden = !open;
  alertBell.setAttribute("aria-expanded", String(open));
}

function setAccountMenu(open) {
  accountMenuPanel.hidden = !open;
  accountMenuButton.setAttribute("aria-expanded", String(open));
}

async function loadBookings() {
  const query = bookingFilterQuery();
  document.querySelector("#booking-export").href = `/api/admin/bookings/export.csv?${query}`;
  const body = document.querySelector("#bookings-body");
  body.innerHTML = '<tr><td colspan="8" class="empty">Loading bookings…</td></tr>';
  try {
    const bookings = await api(`/api/admin/bookings?${query}`);
    adminBookings = bookings;
    body.innerHTML = bookings.length ? bookings.map(bookingRow).join("") : '<tr><td colspan="8" class="empty">No bookings match these filters.</td></tr>';
    document.querySelector("#booking-count").textContent = `${bookings.length} booking${bookings.length === 1 ? "" : "s"} shown`;
  } catch (error) {
    handleDashboardError(error);
  }
}

function bookingFilterQuery() {
  const formData = new FormData(bookingFilters);
  const query = new URLSearchParams();
  if (formData.get("space_id")) query.set("space_id", formData.get("space_id"));
  if (formData.get("q")) query.set("q", formData.get("q"));
  if (formData.get("status")) query.set("status", formData.get("status"));
  if (formData.get("date_from")) query.set("date_from", formData.get("date_from"));
  if (formData.get("date_to")) query.set("date_to", formData.get("date_to"));
  return query;
}

function bookingRow(booking) {
  const date = booking.booking_date ? formatDate(booking.booking_date) : "Not scheduled";
  const time = booking.start_time ? `${displayTime(booking.start_time)} to ${displayTime(booking.end_time)}` : "Not available";
  const action = ["confirmed", "cancelled"].includes(booking.status)
    ? `<button type="button" class="manage-booking" data-booking-id="${booking.id}">Manage</button>`
    : "Not available";
  return `<tr>
    <td><b>${safe(booking.reference)}</b><small>${safe(booking.payment_mode?.replaceAll("_", " ") || "No payment mode")}</small></td>
    <td><b>${safe(booking.customer_name || "Incomplete booking")}</b><small>${safe(booking.customer_email || booking.phone_number)}</small></td>
    <td>${safe(booking.space_name)}</td>
    <td>${safe(date)}<small>${safe(time)}</small></td>
    <td>${safe(currency.format(booking.total_amount))}</td>
    <td><span class="status status-${safe(booking.payment_status)}">${safe(booking.payment_status.replaceAll("_", " "))}</span></td>
    <td><span class="status status-${safe(booking.status)}">${safe(booking.status.replaceAll("_", " "))}</span></td>
    <td>${action}</td>
  </tr>`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}

function displayTime(value) {
  if (!value) return "Not available";
  const [hours, minutes] = value.split(":").map(Number);
  return `${hours % 12 || 12}:${String(minutes).padStart(2, "0")} ${hours >= 12 ? "PM" : "AM"}`;
}

function halfHourOptions(selected = "", startIndex = 0, endIndex = 48) {
  return Array.from({ length: endIndex - startIndex }, (_, offset) => {
    const minutes = (startIndex + offset) * 30;
    const value = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    return `<option value="${value}"${value === selected ? " selected" : ""}>${displayTime(value)}</option>`;
  }).join("");
}

function durationOptions(selected = 2) {
  return Array.from({ length: 21 }, (_, index) => {
    const value = 2 + (index / 2);
    return `<option value="${value}"${value === Number(selected) ? " selected" : ""}>${value} hour${value === 1 ? "" : "s"}</option>`;
  }).join("");
}

function studioById(spaceId) {
  return studioSettings.find((studio) => studio.id === spaceId);
}

function syncStudioSelects() {
  const selects = [
    bookingFilters.elements.space_id,
    availabilityFilters.elements.space_id,
    bookingEditForm.elements.space_id,
  ];
  selects.forEach((select) => {
    const previous = select.value;
    select.innerHTML = studioSettings.map((studio) =>
      `<option value="${safeAttr(studio.id)}">${safe(studio.name)}${studio.is_active ? "" : " (inactive)"}</option>`
    ).join("");
    if (studioSettings.some((studio) => studio.id === previous)) select.value = previous;
  });
  setupHalfHourBlockOptions();
  setupBookingEditOptions();
}

async function loadStudioSettings() {
  const root = document.querySelector("#studio-settings-list");
  root.innerHTML = '<p class="settings-empty">Loading studio settings…</p>';
  try {
    studioSettings = await api("/api/admin/studios");
    renderStudioSettings();
    syncStudioSelects();
  } catch (error) {
    root.innerHTML = `<p class="settings-empty">${safe(error.message)}</p>`;
    handleDashboardError(error);
  }
}

function renderStudioSettings() {
  const root = document.querySelector("#studio-settings-list");
  root.innerHTML = studioSettings.map((studio) => `
    <form class="studio-settings-form" data-studio-id="${safeAttr(studio.id)}">
      <div class="studio-settings-head">
        <div><p>${safe(studio.id.replaceAll("_", " "))}</p><h3>${safe(studio.name)}</h3><small>Public URL: /studios/${safe(studio.slug)}</small></div>
        <label class="studio-active"><input name="is_active" type="checkbox" ${studio.is_active ? "checked" : ""}> Accept new bookings</label>
      </div>
      <div class="studio-settings-fields">
        <label class="span-2"><span>Studio name</span><input name="name" value="${safeAttr(studio.name)}" minlength="2" maxlength="120" required></label>
        <label><span>Hourly rate (₹)</span><input name="hourly_rate" type="number" value="${studio.hourly_rate}" min="0" max="1000000" step="1" required></label>
        <label><span>Capacity</span><input name="capacity" type="number" value="${studio.capacity}" min="1" max="500" required></label>
        <label class="span-2"><span>Short description</span><textarea name="short_description" minlength="10" maxlength="300" required>${safe(studio.short_description)}</textarea></label>
        <label class="span-2"><span>Dimensions / capacity note</span><input name="dimensions" value="${safeAttr(studio.dimensions)}" minlength="2" maxlength="180" required></label>
        <label class="full"><span>Brochure / details</span><textarea name="brochure" minlength="10" maxlength="3000" required>${safe(studio.brochure)}</textarea></label>
        <label class="full"><span>Studio rules</span><textarea name="rules" minlength="10" maxlength="3000" required>${safe(studio.rules)}</textarea></label>
        <label class="span-2"><span>Equipment: one item per line</span><textarea name="equipment" maxlength="6050">${safe(studio.equipment.join("\n"))}</textarea></label>
        <label class="span-2"><span>Amenities: one item per line</span><textarea name="amenities" maxlength="6050">${safe(studio.amenities.join("\n"))}</textarea></label>
        <label class="full"><span>Purpose options: one dropdown option per line</span><textarea name="booking_purposes" maxlength="6050" required>${safe(studio.booking_purposes.join("\n"))}</textarea></label>
        <label class="full"><span>Cover image URL</span><input name="cover_image" type="url" value="${safeAttr(studio.cover_image)}" maxlength="1000" required></label>
        <label><span>Opening time</span><select name="opening_time" required>${halfHourOptions(studio.opening_time, 0, 47)}</select></label>
        <label><span>Closing time</span><select name="closing_time" required>${halfHourOptions(studio.closing_time, 1, 48)}</select></label>
        <label><span>Minimum duration</span><select name="min_duration_hours" required>${durationOptions(studio.min_duration_hours)}</select></label>
        <label><span>Maximum duration</span><select name="max_duration_hours" required>${durationOptions(studio.max_duration_hours)}</select></label>
      </div>
        <div class="studio-settings-actions"><button type="submit">Save studio settings</button></div>
    </form>
  `).join("");
}

function hideDashboardMessage(message) {
  const timer = dashboardMessageTimers.get(message);
  if (timer) window.clearTimeout(timer);
  dashboardMessageTimers.delete(message);
  message.hidden = true;
  message.replaceChildren();
}

function showDashboardMessage(target, text, { autoHide = true, kind = "success" } = {}) {
  const message = typeof target === "string" ? document.querySelector(target) : target;
  const previousTimer = dashboardMessageTimers.get(message);
  if (previousTimer) window.clearTimeout(previousTimer);

  const copy = document.createElement("span");
  copy.textContent = text;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "dashboard-message-close";
  close.setAttribute("aria-label", "Dismiss message");
  close.textContent = "×";
  close.addEventListener("click", () => hideDashboardMessage(message));

  message.replaceChildren(copy, close);
  message.classList.toggle("is-success", kind === "success");
  message.classList.toggle("is-error", kind === "error");
  message.setAttribute("role", kind === "error" ? "alert" : "status");
  message.hidden = false;

  if (autoHide) {
    dashboardMessageTimers.set(
      message,
      window.setTimeout(() => hideDashboardMessage(message), 10000),
    );
  }
}

function handleDashboardError(error) {
  if (error.status === 401) {
    showLogin("Your session has expired. Please sign in again.");
    return;
  }
  showDashboardMessage("#dashboard-message", error.message, { autoHide: false, kind: "error" });
}

function localDate(addDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + addDays);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function setupHalfHourBlockOptions() {
  if (!studioSettings.length) return;
  const startSelect = availabilityBlockForm.elements.start_time;
  const studio = studioById(availabilityFilters.elements.space_id.value) || studioSettings[0];
  const openingIndex = timeToMinutes(studio.opening_time) / 30;
  const closingIndex = timeToMinutes(studio.closing_time) / 30;
  const previous = startSelect.value;
  startSelect.innerHTML = halfHourOptions(previous, openingIndex, Math.max(openingIndex, closingIndex - 3));
  syncBlockDurationOptions();
}

function syncBlockDurationOptions() {
  const studio = studioById(availabilityFilters.elements.space_id.value) || studioSettings[0];
  if (!studio) return;
  const startValue = availabilityBlockForm.elements.start_time.value || studio.opening_time;
  const durationSelect = availabilityBlockForm.elements.duration_hours;
  const previousDuration = Number(durationSelect.value || 2);
  const remainingHalfHours = (timeToMinutes(studio.closing_time) - timeToMinutes(startValue)) / 30;
  const maximumDuration = Math.min(MAX_BLOCK_DURATION_HOURS, remainingHalfHours / 2);
  const optionCount = Math.max(0, Math.floor((maximumDuration - 2) * 2) + 1);
  durationSelect.innerHTML = Array.from({ length: optionCount }, (_, index) => {
    const duration = 2 + (index / 2);
    return `<option value="${duration}">${duration} hour${duration === 1 ? "" : "s"}</option>`;
  }).join("");
  durationSelect.value = String(Math.max(2, Math.min(previousDuration, maximumDuration)));
}

function setupBookingEditOptions() {
  if (!studioSettings.length) return;
  const startSelect = bookingEditForm.elements.start_time;
  const studio = studioById(bookingEditForm.elements.space_id.value) || studioSettings[0];
  const openingIndex = timeToMinutes(studio.opening_time) / 30;
  const closingIndex = timeToMinutes(studio.closing_time) / 30;
  const previous = startSelect.value;
  startSelect.innerHTML = halfHourOptions(previous, openingIndex, closingIndex);
  syncBookingDurationOptions();
}

function syncBookingDurationOptions() {
  const studio = studioById(bookingEditForm.elements.space_id.value) || studioSettings[0];
  if (!studio) return;
  const startValue = bookingEditForm.elements.start_time.value || studio.opening_time;
  const durationSelect = bookingEditForm.elements.duration_hours;
  const previousDuration = Number(durationSelect.value || studio.min_duration_hours);
  const remainingHours = (timeToMinutes(studio.closing_time) - timeToMinutes(startValue)) / 60;
  const maximum = Math.min(studio.max_duration_hours, remainingHours);
  const optionCount = Math.max(0, Math.floor((maximum - studio.min_duration_hours) * 2) + 1);
  durationSelect.innerHTML = Array.from({ length: optionCount }, (_, index) => {
    const duration = studio.min_duration_hours + (index / 2);
    return `<option value="${duration}">${duration} hour${duration === 1 ? "" : "s"}</option>`;
  }).join("");
  durationSelect.value = String(Math.max(studio.min_duration_hours, Math.min(previousDuration, maximum)));
}

function timeToMinutes(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return (hours * 60) + minutes;
}

function openBookingModal(bookingId) {
  const booking = adminBookings.find((item) => item.id === Number(bookingId));
  if (!booking) return;
  bookingEditForm.reset();
  bookingEditForm.elements.booking_id.value = booking.id;
  bookingEditForm.elements.space_id.value = booking.space_id;
  bookingEditForm.elements.booking_date.value = booking.booking_date;
  setupBookingEditOptions();
  bookingEditForm.elements.start_time.value = booking.start_time;
  syncBookingDurationOptions();
  bookingEditForm.elements.duration_hours.value = String(booking.duration_hours);
  bookingEditForm.elements.customer_name.value = booking.customer_name || "";
  bookingEditForm.elements.customer_email.value = booking.customer_email || "";
  bookingEditForm.elements.phone_number.value = booking.phone_number || "";
  bookingEditForm.elements.purpose.value = booking.purpose || "";
  const editable = booking.status === "confirmed";
  bookingEditForm.querySelectorAll(".edit-grid input,.edit-grid select,.edit-grid textarea")
    .forEach((field) => { field.disabled = !editable; });
  document.querySelector("#save-booking-button").hidden = !editable;
  document.querySelector("#cancel-booking-button").hidden = !editable;
  document.querySelector("#booking-payment-status").textContent = booking.payment_status.replaceAll("_", " ");
  document.querySelector("#booking-payment-summary").textContent =
    `${booking.payment_mode?.replaceAll("_", " ") || "No mode"} · ${currency.format(booking.total_amount)}`;
  document.querySelector("#payment-reference").value = booking.payment_reference || "";
  const paymentAction = document.querySelector("#payment-action-button");
  if (booking.payment_status === "pending" && ["payment_pending", "confirmed"].includes(booking.status)) {
    paymentAction.hidden = false;
    paymentAction.dataset.status = "paid";
    paymentAction.textContent = "Mark paid";
  } else if (booking.payment_status === "refund_due") {
    paymentAction.hidden = false;
    paymentAction.dataset.status = "refunded";
    paymentAction.textContent = "Mark refunded";
  } else {
    paymentAction.hidden = true;
    delete paymentAction.dataset.status;
  }
  document.querySelector("#booking-modal-reference").textContent = booking.reference;
  document.querySelector("#booking-edit-message").hidden = true;
  bookingModal.hidden = false;
}

async function loadAvailability() {
  const data = new FormData(availabilityFilters);
  const spaceId = data.get("space_id");
  const bookingDate = data.get("booking_date");
  const requestToken = ++availabilityRequestToken;
  availabilityRequestController?.abort();
  const controller = new AbortController();
  availabilityRequestController = controller;
  const query = new URLSearchParams({
    space_id: spaceId,
    booking_date: bookingDate,
  });
  const slots = document.querySelector("#availability-slots");
  slots.innerHTML = '<p class="availability-empty">Loading schedule…</p>';
  slots.setAttribute("aria-busy", "true");
  try {
    const day = await api(`/api/admin/availability?${query}`, { signal: controller.signal });
    if (
      requestToken !== availabilityRequestToken
      || availabilityFilters.elements.space_id.value !== spaceId
      || availabilityFilters.elements.booking_date.value !== bookingDate
    ) return;
    document.querySelector("#schedule-space").textContent = day.space_name;
    document.querySelector("#schedule-date").textContent = formatDate(day.booking_date);
    slots.innerHTML = day.slots.map(availabilitySlot).join("");
  } catch (error) {
    if (error.name === "AbortError" || requestToken !== availabilityRequestToken) return;
    slots.innerHTML = `<p class="availability-empty">${safe(error.message)}</p>`;
    if (error.status === 401) handleDashboardError(error);
  } finally {
    if (requestToken === availabilityRequestToken) {
      slots.removeAttribute("aria-busy");
      availabilityRequestController = null;
    }
  }
}

function availabilitySlot(slot) {
  let detail = "Open for booking";
  let action = `data-block-start="${safeAttr(slot.start_time)}"`;
  let disabled = "";
  if (slot.status === "booked") detail = `${slot.booking_reference} · ${slot.customer_name || "Confirmed booking"}`;
  if (slot.status === "blocked") {
    detail = slot.reason || "Owner blocked";
    action = `data-unblock="${slot.block_id}"`;
  }
  if (slot.status === "booked") {
    action = "";
    disabled = "disabled";
  }
  if (slot.status === "past" || slot.status === "unavailable") {
    detail = slot.status === "past" ? "Past time" : "Calendar unavailable";
    action = "";
    disabled = "disabled";
  }
  const actionLabel = slot.status === "available" ? "Click to block" : detail;
  const slotLabel = `${displayTime(slot.start_time)} - ${displayTime(slot.end_time)}`;
  const title = `${slotLabel} · ${detail}`;
  return `<button type="button" class="admin-slot-button ${safeAttr(slot.status)}" ${action} ${disabled} title="${safeAttr(title)}">
    <span>${safe(slotLabel)}</span>
    <small>${safe(slot.status.replaceAll("_", " "))}</small>
    <em>${safe(actionLabel)}</em>
  </button>`;
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#login-button");
  const data = new FormData(loginForm);
  button.disabled = true;
  button.firstChild.textContent = "Signing in… ";
  try {
    const session = await api("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
    });
    loginForm.reset();
    await showDashboard(session.username);
  } catch (error) {
    showLogin(error.message);
  } finally {
    button.disabled = false;
    button.firstChild.textContent = "Sign in ";
  }
});

setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#setup-button");
  const data = new FormData(setupForm);
  if (data.get("password") !== data.get("confirm_password")) {
    showSetup("The password confirmation does not match.");
    return;
  }
  button.disabled = true;
  button.firstChild.textContent = "Creating account… ";
  try {
    const session = await api("/api/admin/setup", {
      method: "POST",
      body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
    });
    setupForm.reset();
    await showDashboard(session.username);
  } catch (error) {
    showSetup(error.message);
  } finally {
    button.disabled = false;
    button.firstChild.textContent = "Create owner account ";
  }
});

bookingFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  loadBookings();
});
alertBell.addEventListener("click", () => {
  setAlertPanel(alertCenter.hidden);
});
accountMenuButton.addEventListener("click", () => {
  setAccountMenu(accountMenuPanel.hidden);
});
document.querySelectorAll("[data-alert-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    alertFilter = button.dataset.alertFilter;
    document.querySelectorAll("[data-alert-filter]").forEach((tab) => {
      const selected = tab === button;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
    });
    renderAlertList();
  });
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".alert-menu")) setAlertPanel(false);
  if (!event.target.closest(".account-menu")) setAccountMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setAlertPanel(false);
    setAccountMenu(false);
  }
});
desktopAlertsButton.addEventListener("click", async () => {
  if (!("Notification" in window)) return;
  await Notification.requestPermission();
  updateDesktopAlertsButton();
  await loadAlerts();
});
document.querySelector("#read-all-alerts").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api("/api/admin/alerts/read-all", { method: "POST" });
    await loadAlerts();
  } catch (error) {
    handleDashboardError(error);
  } finally {
    button.disabled = false;
  }
});
alertList.addEventListener("click", async (event) => {
  const readButton = event.target.closest("[data-read-alert]");
  if (readButton) {
    readButton.disabled = true;
    try {
      await api(`/api/admin/alerts/${readButton.dataset.readAlert}/read`, { method: "POST" });
      await loadAlerts();
    } catch (error) {
      handleDashboardError(error);
      readButton.disabled = false;
    }
    return;
  }

  const viewButton = event.target.closest("[data-view-alert-booking]");
  if (!viewButton) return;
  viewButton.disabled = true;
  try {
    if (viewButton.dataset.notificationId) {
      await api(`/api/admin/alerts/${viewButton.dataset.notificationId}/read`, { method: "POST" });
    }
    bookingFilters.reset();
    bookingFilters.elements.space_id.value = viewButton.dataset.alertSpace;
    await loadBookings();
    setAlertPanel(false);
    navigateToAdminSection("bookings");
    openBookingModal(viewButton.dataset.viewAlertBooking);
    await loadAlerts();
  } catch (error) {
    handleDashboardError(error);
    viewButton.disabled = false;
  }
});
document.querySelector("#bookings-body").addEventListener("click", (event) => {
  const button = event.target.closest("[data-booking-id]");
  if (button) openBookingModal(button.dataset.bookingId);
});
document.querySelector(".booking-modal-close").addEventListener("click", () => { bookingModal.hidden = true; });
bookingModal.addEventListener("click", (event) => {
  if (event.target === bookingModal) bookingModal.hidden = true;
});
bookingEditForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(bookingEditForm);
  const bookingId = data.get("booking_id");
  const button = document.querySelector("#save-booking-button");
  const message = document.querySelector("#booking-edit-message");
  button.disabled = true;
  try {
    const booking = await api(`/api/admin/bookings/${bookingId}`, {
      method: "PATCH",
      body: JSON.stringify({
        space_id: data.get("space_id"),
        booking_date: data.get("booking_date"),
        start_time: data.get("start_time"),
        duration_hours: Number(data.get("duration_hours")),
        customer_name: data.get("customer_name"),
        customer_email: data.get("customer_email"),
        phone_number: data.get("phone_number"),
        purpose: data.get("purpose"),
      }),
    });
    bookingModal.hidden = true;
    showDashboardMessage("#dashboard-message", `${booking.reference} updated successfully.`);
    await Promise.all([loadOverview(), loadBookings(), loadAvailability()]);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
});
document.querySelector("#cancel-booking-button").addEventListener("click", async () => {
  const bookingId = bookingEditForm.elements.booking_id.value;
  const reference = document.querySelector("#booking-modal-reference").textContent;
  if (!window.confirm(`Cancel ${reference}? The studio time will become available again.`)) return;
  const button = document.querySelector("#cancel-booking-button");
  const message = document.querySelector("#booking-edit-message");
  button.disabled = true;
  try {
    const booking = await api(`/api/admin/bookings/${bookingId}/cancel`, { method: "POST" });
    bookingModal.hidden = true;
    const confirmation = booking.payment_status === "refund_due"
      ? `${booking.reference} cancelled. Its time is available and a refund is now due.`
      : `${booking.reference} cancelled. Its time is available again.`;
    showDashboardMessage("#dashboard-message", confirmation);
    await Promise.all([loadOverview(), loadBookings(), loadAvailability()]);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
});
document.querySelector("#payment-action-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const status = button.dataset.status;
  if (!status) return;
  const bookingId = bookingEditForm.elements.booking_id.value;
  const reference = document.querySelector("#payment-reference").value;
  button.disabled = true;
  try {
    const booking = await api(`/api/admin/bookings/${bookingId}/payment`, {
      method: "POST",
      body: JSON.stringify({ status, provider_reference: reference || null }),
    });
    bookingModal.hidden = true;
    showDashboardMessage(
      "#dashboard-message",
      `${booking.reference} payment marked ${booking.payment_status.replaceAll("_", " ")}.`,
    );
    await Promise.all([loadOverview(), loadBookings()]);
  } catch (error) {
    const message = document.querySelector("#booking-edit-message");
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
});
availabilityFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  loadAvailability();
});
availabilityFilters.querySelector('select[name="space_id"]').addEventListener("change", () => {
  setupHalfHourBlockOptions();
  loadAvailability();
});
availabilityFilters.querySelector('input[name="booking_date"]').addEventListener("change", loadAvailability);
availabilityBlockForm.elements.start_time.addEventListener("change", syncBlockDurationOptions);
bookingEditForm.elements.space_id.addEventListener("change", setupBookingEditOptions);
bookingEditForm.elements.start_time.addEventListener("change", syncBookingDurationOptions);
availabilityBlockForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const filters = new FormData(availabilityFilters);
  const block = new FormData(availabilityBlockForm);
  const button = document.querySelector("#block-time-button");
  button.disabled = true;
  try {
    await api("/api/admin/availability/blocks", {
      method: "POST",
      body: JSON.stringify({
        space_id: filters.get("space_id"),
        booking_date: filters.get("booking_date"),
        start_time: block.get("start_time"),
        duration_hours: Number(block.get("duration_hours")),
        reason: block.get("reason") || "Owner blocked",
      }),
    });
    showDashboardMessage(
      "#availability-message",
      "Studio time blocked. Customer availability has been updated.",
    );
    availabilityBlockForm.querySelector('input[name="reason"]').value = "";
    await loadAvailability();
  } catch (error) {
    showDashboardMessage("#availability-message", error.message, { autoHide: false, kind: "error" });
  } finally {
    button.disabled = false;
  }
});
document.querySelector("#availability-slots").addEventListener("click", async (event) => {
  const blockButton = event.target.closest("[data-block-start]");
  if (blockButton) {
    availabilityBlockForm.elements.start_time.value = blockButton.dataset.blockStart;
    syncBlockDurationOptions();
    availabilityBlockForm.querySelector('input[name="reason"]').focus();
    return;
  }
  const unblockButton = event.target.closest("[data-unblock]");
  if (!unblockButton) return;
  unblockButton.disabled = true;
  try {
    await api(`/api/admin/availability/blocks/${unblockButton.dataset.unblock}`, { method: "DELETE" });
    showDashboardMessage("#availability-message", "Studio time reopened for customer bookings.");
    await loadAvailability();
  } catch (error) {
    showDashboardMessage("#availability-message", error.message, { autoHide: false, kind: "error" });
    unblockButton.disabled = false;
  }
});
bookingFilters.elements.space_id.addEventListener("change", loadBookings);
bookingFilters.elements.status.addEventListener("change", loadBookings);
bookingFilters.querySelectorAll('input[type="date"]').forEach((input) => {
  input.addEventListener("change", loadBookings);
});
document.querySelector("#studio-settings-list").addEventListener("submit", async (event) => {
  const form = event.target.closest(".studio-settings-form");
  if (!form) return;
  event.preventDefault();
  const data = new FormData(form);
  const button = form.querySelector('button[type="submit"]');
  const message = document.querySelector("#studio-settings-message");
  const listItems = (name) => String(data.get(name) || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  button.disabled = true;
  try {
    const studio = await api(`/api/admin/studios/${encodeURIComponent(form.dataset.studioId)}`, {
      method: "PUT",
      body: JSON.stringify({
        name: data.get("name"),
        short_description: data.get("short_description"),
        brochure: data.get("brochure"),
        rules: data.get("rules"),
        hourly_rate: Number(data.get("hourly_rate")),
        capacity: Number(data.get("capacity")),
        dimensions: data.get("dimensions"),
        equipment: listItems("equipment"),
        amenities: listItems("amenities"),
        booking_purposes: listItems("booking_purposes"),
        cover_image: data.get("cover_image"),
        opening_time: data.get("opening_time"),
        closing_time: data.get("closing_time"),
        min_duration_hours: Number(data.get("min_duration_hours")),
        max_duration_hours: Number(data.get("max_duration_hours")),
        is_active: data.get("is_active") === "on",
      }),
    });
    showDashboardMessage(
      message,
      `${studio.name} settings saved. Public booking availability has been updated.`,
    );
    window.YNFStudioCache?.clear();
    await loadStudioSettings();
    await Promise.all([loadOverview(), loadBookings(), loadAvailability()]);
  } catch (error) {
    showDashboardMessage(message, error.message, { autoHide: false, kind: "error" });
    if (error.status === 401) handleDashboardError(error);
  } finally {
    button.disabled = false;
  }
});
document.querySelector("#logout-button").addEventListener("click", async () => {
  await api("/api/admin/logout", { method: "POST" }).catch(() => {});
  showLogin();
});
document.querySelector("#change-password-button").addEventListener("click", () => {
  setAccountMenu(false);
  document.querySelector("#change-password-form").reset();
  document.querySelector("#password-message").hidden = true;
  passwordModal.hidden = false;
});
document.querySelector(".password-modal-close").addEventListener("click", () => { passwordModal.hidden = true; });
passwordModal.addEventListener("click", (event) => {
  if (event.target === passwordModal) passwordModal.hidden = true;
});
document.querySelector("#change-password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const message = document.querySelector("#password-message");
  if (data.get("new_password") !== data.get("confirm_password")) {
    message.textContent = "The new password confirmation does not match.";
    message.hidden = false;
    return;
  }
  const button = document.querySelector("#save-password-button");
  button.disabled = true;
  try {
    await api("/api/admin/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: data.get("current_password"), new_password: data.get("new_password") }),
    });
    passwordModal.hidden = true;
    showDashboardMessage(
      "#dashboard-message",
      "Password updated. Other signed-in sessions have been invalidated.",
    );
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
});

function updateCurrentDateTime() {
  document.querySelector("#current-date").textContent = new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  }).format(new Date());
}

updateCurrentDateTime();
window.setInterval(updateCurrentDateTime, 1000);
availabilityFilters.elements.booking_date.min = localDate();
availabilityFilters.elements.booking_date.value = localDate(1);
bookingEditForm.elements.booking_date.min = localDate();
setupHalfHourBlockOptions();
setupBookingEditOptions();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !dashboardView.hidden) loadAlerts();
});

api("/api/admin/session")
  .then((session) => session.authenticated ? showDashboard(session.username) : session.setup_required ? showSetup() : showLogin())
  .catch(() => showLogin("Unable to check the dashboard session."));
