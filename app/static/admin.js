const loginView = document.querySelector("#login-view");
const dashboardView = document.querySelector("#dashboard-view");
const loginForm = document.querySelector("#admin-login-form");
const setupForm = document.querySelector("#admin-setup-form");
const passwordModal = document.querySelector("#password-modal");
const availabilityBookingModal = document.querySelector("#availability-booking-modal");
const bookingModal = document.querySelector("#booking-modal");
const bookingEditForm = document.querySelector("#booking-edit-form");
const offlineBookingModal = document.querySelector("#offline-booking-modal");
const offlineBookingForm = document.querySelector("#offline-booking-form");
const bookingFilters = document.querySelector("#booking-filters");
const bookingColumnsButton = document.querySelector("#booking-columns-button");
const bookingColumnsPanel = document.querySelector("#booking-columns-panel");
const availabilityFilters = document.querySelector("#availability-filters");
const availabilityBlockForm = document.querySelector("#availability-block-form");
const slotContextMenu = document.querySelector("#slot-context-menu");
const unblockSlotAction = document.querySelector("#unblock-slot-action");
const alertCenter = document.querySelector("#alert-center");
const alertBell = document.querySelector("#alert-bell");
const alertList = document.querySelector("#alert-list");
const desktopAlertsButton = document.querySelector("#desktop-alerts-button");
const accountMenuButton = document.querySelector("#account-menu-button");
const accountMenuPanel = document.querySelector("#account-menu-panel");
const dashboardHomeLink = document.querySelector("#dashboard-home-link");
const overviewMenuToggle = document.querySelector("#overview-menu-toggle");
const overviewSubmenu = document.querySelector("#overview-submenu");
const settingsMenuToggle = document.querySelector("#settings-menu-toggle");
const settingsSubmenu = document.querySelector("#settings-submenu");
const fundsOverviewFilters = document.querySelector("#funds-overview-filters");
const bookingsOverviewFilters = document.querySelector("#bookings-overview-filters");
const unavailabilityOverviewFilters = document.querySelector("#unavailability-overview-filters");
const staffUserForm = document.querySelector("#staff-user-form");
const staffUsersList = document.querySelector("#staff-users-list");
let adminBookings = [];
let studioSettings = [];
let currentAdminRole = "staff";
let alertPollTimer = null;
let alertsPayload = { unread_count: 0, new_bookings: [], operational: [] };
let alertFilter = "all";
let availabilityRequestToken = 0;
let availabilityRequestController = null;
let currentAvailabilityDay = null;
let contextSlot = null;
let bookingEditAvailabilityRequestToken = 0;
let bookingEditAvailabilityRequestController = null;
let currentBookingEditDay = null;
const dashboardMessageTimers = new WeakMap();
const MAX_BLOCK_DURATION_HOURS = 12;
const BOOKING_COLUMN_STORAGE_KEY = "ynf_admin_booking_columns_v2";
const BOOKING_COLUMNS = ["schedule", "customer", "purpose", "payment", "status", "reference", "terms", "value", "actions"];
const DEFAULT_BOOKING_COLUMNS = ["schedule", "customer", "purpose", "payment", "status", "actions"];
const LOCKED_BOOKING_COLUMNS = new Set(["actions"]);
const PAYMENT_METHODS_BY_FLOW = {
  pay_at_studio: [
    ["cash", "Cash"], ["upi", "UPI"], ["card", "Card"],
    ["bank_transfer", "Bank transfer"], ["cheque", "Cheque"], ["other", "Other"],
  ],
  pay_now: [
    ["upi", "UPI"], ["card", "Card"], ["netbanking", "Net banking"],
    ["wallet", "Wallet"], ["bank_transfer", "Bank transfer"], ["other", "Other"],
  ],
};
let visibleBookingColumns = loadBookingColumnPreferences();
const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const adminNavLinks = Array.from(document.querySelectorAll(".admin-shell aside nav a[href^='#']"));
const adminSections = Array.from(document.querySelectorAll(".admin-shell > main > section[id]"));
const OVERVIEW_SUBSECTION_IDS = new Set(["funds", "overview-bookings", "unavailability"]);
const SETTINGS_SUBSECTION_IDS = new Set(["staff-access", "studio-catalogue"]);

function safe(value) {
  const element = document.createElement("span");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function safeAttr(value) {
  return safe(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function paymentFlowLabel(value) {
  return value === "pay_now" ? "Online" : "Pay at studio";
}

function readableLabel(value, fallback = "Not available") {
  if (!value) return fallback;
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function syncPaymentMethodSelect(paymentMode, methodSelect, selected = "") {
  const methods = PAYMENT_METHODS_BY_FLOW[paymentMode] || [];
  const selectedIsKnown = methods.some(([value]) => value === selected);
  methodSelect.innerHTML = [
    '<option value="">Not decided yet</option>',
    ...methods.map(([value, label]) => `<option value="${safeAttr(value)}">${safe(label)}</option>`),
    ...(selected && !selectedIsKnown
      ? [`<option value="${safeAttr(selected)}">${safe(selected.replaceAll("_", " "))}</option>`]
      : []),
  ].join("");
  methodSelect.value = selected;
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

function isOwner() {
  return currentAdminRole === "owner";
}

function applyRolePermissions() {
  document.querySelectorAll("[data-owner-only]").forEach((element) => {
    element.hidden = !isOwner();
  });
}

async function showDashboard(session) {
  loginView.hidden = true;
  currentAdminRole = session.role === "owner" ? "owner" : "staff";
  applyRolePermissions();
  const initialSection = showAdminSection(window.location.hash.slice(1));
  dashboardView.hidden = false;
  document.querySelector("#admin-username").textContent = session.username || "admin";
  setupOverviewFilters();
  await loadStudioSettings();
  const initialLoads = [
    loadFundsOverview(),
    loadBookingsOverview(),
    loadUnavailabilityOverview(),
    loadBookings(),
    loadAlerts(),
  ];
  if (isOwner()) initialLoads.push(loadStaffUsers());
  if (initialSection === "availability") initialLoads.push(loadAvailability());
  await Promise.all(initialLoads);
  startAlertPolling();
  updateDesktopAlertsButton();
}

function setActiveNavigation(sectionId) {
  const isOverviewSubsection = OVERVIEW_SUBSECTION_IDS.has(sectionId);
  const isSettingsSubsection = SETTINGS_SUBSECTION_IDS.has(sectionId);
  adminNavLinks.forEach((link) => {
    const linkSectionId = link.getAttribute("href").slice(1);
    const selected = linkSectionId === sectionId;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  overviewMenuToggle.classList.toggle("parent-active", isOverviewSubsection);
  overviewMenuToggle.setAttribute("aria-expanded", String(isOverviewSubsection));
  overviewSubmenu.hidden = !isOverviewSubsection;
  settingsMenuToggle.classList.toggle("parent-active", isSettingsSubsection);
  settingsMenuToggle.setAttribute("aria-expanded", String(isSettingsSubsection));
  settingsSubmenu.hidden = !isSettingsSubsection;
}

function showAdminSection(sectionId, scrollToTop = false) {
  const allowedSections = adminSections.filter((section) => isOwner() || !section.hasAttribute("data-owner-only"));
  const activeSection = allowedSections.find((section) => section.id === sectionId) || allowedSections[0];
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
function toggleSectionSubmenu(toggle, submenu) {
  const expanded = toggle.getAttribute("aria-expanded") === "true";
  toggle.setAttribute("aria-expanded", String(!expanded));
  submenu.hidden = expanded;
}

overviewMenuToggle.addEventListener("click", () => toggleSectionSubmenu(overviewMenuToggle, overviewSubmenu));
settingsMenuToggle.addEventListener("click", () => toggleSectionSubmenu(settingsMenuToggle, settingsSubmenu));
dashboardHomeLink.addEventListener("click", (event) => {
  event.preventDefault();
  navigateToAdminSection("funds");
});
window.addEventListener("popstate", () => {
  const activeSection = showAdminSection(window.location.hash.slice(1), true);
  if (activeSection === "availability") loadAvailability();
});
fundsOverviewFilters.elements.scope.addEventListener("change", syncFundsMonthPicker);
fundsOverviewFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  loadFundsOverview();
});
bookingsOverviewFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  loadBookingsOverview();
});
unavailabilityOverviewFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  loadUnavailabilityOverview();
});

function setupOverviewFilters() {
  const currentMonth = localDate().slice(0, 7);
  fundsOverviewFilters.elements.scope.value = "overall";
  fundsOverviewFilters.elements.month.value = currentMonth;
  bookingsOverviewFilters.elements.day_offset.value = "0";
  bookingsOverviewFilters.elements.month.value = currentMonth;
  unavailabilityOverviewFilters.elements.month.value = currentMonth;
  syncFundsMonthPicker();
}

function syncFundsMonthPicker() {
  const isMonth = fundsOverviewFilters.elements.scope.value === "month";
  fundsOverviewFilters.elements.month.disabled = !isMonth;
  fundsOverviewFilters.elements.month.required = isMonth;
  document.querySelector("#funds-month-field").classList.toggle("is-disabled", !isMonth);
}

function monthLabel(value) {
  return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" })
    .format(new Date(`${value}-01T12:00:00`));
}

function hoursLabel(value) {
  const hours = Number(value || 0);
  return `${hours.toLocaleString("en-IN", { maximumFractionDigits: 1 })} hour${hours === 1 ? "" : "s"}`;
}

function showOverviewError(selector, error) {
  const message = document.querySelector(selector);
  message.textContent = error.message;
  message.hidden = false;
  if (error.status === 401) handleDashboardError(error);
}

async function loadFundsOverview() {
  const message = document.querySelector("#funds-overview-message");
  message.hidden = true;
  const query = new URLSearchParams();
  if (fundsOverviewFilters.elements.scope.value === "month") {
    query.set("month", fundsOverviewFilters.elements.month.value);
  }
  try {
    const queryString = query.toString();
    const suffix = queryString ? `?${queryString}` : "";
    const overview = await api(`/api/admin/overview/funds${suffix}`);
    document.querySelector("#funds-estimated").textContent = currency.format(overview.estimated_amount);
    document.querySelector("#funds-collected").textContent = currency.format(overview.collected_amount);
    document.querySelector("#funds-outstanding").textContent = currency.format(overview.outstanding_amount);
  } catch (error) {
    showOverviewError("#funds-overview-message", error);
  }
}

function overviewBookingRow(booking) {
  return `<tr>
    <td><b>${safe(booking.space_name)}</b><small>${safe(booking.reference)}</small></td>
    <td>${safe(formatDate(booking.booking_date))}<small>${safe(displayTime(booking.start_time))} to ${safe(displayTime(booking.end_time))}</small></td>
    <td><b>${safe(booking.customer_name)}</b><small>${safe(booking.phone_number)}</small></td>
  </tr>`;
}

function renderUtilizationChart(items) {
  const chart = document.querySelector("#studio-utilisation-chart");
  if (!items.length) {
    chart.innerHTML = '<p class="analytics-empty">No studios are configured.</p>';
    return;
  }
  chart.innerHTML = items.map((item) => {
    const percent = Math.max(0, Math.min(100, Number(item.utilization_percent || 0)));
    return `<article class="analytics-bar">
      <div><b>${safe(item.space_name)}</b><span>${safe(`${item.utilization_percent}% · ${hoursLabel(item.booked_hours)} booked`)}</span></div>
      <div class="analytics-bar-track" role="img" aria-label="${safeAttr(`${item.space_name} utilization ${item.utilization_percent}%`)}"><i style="width:${percent}%"></i></div>
      <small>${safe(`${hoursLabel(item.booked_hours)} of ${hoursLabel(item.available_hours)}`)}</small>
    </article>`;
  }).join("");
}

async function loadBookingsOverview() {
  const message = document.querySelector("#bookings-overview-message");
  message.hidden = true;
  const query = new URLSearchParams({
    day_offset: bookingsOverviewFilters.elements.day_offset.value,
    month: bookingsOverviewFilters.elements.month.value,
  });
  try {
    const overview = await api(`/api/admin/overview/bookings?${query}`);
    const selectedDate = formatDate(overview.selected_date);
    document.querySelector("#overview-booking-count").textContent = overview.total_bookings;
    document.querySelector("#overview-booking-date").textContent = selectedDate;
    document.querySelector("#overview-bookings-table-title").textContent = selectedDate;
    document.querySelector("#utilisation-chart-title").textContent = monthLabel(overview.utilization_month);
    document.querySelector("#overview-bookings-body").innerHTML = overview.bookings.length
      ? overview.bookings.map(overviewBookingRow).join("")
      : '<tr><td colspan="3" class="empty">No confirmed bookings for this day.</td></tr>';
    renderUtilizationChart(overview.studio_utilization);
  } catch (error) {
    showOverviewError("#bookings-overview-message", error);
  }
}

function renderUnavailabilityChart(items) {
  const chart = document.querySelector("#unavailability-chart");
  if (!items.length) {
    chart.innerHTML = '<p class="analytics-empty">No blocked studio time for this month.</p>';
    return;
  }
  const maximum = Math.max(...items.map((item) => Number(item.blocked_hours || 0)), 1);
  chart.innerHTML = items.map((item) => {
    const width = Math.max(0, Math.min(100, Number(item.blocked_hours || 0) / maximum * 100));
    return `<article class="analytics-bar unavailability-bar">
      <div><b>${safe(item.reason)}</b><span>${safe(hoursLabel(item.blocked_hours))}</span></div>
      <div class="analytics-bar-track" role="img" aria-label="${safeAttr(`${item.reason}: ${hoursLabel(item.blocked_hours)}`)}"><i style="width:${width}%"></i></div>
    </article>`;
  }).join("");
}

async function loadUnavailabilityOverview() {
  const message = document.querySelector("#unavailability-overview-message");
  message.hidden = true;
  const month = unavailabilityOverviewFilters.elements.month.value;
  try {
    const overview = await api(`/api/admin/overview/unavailability?${new URLSearchParams({ month })}`);
    const selectedMonth = monthLabel(overview.month);
    document.querySelector("#unavailability-total").textContent = hoursLabel(overview.total_blocked_hours);
    document.querySelector("#unavailability-month").textContent = selectedMonth;
    document.querySelector("#unavailability-chart-title").textContent = selectedMonth;
    renderUnavailabilityChart(overview.reasons);
  } catch (error) {
    showOverviewError("#unavailability-overview-message", error);
  }
}

function loadDashboardAnalytics() {
  return Promise.all([
    loadFundsOverview(),
    loadBookingsOverview(),
    loadUnavailabilityOverview(),
  ]);
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

function loadBookingColumnPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(BOOKING_COLUMN_STORAGE_KEY) || "null");
    if (Array.isArray(saved)) {
      const visible = new Set(
        saved.filter((column) => BOOKING_COLUMNS.includes(column) && column !== "actions"),
      );
      visible.add("actions");
      return visible;
    }
  } catch (error) {
    // Storage can be unavailable in private browsing; use the default layout in that case.
  }
  return new Set(DEFAULT_BOOKING_COLUMNS);
}

function saveBookingColumnPreferences() {
  try {
    localStorage.setItem(BOOKING_COLUMN_STORAGE_KEY, JSON.stringify([...visibleBookingColumns]));
  } catch (error) {
    // The selected layout still applies for the current page when storage is unavailable.
  }
}

function visibleBookingColumnCount() {
  return BOOKING_COLUMNS.filter((column) => visibleBookingColumns.has(column)).length;
}

function applyBookingColumnVisibility() {
  LOCKED_BOOKING_COLUMNS.forEach((column) => visibleBookingColumns.add(column));
  const visibleOrder = [...visibleBookingColumns]
    .filter((column) => BOOKING_COLUMNS.includes(column) && column !== "actions");
  const hiddenOrder = BOOKING_COLUMNS
    .filter((column) => column !== "actions" && !visibleBookingColumns.has(column));
  const columnOrder = [...visibleOrder, ...hiddenOrder, "actions"];
  document.querySelectorAll("#bookings-table tr").forEach((row) => {
    const cells = new Map(
      [...row.querySelectorAll("[data-table-column]")]
        .map((cell) => [cell.dataset.tableColumn, cell]),
    );
    columnOrder.forEach((column) => {
      if (cells.has(column)) row.append(cells.get(column));
    });
  });
  document.querySelectorAll("#bookings-table [data-table-column]").forEach((cell) => {
    cell.hidden = !visibleBookingColumns.has(cell.dataset.tableColumn);
  });
  document.querySelectorAll("[data-booking-column-toggle]").forEach((checkbox) => {
    checkbox.checked = visibleBookingColumns.has(checkbox.value);
  });
  document.querySelectorAll("#bookings-body .empty").forEach((cell) => {
    cell.colSpan = visibleBookingColumnCount();
  });
}

function setBookingColumnsPanel(open) {
  bookingColumnsPanel.hidden = !open;
  bookingColumnsButton.setAttribute("aria-expanded", String(open));
}

function bookingEmptyRow(message) {
  return `<tr><td colspan="${visibleBookingColumnCount()}" class="empty">${safe(message)}</td></tr>`;
}

async function loadBookings() {
  const query = bookingFilterQuery();
  document.querySelector("#booking-export").href = `/api/admin/bookings/export.csv?${query}`;
  const body = document.querySelector("#bookings-body");
  body.innerHTML = bookingEmptyRow("Loading bookings…");
  try {
    const bookings = await api(`/api/admin/bookings?${query}`);
    adminBookings = bookings;
    body.innerHTML = bookings.length ? bookings.map(bookingRow).join("") : bookingEmptyRow("No bookings match these filters.");
    applyBookingColumnVisibility();
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
    ? `<button type="button" class="manage-booking" data-booking-id="${booking.id}">${isOwner() ? "Manage" : "View"}</button>`
    : "Not available";
  const purpose = booking.purpose || "Not provided";
  const terms = booking.terms_accepted
    ? '<span class="status status-confirmed">Accepted</span>'
    : '<span class="status status-void">Not accepted</span>';
  const paymentLabel = booking.payment_method
    ? `${paymentFlowLabel(booking.payment_mode)} / ${booking.payment_method.replaceAll("_", " ")}`
    : paymentFlowLabel(booking.payment_mode);
  return `<tr>
    <td data-table-column="schedule">${safe(date)}<small>${safe(time)}</small></td>
    <td data-table-column="customer"><b>${safe(booking.customer_name || "Incomplete booking")}</b><small>${safe(booking.phone_number || "Phone not available")}</small></td>
    <td data-table-column="purpose" class="booking-purpose-cell" title="${safeAttr(purpose)}"><span>${safe(purpose)}</span></td>
    <td data-table-column="payment"><span class="status status-${safe(booking.payment_status)}">${safe(booking.payment_status.replaceAll("_", " "))}</span></td>
    <td data-table-column="status"><span class="status status-${safe(booking.status)}">${safe(booking.status.replaceAll("_", " "))}</span></td>
    <td data-table-column="reference" hidden><b>${safe(booking.reference)}</b><small>${safe(paymentLabel)}</small></td>
    <td data-table-column="terms" hidden>${terms}</td>
    <td data-table-column="value" hidden>${safe(currency.format(booking.total_amount))}<small>Paid ${safe(currency.format(booking.amount_paid || 0))} · Balance ${safe(currency.format(booking.balance_due || 0))}</small></td>
    <td data-table-column="actions">${action}</td>
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

function halfHourOptions(selected = "", startIndex = 0, endIndex = 48, showRange = false) {
  return Array.from({ length: endIndex - startIndex }, (_, offset) => {
    const minutes = (startIndex + offset) * 30;
    const value = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    const rangeEndMinutes = (minutes + 30) % (24 * 60);
    const rangeEnd = `${String(Math.floor(rangeEndMinutes / 60)).padStart(2, "0")}:${String(rangeEndMinutes % 60).padStart(2, "0")}`;
    const label = showRange ? `${displayTime(value)} - ${displayTime(rangeEnd)}` : displayTime(value);
    return `<option value="${value}"${value === selected ? " selected" : ""}>${label}</option>`;
  }).join("");
}

function durationOptions(selected = 1) {
  return Array.from({ length: 23 }, (_, index) => {
    const value = 1 + (index / 2);
    return `<option value="${value}"${value === Number(selected) ? " selected" : ""}>${value} hour${value === 1 ? "" : "s"}</option>`;
  }).join("");
}

function studioById(spaceId) {
  return studioSettings.find((studio) => studio.id === spaceId);
}

function setupOfflineBookingOptions({ refreshAmount = true } = {}) {
  if (!studioSettings.length) return;
  const studio = studioById(offlineBookingForm.elements.space_id.value) || studioSettings[0];
  offlineBookingForm.elements.space_id.value = studio.id;

  const startSelect = offlineBookingForm.elements.start_time;
  const previousStart = startSelect.value;
  const openingIndex = timeToMinutes(studio.opening_time) / 30;
  const latestStartIndex = (timeToMinutes(studio.closing_time) / 30) - (studio.min_duration_hours * 2);
  startSelect.innerHTML = halfHourOptions(previousStart, openingIndex, latestStartIndex + 1, true);
  if (!startSelect.value && startSelect.options.length) startSelect.selectedIndex = 0;

  const startMinutes = timeToMinutes(startSelect.value || studio.opening_time);
  const remainingHours = (timeToMinutes(studio.closing_time) - startMinutes) / 60;
  const maximumDuration = Math.min(studio.max_duration_hours, remainingHours);
  const durationSelect = offlineBookingForm.elements.duration_hours;
  const previousDuration = Number(durationSelect.value || studio.min_duration_hours);
  const durationCount = Math.max(0, Math.floor((maximumDuration - studio.min_duration_hours) * 2) + 1);
  durationSelect.innerHTML = Array.from({ length: durationCount }, (_, index) => {
    const value = studio.min_duration_hours + (index / 2);
    return `<option value="${value}">${value} hour${value === 1 ? "" : "s"}</option>`;
  }).join("");
  durationSelect.value = String(Math.min(Math.max(previousDuration, studio.min_duration_hours), maximumDuration));

  const purposeSelect = offlineBookingForm.elements.purpose;
  const previousPurpose = purposeSelect.value;
  purposeSelect.innerHTML = studio.booking_purposes.map((purpose) =>
    `<option value="${safeAttr(purpose)}">${safe(purpose)}</option>`
  ).join("");
  if (studio.booking_purposes.includes(previousPurpose)) purposeSelect.value = previousPurpose;

  if (refreshAmount) {
    offlineBookingForm.elements.total_amount.value = String(
      Math.round(studio.hourly_rate * Number(durationSelect.value || 0)),
    );
  }
}

function openOfflineBookingModal() {
  offlineBookingForm.reset();
  syncPaymentMethodSelect(
    "pay_at_studio",
    offlineBookingForm.elements.payment_method,
  );
  offlineBookingForm.elements.booking_date.value = localDate();
  const filteredSpace = bookingFilters.elements.space_id.value;
  if (studioSettings.some((studio) => studio.id === filteredSpace && studio.is_active)) {
    offlineBookingForm.elements.space_id.value = filteredSpace;
  }
  setupOfflineBookingOptions();
  const message = document.querySelector("#offline-booking-message");
  message.textContent = "";
  message.hidden = true;
  document.querySelector("#create-offline-booking-button").disabled = false;
  offlineBookingModal.hidden = false;
  offlineBookingForm.elements.customer_name.focus();
}

function syncStudioSelects() {
  const selects = [
    bookingFilters.elements.space_id,
    availabilityFilters.elements.space_id,
    bookingEditForm.elements.space_id,
    offlineBookingForm.elements.space_id,
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
  setupOfflineBookingOptions();
}

async function loadStudioSettings() {
  const root = document.querySelector("#studio-settings-list");
  if (isOwner()) root.innerHTML = '<p class="settings-empty">Loading studio settings…</p>';
  try {
    studioSettings = await api("/api/admin/studios");
    if (isOwner()) renderStudioSettings();
    syncStudioSelects();
  } catch (error) {
    if (isOwner()) root.innerHTML = `<p class="settings-empty">${safe(error.message)}</p>`;
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

async function loadStaffUsers() {
  if (!isOwner()) return;
  staffUsersList.innerHTML = '<p class="settings-empty">Loading staff users&hellip;</p>';
  try {
    const users = await api("/api/admin/staff-users");
    renderStaffUsers(users);
  } catch (error) {
    staffUsersList.innerHTML = `<p class="settings-empty">${safe(error.message)}</p>`;
    handleDashboardError(error);
  }
}

function renderStaffUsers(users) {
  const addButton = document.querySelector("#add-staff-user-button");
  addButton.disabled = users.length >= 2;
  addButton.textContent = users.length >= 2 ? "Two-user limit reached" : "Add staff user";
  if (!users.length) {
    staffUsersList.innerHTML = '<p class="settings-empty">No staff users have been added.</p>';
    return;
  }
  staffUsersList.innerHTML = users.map((user) => `
    <article class="staff-user-card" data-staff-user-id="${user.id}">
      <div class="staff-user-card-head">
        <div><h3>${safe(user.username)}</h3><p>View, export, block &amp; unblock access</p></div>
        <span class="status status-confirmed">Staff</span>
      </div>
      <div class="staff-user-card-actions">
        <label><span>New password</span><input data-staff-password type="password" minlength="10" maxlength="500" autocomplete="new-password" placeholder="At least 10 characters"></label>
        <button type="button" data-reset-staff-password>Reset password</button>
        <button class="staff-delete" type="button" data-delete-staff-user>Remove</button>
      </div>
    </article>
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

function currentWeekRange() {
  const dayOfWeek = new Date().getDay() || 7;
  const mondayOffset = 1 - dayOfWeek;
  return {
    from: localDate(mondayOffset),
    to: localDate(mondayOffset + 6),
  };
}

function setupHalfHourBlockOptions() {
  if (!studioSettings.length) return;
  const startSelect = availabilityBlockForm.elements.start_time;
  const studio = studioById(availabilityFilters.elements.space_id.value) || studioSettings[0];
  const openingIndex = timeToMinutes(studio.opening_time) / 30;
  const closingIndex = timeToMinutes(studio.closing_time) / 30;
  const previous = startSelect.value;
  const selectedDate = availabilityFilters.elements.booking_date.value;
  const dayIsLoaded = currentAvailabilityDay
    && currentAvailabilityDay.space_id === studio.id
    && currentAvailabilityDay.booking_date === selectedDate;
  const slotsByStart = new Map((dayIsLoaded ? currentAvailabilityDay.slots : []).map((slot) => [slot.start_time, slot]));
  const values = Array.from({ length: Math.max(0, closingIndex - openingIndex) }, (_, offset) => {
    const minutes = (openingIndex + offset) * 30;
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  });
  const blockableStatuses = new Set(isOwner() ? ["available", "past"] : ["available"]);
  const firstAvailable = values.find((value) => blockableStatuses.has(slotsByStart.get(value)?.status)) || "";
  startSelect.innerHTML = values.map((value) => {
    const slot = slotsByStart.get(value);
    const available = blockableStatuses.has(slot?.status);
    const endValue = slot?.end_time || minutesToTime(timeToMinutes(value) + 30);
    const suffix = dayIsLoaded && !available
      ? ` (${String(slot?.status || "unavailable").replaceAll("_", " ")})`
      : "";
    return `<option value="${value}"${available ? "" : " disabled"}>${displayTime(value)} - ${displayTime(endValue)}${safe(suffix)}</option>`;
  }).join("");
  startSelect.value = blockableStatuses.has(slotsByStart.get(previous)?.status) ? previous : firstAvailable;
  syncBlockDurationOptions();
}

function syncBlockDurationOptions() {
  const studio = studioById(availabilityFilters.elements.space_id.value) || studioSettings[0];
  if (!studio) return;
  const startValue = availabilityBlockForm.elements.start_time.value;
  const durationSelect = availabilityBlockForm.elements.duration_hours;
  const button = document.querySelector("#block-time-button");
  const previousDuration = Number(durationSelect.value || 0.5);
  const selectedDate = availabilityFilters.elements.booking_date.value;
  const dayIsLoaded = currentAvailabilityDay
    && currentAvailabilityDay.space_id === studio.id
    && currentAvailabilityDay.booking_date === selectedDate;
  const startIndex = dayIsLoaded
    ? currentAvailabilityDay.slots.findIndex((slot) => slot.start_time === startValue)
    : -1;
  let contiguousHalfHours = 0;
  const blockableStatuses = new Set(isOwner() ? ["available", "past"] : ["available"]);
  if (startIndex >= 0) {
    for (const slot of currentAvailabilityDay.slots.slice(startIndex)) {
      if (!blockableStatuses.has(slot.status) || contiguousHalfHours >= MAX_BLOCK_DURATION_HOURS * 2) break;
      contiguousHalfHours += 1;
    }
  }
  const maximumDuration = contiguousHalfHours / 2;
  const optionCount = contiguousHalfHours;
  durationSelect.innerHTML = Array.from({ length: optionCount }, (_, index) => {
    const duration = 0.5 + (index / 2);
    const label = duration === 0.5 ? "30 minutes" : `${duration} hour${duration === 1 ? "" : "s"}`;
    return `<option value="${duration}">${label}</option>`;
  }).join("");
  if (maximumDuration) durationSelect.value = String(Math.max(0.5, Math.min(previousDuration, maximumDuration)));
  button.disabled = !startValue || !maximumDuration;
}

function availableEditHalfHoursFrom(startTime) {
  if (!currentBookingEditDay) return 0;
  const startIndex = currentBookingEditDay.slots.findIndex((slot) => slot.start_time === startTime);
  if (startIndex < 0) return 0;
  let count = 0;
  for (const slot of currentBookingEditDay.slots.slice(startIndex)) {
    if (slot.status !== "available") break;
    count += 1;
  }
  return count;
}

function setupBookingEditOptions(preferredStart = "") {
  if (!studioSettings.length) return;
  const startSelect = bookingEditForm.elements.start_time;
  const studio = studioById(bookingEditForm.elements.space_id.value) || studioSettings[0];
  const selectedDate = bookingEditForm.elements.booking_date.value;
  const dayIsLoaded = currentBookingEditDay
    && currentBookingEditDay.space_id === studio.id
    && currentBookingEditDay.booking_date === selectedDate;
  if (!dayIsLoaded) {
    const currentStart = preferredStart || startSelect.value;
    if (currentStart) {
      const currentEnd = minutesToTime(timeToMinutes(currentStart) + 30);
      startSelect.innerHTML = `<option value="${safeAttr(currentStart)}">${displayTime(currentStart)} - ${displayTime(currentEnd)} (checking availability)</option>`;
      startSelect.value = currentStart;
    } else {
      startSelect.innerHTML = '<option value="">Checking live availability…</option>';
    }
    startSelect.disabled = true;
    document.querySelector("#save-booking-button").disabled = true;
    return;
  }

  const previous = preferredStart || startSelect.value;
  const requiredHalfHours = Number(bookingEditForm.elements.duration_hours.value) * 2;
  const originalBooking = adminBookings.find(
    (booking) => booking.id === Number(bookingEditForm.elements.booking_id.value),
  );
  const validStarts = new Set();
  startSelect.innerHTML = currentBookingEditDay.slots.map((slot) => {
    const isCurrentStart = slot.start_time === previous;
    const availableHalfHours = availableEditHalfHoursFrom(slot.start_time);
    const slotIndex = currentBookingEditDay.slots.findIndex(
      (candidate) => candidate.start_time === slot.start_time,
    );
    const currentInterval = currentBookingEditDay.slots.slice(slotIndex, slotIndex + requiredHalfHours);
    const canKeepCurrentSchedule = Boolean(
      isCurrentStart
      && originalBooking
      && originalBooking.booking_date === selectedDate
      && originalBooking.start_time === slot.start_time
      && currentInterval.length === requiredHalfHours
      && currentInterval.every((candidate) => ["available", "past"].includes(candidate.status)),
    );
    const selectable = (
      slot.status === "available" && availableHalfHours >= requiredHalfHours
    ) || canKeepCurrentSchedule;
    if (selectable) validStarts.add(slot.start_time);
    const suffix = canKeepCurrentSchedule && slot.status !== "available"
      ? " (current booking)"
      : selectable
      ? ""
      : isCurrentStart
        ? " (current booking)"
        : ` (${slot.status === "available" ? "insufficient time" : slot.status.replaceAll("_", " ")})`;
    return `<option value="${safeAttr(slot.start_time)}"${selectable ? "" : " disabled"}>${displayTime(slot.start_time)} - ${displayTime(slot.end_time)}${safe(suffix)}</option>`;
  }).join("");
  const currentStartExists = currentBookingEditDay.slots.some((slot) => slot.start_time === previous);
  startSelect.value = currentStartExists ? previous : [...validStarts][0] || "";
  startSelect.disabled = validStarts.size === 0;
  syncBookingEditSaveState();
}

function syncBookingEditSaveState() {
  const startSelect = bookingEditForm.elements.start_time;
  const saveButton = document.querySelector("#save-booking-button");
  saveButton.disabled = startSelect.disabled || !startSelect.value || Boolean(startSelect.selectedOptions[0]?.disabled);
}

function syncBookingEditPaymentEstimate() {
  const booking = adminBookings.find(
    (item) => item.id === Number(bookingEditForm.elements.booking_id.value),
  );
  if (!booking) return;
  const selectedSpace = studioById(bookingEditForm.elements.space_id.value);
  const studioChanged = Boolean(selectedSpace && selectedSpace.id !== booking.space_id);
  const amount = studioChanged
    ? Math.round(selectedSpace.hourly_rate * Number(bookingEditForm.elements.duration_hours.value || 0))
    : booking.total_amount;
  const suffix = studioChanged ? " after studio change" : "";
  const amountPaid = booking.amount_paid || 0;
  const balanceDue = Math.max(0, amount - amountPaid);
  const paymentDescription = booking.payment_method
    ? `${paymentFlowLabel(booking.payment_mode)} · ${booking.payment_method.replaceAll("_", " ")}`
    : paymentFlowLabel(booking.payment_mode);
  document.querySelector("#booking-payment-summary").textContent =
    `${paymentDescription} · Total ${currency.format(amount)} · Paid ${currency.format(amountPaid)} · Balance ${currency.format(balanceDue)}${suffix}`;
}

function renderPaymentHistory(booking) {
  const list = document.querySelector("#payment-history-list");
  const transactions = booking.payment_transactions || [];
  if (!transactions.length) {
    list.innerHTML = '<div class="payment-history-list-empty">No payments recorded yet.</div>';
    return;
  }
  list.innerHTML = transactions.map((transaction) => {
    const method = transaction.payment_method?.replaceAll("_", " ") || "Method not recorded";
    const reference = transaction.provider_reference || "No reference";
    const timestamp = new Date(transaction.occurred_at).toLocaleString("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    });
    return `<div class="payment-history-entry">
      <b>${safe(transaction.transaction_type)} · ${safe(currency.format(transaction.amount))}</b>
      <span>${safe(method)}</span>
      <span>${safe(reference)} · ${safe(timestamp)}</span>
    </div>`;
  }).join("");
}

function configureBookingStudioOptions(booking) {
  const studioSelect = bookingEditForm.elements.space_id;
  Array.from(studioSelect.options).forEach((option) => {
    const isCurrentStudio = option.value === booking.space_id;
    const isCubeToArenaUpgrade = booking.space_id === "standard_small" && option.value === "premium_large";
    option.disabled = !isCurrentStudio && !isCubeToArenaUpgrade;
    const studio = studioById(option.value);
    option.textContent = studio?.name || (option.value === "standard_small" ? "Cube" : "Arena");
    if (option.disabled && booking.space_id === "premium_large" && option.value === "standard_small") {
      option.textContent += " (downgrade unavailable)";
    }
  });
}

async function loadBookingEditAvailability(preferredStart = "") {
  const bookingId = bookingEditForm.elements.booking_id.value;
  const spaceId = bookingEditForm.elements.space_id.value;
  const bookingDate = bookingEditForm.elements.booking_date.value;
  if (!bookingId || !spaceId || !bookingDate) return;
  const requestToken = ++bookingEditAvailabilityRequestToken;
  bookingEditAvailabilityRequestController?.abort();
  const controller = new AbortController();
  bookingEditAvailabilityRequestController = controller;
  currentBookingEditDay = null;
  setupBookingEditOptions();
  const query = new URLSearchParams({
    space_id: spaceId,
    booking_date: bookingDate,
    exclude_booking_id: bookingId,
  });
  try {
    const day = await api(`/api/admin/availability?${query}`, { signal: controller.signal });
    if (
      requestToken !== bookingEditAvailabilityRequestToken
      || bookingEditForm.elements.booking_id.value !== bookingId
      || bookingEditForm.elements.space_id.value !== spaceId
      || bookingEditForm.elements.booking_date.value !== bookingDate
    ) return;
    currentBookingEditDay = day;
    setupBookingEditOptions(preferredStart);
  } catch (error) {
    if (error.name === "AbortError" || requestToken !== bookingEditAvailabilityRequestToken) return;
    const message = document.querySelector("#booking-edit-message");
    message.textContent = `Live availability could not be loaded. ${error.message}`;
    message.hidden = false;
  } finally {
    if (requestToken === bookingEditAvailabilityRequestToken) {
      bookingEditAvailabilityRequestController = null;
    }
  }
}

function timeToMinutes(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return (hours * 60) + minutes;
}

function minutesToTime(minutes) {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function openBookingModal(bookingId) {
  const booking = adminBookings.find((item) => item.id === Number(bookingId));
  if (!booking) return;
  bookingEditForm.reset();
  bookingEditForm.elements.booking_id.value = booking.id;
  bookingEditForm.elements.space_id.value = booking.space_id;
  configureBookingStudioOptions(booking);
  bookingEditForm.elements.booking_date.value = booking.booking_date;
  const bookingSlotEnd = minutesToTime(timeToMinutes(booking.start_time) + 30);
  bookingEditForm.elements.start_time.innerHTML = `<option value="${safeAttr(booking.start_time)}">${displayTime(booking.start_time)} - ${displayTime(bookingSlotEnd)}</option>`;
  bookingEditForm.elements.duration_hours.value = String(booking.duration_hours);
  bookingEditForm.elements.duration_display.value = `${booking.duration_hours} hour${booking.duration_hours === 1 ? "" : "s"}`;
  bookingEditForm.elements.customer_name.value = booking.customer_name || "";
  bookingEditForm.elements.customer_email.value = booking.customer_email || "";
  bookingEditForm.elements.phone_number.value = booking.phone_number || "";
  bookingEditForm.elements.purpose.value = booking.purpose || "";
  const editable = isOwner() && booking.status === "confirmed";
  bookingEditForm.querySelectorAll(".edit-grid input,.edit-grid select,.edit-grid textarea")
    .forEach((field) => { field.disabled = !editable; });
  document.querySelector("#save-booking-button").hidden = !editable;
  document.querySelector("#cancel-booking-button").hidden = !editable;
  document.querySelector("#booking-payment-status").textContent = booking.payment_status.replaceAll("_", " ");
  syncBookingEditPaymentEstimate();
  renderPaymentHistory(booking);
  const paymentReference = document.querySelector("#payment-reference");
  paymentReference.value = "";
  paymentReference.disabled = !isOwner();
  const paymentFlow = document.querySelector("#payment-flow");
  paymentFlow.value = paymentFlowLabel(booking.payment_mode);
  const paymentMethod = document.querySelector("#payment-method");
  syncPaymentMethodSelect(
    booking.payment_mode || "pay_at_studio",
    paymentMethod,
    booking.payment_method || "",
  );
  const canReceivePayment = ["pending", "partially_paid"].includes(booking.payment_status);
  paymentMethod.disabled = !isOwner() || !canReceivePayment;
  const paymentAmount = document.querySelector("#payment-amount");
  paymentAmount.value = canReceivePayment ? String(booking.balance_due || "") : "";
  paymentAmount.max = String(booking.balance_due || booking.total_amount || 1);
  paymentAmount.disabled = !isOwner() || !canReceivePayment;
  const paymentAction = document.querySelector("#payment-action-button");
  if (isOwner() && canReceivePayment && ["payment_pending", "confirmed"].includes(booking.status)) {
    paymentAction.hidden = false;
    paymentAction.dataset.status = "paid";
    paymentAction.textContent = "Record payment";
  } else if (isOwner() && booking.payment_status === "refund_due") {
    paymentAction.hidden = false;
    paymentAction.dataset.status = "refunded";
    paymentAction.textContent = "Mark refunded";
    paymentReference.disabled = false;
  } else {
    paymentAction.hidden = true;
    delete paymentAction.dataset.status;
  }
  document.querySelector("#booking-modal-reference").textContent = booking.reference;
  document.querySelector("#booking-edit-message").hidden = true;
  bookingModal.hidden = false;
  if (editable) loadBookingEditAvailability(booking.start_time);
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
  closeSlotContextMenu();
  currentAvailabilityDay = null;
  setupHalfHourBlockOptions();
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
    currentAvailabilityDay = day;
    slots.innerHTML = day.slots.map(availabilitySlot).join("");
    setupHalfHourBlockOptions();
  } catch (error) {
    if (error.name === "AbortError" || requestToken !== availabilityRequestToken) return;
    slots.innerHTML = `<p class="availability-empty">${safe(error.message)}</p>`;
    setupHalfHourBlockOptions();
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
    action = `data-unblock="${slot.block_id}" data-slot-start="${safeAttr(slot.start_time)}" data-slot-end="${safeAttr(slot.end_time)}" aria-haspopup="menu"`;
  }
  if (slot.status === "booked") {
    if (slot.booking_id) {
      action = `data-view-availability-booking="${slot.booking_id}"`;
    } else {
      action = "";
      disabled = "disabled";
    }
  }
  if (slot.status === "past") {
    detail = isOwner()
      ? "Past time available for historical blocking"
      : "Past time · Owner access required to block";
    if (!isOwner()) {
      action = "";
      disabled = "disabled";
    }
  }
  if (slot.status === "unavailable") {
    detail = "Calendar unavailable";
    action = "";
    disabled = "disabled";
  }
  const canBlock = slot.status === "available" || (slot.status === "past" && isOwner());
  const actionLabel = slot.status === "booked" && slot.booking_id
    ? "Click to view booking"
    : canBlock
    ? "Click to block"
    : slot.status === "blocked" ? "Right-click or tap to unblock" : detail;
  const statusLabel = slot.status.replaceAll("_", " ");
  const reasonLabel = slot.status === "blocked" && slot.reason
    ? `<strong class="admin-slot-reason">${safe(slot.reason)}</strong>`
    : "";
  const slotLabel = `${displayTime(slot.start_time)} - ${displayTime(slot.end_time)}`;
  const title = `${slotLabel} · ${detail}`;
  return `<button type="button" class="admin-slot-button ${safeAttr(slot.status)}" ${action} ${disabled} title="${safeAttr(title)}">
    <span>${safe(slotLabel)}</span>
    <small>${safe(statusLabel)}</small>
    ${reasonLabel}
    <em>${safe(actionLabel)}</em>
  </button>`;
}

function setAvailabilityBookingDetail(field, value) {
  document.querySelector(`#availability-detail-${field}`).textContent = value;
}

async function openAvailabilityBookingModal(bookingId) {
  const message = document.querySelector("#availability-booking-modal-message");
  message.hidden = true;
  setAvailabilityBookingDetail("reference", "Loading…");
  ["schedule", "customer", "studio", "purpose", "payment", "status"].forEach((field) => {
    setAvailabilityBookingDetail(field, "—");
  });
  availabilityBookingModal.hidden = false;

  try {
    const booking = await api(`/api/admin/bookings/${bookingId}`);
    const duration = booking.duration_hours
      ? `${booking.duration_hours} hour${booking.duration_hours === 1 ? "" : "s"}`
      : "Duration not available";
    const schedule = booking.booking_date && booking.start_time
      ? `${formatDate(booking.booking_date)} · ${displayTime(booking.start_time)} to ${displayTime(booking.end_time)} · ${duration}`
      : "Not scheduled";
    const customer = [booking.customer_name, booking.phone_number].filter(Boolean).join(" · ") || "Not provided";
    const paymentMethod = booking.payment_method ? readableLabel(booking.payment_method) : "Method not recorded";
    const payment = `${readableLabel(booking.payment_status)} · ${currency.format(booking.amount_paid || 0)} paid of ${currency.format(booking.total_amount || 0)} · ${paymentFlowLabel(booking.payment_mode)} / ${paymentMethod}`;

    setAvailabilityBookingDetail("reference", booking.reference);
    setAvailabilityBookingDetail("schedule", schedule);
    setAvailabilityBookingDetail("customer", customer);
    setAvailabilityBookingDetail("studio", booking.space_name || "Not selected");
    setAvailabilityBookingDetail("purpose", booking.purpose || "Not provided");
    setAvailabilityBookingDetail("payment", payment);
    setAvailabilityBookingDetail("status", readableLabel(booking.status));
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
    setAvailabilityBookingDetail("reference", "Unable to load booking");
    if (error.status === 401) handleDashboardError(error);
  }
}

function closeSlotContextMenu() {
  slotContextMenu.hidden = true;
  contextSlot = null;
}

function openSlotContextMenu(button, clientX = null, clientY = null) {
  contextSlot = {
    blockId: button.dataset.unblock,
    startTime: button.dataset.slotStart,
    endTime: button.dataset.slotEnd,
  };
  document.querySelector("#slot-context-label").textContent =
    `${displayTime(contextSlot.startTime)} - ${displayTime(contextSlot.endTime)} is blocked`;
  slotContextMenu.hidden = false;
  const anchor = button.getBoundingClientRect();
  const desiredLeft = clientX ?? anchor.left;
  const desiredTop = clientY ?? anchor.bottom + 6;
  const menuRect = slotContextMenu.getBoundingClientRect();
  slotContextMenu.style.left = `${Math.max(8, Math.min(desiredLeft, window.innerWidth - menuRect.width - 8))}px`;
  slotContextMenu.style.top = `${Math.max(8, Math.min(desiredTop, window.innerHeight - menuRect.height - 8))}px`;
  unblockSlotAction.focus();
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
    await showDashboard(session);
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
    await showDashboard(session);
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
document.querySelector("#add-offline-booking-button").addEventListener("click", openOfflineBookingModal);
document.querySelector(".offline-booking-modal-close").addEventListener("click", () => {
  offlineBookingModal.hidden = true;
});
offlineBookingModal.addEventListener("click", (event) => {
  if (event.target === offlineBookingModal) offlineBookingModal.hidden = true;
});
offlineBookingForm.elements.space_id.addEventListener("change", () => setupOfflineBookingOptions());
offlineBookingForm.elements.start_time.addEventListener("change", () => setupOfflineBookingOptions());
offlineBookingForm.elements.duration_hours.addEventListener("change", () => {
  const studio = studioById(offlineBookingForm.elements.space_id.value);
  if (!studio) return;
  offlineBookingForm.elements.total_amount.value = String(
    Math.round(studio.hourly_rate * Number(offlineBookingForm.elements.duration_hours.value || 0)),
  );
});
offlineBookingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(offlineBookingForm);
  const button = document.querySelector("#create-offline-booking-button");
  const message = document.querySelector("#offline-booking-message");
  button.disabled = true;
  message.hidden = true;
  try {
    const booking = await api("/api/admin/bookings/offline", {
      method: "POST",
      body: JSON.stringify({
        space_id: data.get("space_id"),
        booking_date: data.get("booking_date"),
        start_time: data.get("start_time"),
        duration_hours: Number(data.get("duration_hours")),
        customer_name: data.get("customer_name"),
        customer_email: data.get("customer_email"),
        phone_number: data.get("phone_number"),
        purpose: data.get("purpose"),
        total_amount: Number(data.get("total_amount")),
        payment_method: data.get("payment_method") || null,
        terms_accepted: data.has("terms_accepted"),
      }),
    });
    offlineBookingModal.hidden = true;
    bookingFilters.elements.space_id.value = booking.space_id;
    bookingFilters.elements.q.value = "";
    bookingFilters.elements.status.value = "";
    bookingFilters.elements.date_from.value = booking.booking_date;
    bookingFilters.elements.date_to.value = booking.booking_date;
    showDashboardMessage(
      "#dashboard-message",
      `${booking.reference} created as a confirmed offline booking. Payment is pending.`,
    );
    await Promise.all([loadDashboardAnalytics(), loadBookings(), loadAvailability()]);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
});
bookingColumnsButton.addEventListener("click", () => {
  setBookingColumnsPanel(bookingColumnsPanel.hidden);
});
bookingColumnsPanel.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-booking-column-toggle]");
  if (!checkbox || LOCKED_BOOKING_COLUMNS.has(checkbox.value)) return;
  visibleBookingColumns.delete("actions");
  if (checkbox.checked) visibleBookingColumns.add(checkbox.value);
  else visibleBookingColumns.delete(checkbox.value);
  visibleBookingColumns.add("actions");
  saveBookingColumnPreferences();
  applyBookingColumnVisibility();
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
  if (!event.target.closest(".booking-column-menu")) setBookingColumnsPanel(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setAlertPanel(false);
    setAccountMenu(false);
    setBookingColumnsPanel(false);
    availabilityBookingModal.hidden = true;
    bookingModal.hidden = true;
    offlineBookingModal.hidden = true;
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
        duration_hours: Number(bookingEditForm.elements.duration_hours.value),
        customer_name: data.get("customer_name"),
        customer_email: data.get("customer_email"),
        phone_number: data.get("phone_number"),
        purpose: data.get("purpose"),
      }),
    });
    bookingModal.hidden = true;
    showDashboardMessage("#dashboard-message", `${booking.reference} updated successfully.`);
    await Promise.all([loadDashboardAnalytics(), loadBookings(), loadAvailability()]);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    syncBookingEditSaveState();
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
    await Promise.all([loadDashboardAnalytics(), loadBookings(), loadAvailability()]);
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
  const paymentMethod = document.querySelector("#payment-method").value;
  const paymentAmount = Number(document.querySelector("#payment-amount").value || 0);
  if (status === "paid" && !paymentMethod) {
    const message = document.querySelector("#booking-edit-message");
    message.textContent = "Choose the payment method before marking this booking as paid.";
    message.hidden = false;
    return;
  }
  if (status === "paid" && paymentAmount <= 0) {
    const message = document.querySelector("#booking-edit-message");
    message.textContent = "Enter the payment amount received.";
    message.hidden = false;
    return;
  }
  button.disabled = true;
  try {
    const booking = await api(`/api/admin/bookings/${bookingId}/payment`, {
      method: "POST",
      body: JSON.stringify({
        status,
        provider_reference: reference || null,
        payment_method: paymentMethod || null,
        amount: status === "paid" ? paymentAmount : null,
      }),
    });
    bookingModal.hidden = true;
    showDashboardMessage(
      "#dashboard-message",
      `${booking.reference} payment marked ${booking.payment_status.replaceAll("_", " ")}.`,
    );
    await Promise.all([loadDashboardAnalytics(), loadBookings()]);
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
bookingEditForm.elements.space_id.addEventListener("change", () => {
  syncBookingEditPaymentEstimate();
  loadBookingEditAvailability();
});
bookingEditForm.elements.booking_date.addEventListener("change", () => loadBookingEditAvailability());
bookingEditForm.elements.start_time.addEventListener("change", syncBookingEditSaveState);
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
        reason: block.get("reason") || "Maintenance",
      }),
    });
    showDashboardMessage(
      "#availability-message",
      "Studio time blocked. Customer availability has been updated.",
    );
    availabilityBlockForm.elements.reason.value = "Maintenance";
    await loadAvailability();
  } catch (error) {
    showDashboardMessage("#availability-message", error.message, { autoHide: false, kind: "error" });
  } finally {
    syncBlockDurationOptions();
  }
});
document.querySelector("#availability-slots").addEventListener("click", (event) => {
  const bookingButton = event.target.closest("[data-view-availability-booking]");
  if (bookingButton) {
    openAvailabilityBookingModal(bookingButton.dataset.viewAvailabilityBooking);
    return;
  }
  const blockButton = event.target.closest("[data-block-start]");
  if (blockButton) {
    availabilityBlockForm.elements.start_time.value = blockButton.dataset.blockStart;
    syncBlockDurationOptions();
    availabilityBlockForm.elements.reason.focus();
    return;
  }
  const unblockButton = event.target.closest("[data-unblock]");
  if (!unblockButton) return;
  event.stopPropagation();
  openSlotContextMenu(unblockButton);
});
document.querySelector("#availability-slots").addEventListener("contextmenu", (event) => {
  const unblockButton = event.target.closest("[data-unblock]");
  if (!unblockButton) return;
  event.preventDefault();
  event.stopPropagation();
  openSlotContextMenu(unblockButton, event.clientX, event.clientY);
});
unblockSlotAction.addEventListener("click", async () => {
  if (!contextSlot) return;
  const selectedSlot = { ...contextSlot };
  unblockSlotAction.disabled = true;
  try {
    const query = new URLSearchParams({ start_time: selectedSlot.startTime });
    await api(`/api/admin/availability/blocks/${selectedSlot.blockId}/slot?${query}`, { method: "DELETE" });
    closeSlotContextMenu();
    showDashboardMessage(
      "#availability-message",
      `${displayTime(selectedSlot.startTime)} - ${displayTime(selectedSlot.endTime)} reopened for customer bookings.`,
    );
    await loadAvailability();
  } catch (error) {
    showDashboardMessage("#availability-message", error.message, { autoHide: false, kind: "error" });
  } finally {
    unblockSlotAction.disabled = false;
  }
});
document.addEventListener("click", (event) => {
  if (!slotContextMenu.hidden && !event.target.closest("#slot-context-menu")) closeSlotContextMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !slotContextMenu.hidden) closeSlotContextMenu();
});
window.addEventListener("resize", closeSlotContextMenu);
window.addEventListener("scroll", closeSlotContextMenu, true);
bookingFilters.elements.space_id.addEventListener("change", loadBookings);
bookingFilters.elements.status.addEventListener("change", loadBookings);
bookingFilters.querySelectorAll('input[type="date"]').forEach((input) => {
  input.addEventListener("change", loadBookings);
});
staffUserForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(staffUserForm);
  const button = document.querySelector("#add-staff-user-button");
  button.disabled = true;
  try {
    const user = await api("/api/admin/staff-users", {
      method: "POST",
      body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
    });
    staffUserForm.reset();
    showDashboardMessage("#staff-users-message", `${user.username} can now sign in with staff access.`);
    await loadStaffUsers();
  } catch (error) {
    showDashboardMessage("#staff-users-message", error.message, { autoHide: false, kind: "error" });
    button.disabled = false;
  }
});
staffUsersList.addEventListener("click", async (event) => {
  const card = event.target.closest("[data-staff-user-id]");
  if (!card) return;
  const userId = card.dataset.staffUserId;
  const username = card.querySelector("h3").textContent;
  const resetButton = event.target.closest("[data-reset-staff-password]");
  const deleteButton = event.target.closest("[data-delete-staff-user]");
  if (resetButton) {
    const password = card.querySelector("[data-staff-password]").value;
    if (password.length < 10) {
      showDashboardMessage("#staff-users-message", "The new password must be at least 10 characters.", { autoHide: false, kind: "error" });
      return;
    }
    resetButton.disabled = true;
    try {
      await api(`/api/admin/staff-users/${userId}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      showDashboardMessage("#staff-users-message", `${username}'s password was reset. Existing sessions were signed out.`);
      await loadStaffUsers();
    } catch (error) {
      showDashboardMessage("#staff-users-message", error.message, { autoHide: false, kind: "error" });
      resetButton.disabled = false;
    }
    return;
  }
  if (!deleteButton || !window.confirm(`Remove staff access for ${username}?`)) return;
  deleteButton.disabled = true;
  try {
    await api(`/api/admin/staff-users/${userId}`, { method: "DELETE" });
    showDashboardMessage("#staff-users-message", `${username}'s staff access was removed.`);
    await loadStaffUsers();
  } catch (error) {
    showDashboardMessage("#staff-users-message", error.message, { autoHide: false, kind: "error" });
    deleteButton.disabled = false;
  }
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
    await Promise.all([loadDashboardAnalytics(), loadBookings(), loadAvailability()]);
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
document.querySelector(".availability-booking-modal-close").addEventListener("click", () => {
  availabilityBookingModal.hidden = true;
});
availabilityBookingModal.addEventListener("click", (event) => {
  if (event.target === availabilityBookingModal) availabilityBookingModal.hidden = true;
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
availabilityFilters.elements.booking_date.value = localDate();
const bookingWeek = currentWeekRange();
bookingFilters.elements.date_from.value = bookingWeek.from;
bookingFilters.elements.date_to.value = bookingWeek.to;
bookingEditForm.elements.booking_date.min = localDate();
applyBookingColumnVisibility();
setupHalfHourBlockOptions();
setupBookingEditOptions();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !dashboardView.hidden) loadAlerts();
});

api("/api/admin/session")
  .then((session) => session.authenticated ? showDashboard(session) : session.setup_required ? showSetup() : showLogin())
  .catch(() => showLogin("Unable to check the dashboard session."));
