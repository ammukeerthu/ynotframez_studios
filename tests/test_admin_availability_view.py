import unittest
from pathlib import Path


class AdminAvailabilityViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[1]
        cls.html = (project_root / "app" / "web" / "admin.html").read_text(encoding="utf-8")
        cls.script = (project_root / "app" / "static" / "admin.js").read_text(encoding="utf-8")
        cls.styles = (project_root / "app" / "static" / "admin.css").read_text(encoding="utf-8")

    def test_admin_block_controls_use_half_hour_intervals(self) -> None:
        self.assertIn("<h3>Block Studio</h3>", self.html)
        self.assertNotIn("CLOSE A TIME WINDOW", self.html)
        self.assertNotIn("<h3>Block studio time</h3>", self.html)
        self.assertIn("Minimum block: 30 minutes.", self.html)
        self.assertIn("past, current, or future dates", self.html)
        self.assertNotIn("Minimum block: 2 hours.", self.html)
        self.assertNotIn("availabilityFilters.elements.booking_date.min", self.script)
        self.assertIn('isOwner() ? ["available", "past"] : ["available"]', self.script)
        self.assertIn('slot.status === "past" && isOwner()', self.script)
        self.assertIn('class="admin-slot-reason">${safe(slot.reason)}', self.script)
        self.assertIn(".admin-slot-reason {", self.styles)
        reason_style = self.styles.split(".admin-slot-reason {", 1)[1].split("}", 1)[0]
        self.assertNotIn("text-transform:uppercase", reason_style)
        self.assertIn('availabilityBlockForm.elements.reason.focus()', self.script)
        self.assertIn("const duration = 0.5 + (index / 2);", self.script)
        self.assertIn("30 minutes", self.script)
        self.assertIn(" disabled", self.script)

    def test_admin_block_reason_is_a_fixed_dropdown(self) -> None:
        self.assertIn('<select name="reason" required>', self.html)
        for reason in (
            "Maintenance",
            "Power Shutdown",
            "Technical Issue",
            "Mandatory Holiday",
            "Collaboration",
        ):
            self.assertIn(f'<option value="{reason}">{reason}</option>', self.html)
        self.assertNotIn('<input name="reason"', self.html)

    def test_booked_availability_tile_opens_read_only_booking_summary(self) -> None:
        modal = self.html.split('<div id="availability-booking-modal"', 1)[1].split(
            '<div id="booking-modal"', 1
        )[0]
        for label in (
            "REFERENCE",
            "DATE &amp; TIME",
            "CUSTOMER",
            "STUDIO",
            "PURPOSE",
            "PAYMENT",
            "STATUS",
        ):
            self.assertIn(f"<span>{label}</span>", modal)
        self.assertIn('role="dialog"', modal)
        self.assertNotIn("<form", modal)
        self.assertNotIn("<input", modal)
        self.assertIn('data-view-availability-booking="${slot.booking_id}"', self.script)
        self.assertIn("openAvailabilityBookingModal(bookingButton.dataset.viewAvailabilityBooking)", self.script)
        self.assertIn("await api(`/api/admin/bookings/${bookingId}`)", self.script)
        self.assertIn("availabilityBookingModal.hidden = true", self.script)
        self.assertIn(".availability-booking-summary {", self.styles)
        self.assertIn(".admin-slot-button.booked:hover", self.styles)

    def test_dashboard_date_views_open_on_today(self) -> None:
        self.assertIn('<span>FROM</span><input name="date_from" type="date">', self.html)
        self.assertIn('<span>TO</span><input name="date_to" type="date">', self.html)
        self.assertNotIn("<span>FROM DATE</span>", self.html)
        self.assertNotIn("<span>TO DATE</span>", self.html)
        self.assertIn("availabilityFilters.elements.booking_date.value = localDate();", self.script)
        self.assertIn("function currentWeekRange()", self.script)
        self.assertIn("const dayOfWeek = new Date().getDay() || 7;", self.script)
        self.assertIn("from: localDate(mondayOffset)", self.script)
        self.assertIn("to: localDate(mondayOffset + 6)", self.script)
        self.assertIn("bookingFilters.elements.date_from.value = bookingWeek.from;", self.script)
        self.assertIn("bookingFilters.elements.date_to.value = bookingWeek.to;", self.script)
        self.assertNotIn("availabilityFilters.elements.booking_date.value = localDate(1);", self.script)

    def test_booking_table_has_purpose_terms_and_persisted_column_controls(self) -> None:
        self.assertIn('data-table-column="purpose">Purpose', self.html)
        self.assertIn('data-table-column="payment">Payment status', self.html)
        self.assertIn('data-table-column="status">Booking status', self.html)
        self.assertIn('value="payment" data-booking-column-toggle checked><span>Payment status', self.html)
        self.assertIn('value="status" data-booking-column-toggle checked><span>Booking status', self.html)
        self.assertIn('data-table-column="terms" hidden>Terms accepted', self.html)
        self.assertIn('value="reference" data-booking-column-toggle><span>Reference', self.html)
        self.assertIn('value="value" data-booking-column-toggle><span>Amount', self.html)
        self.assertIn('data-table-column="value" hidden>Amount', self.html)
        self.assertNotIn('data-table-column="value" hidden>Value', self.html)
        self.assertNotIn('value="studio" data-booking-column-toggle', self.html)
        self.assertNotIn('data-table-column="studio"', self.html)
        self.assertNotIn('data-table-column="studio"', self.script)
        self.assertIn('value="actions" data-booking-column-toggle checked disabled', self.html)
        self.assertIn('/static/admin.css?v=20260926-11', self.html)
        self.assertIn('/static/admin.js?v=20260926-13', self.html)
        self.assertIn('BOOKING_COLUMN_STORAGE_KEY = "ynf_admin_booking_columns_v2"', self.script)
        self.assertIn(
            'DEFAULT_BOOKING_COLUMNS = ["schedule", "customer", "purpose", "payment", "status", "actions"]',
            self.script,
        )
        header = self.html.split('<table id="bookings-table">', 1)[1].split("</thead>", 1)[0]
        expected_order = (
            'data-table-column="schedule"',
            'data-table-column="customer"',
            'data-table-column="purpose"',
            'data-table-column="payment"',
            'data-table-column="status"',
            'data-table-column="reference"',
            'data-table-column="terms"',
            'data-table-column="value"',
            'data-table-column="actions"',
        )
        positions = [header.index(column) for column in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('const columnOrder = [...visibleOrder, ...hiddenOrder, "actions"]', self.script)
        self.assertIn('data-table-column="purpose" class="booking-purpose-cell"', self.script)
        self.assertIn('data-table-column="terms" hidden>${terms}', self.script)
        self.assertIn('localStorage.setItem(BOOKING_COLUMN_STORAGE_KEY', self.script)
        self.assertIn('safe(booking.phone_number || "Phone not available")', self.script)
        self.assertNotIn('booking.customer_email || booking.phone_number', self.script)
        self.assertIn('.status-paid,.status-confirmed {', self.styles)
        self.assertIn('.status-pending,.status-partially_paid,.status-payment_pending {', self.styles)
        self.assertIn('.status-refund_due,.status-cancelled {', self.styles)
        self.assertIn('.status-refunded,.status-void,.status-expired {', self.styles)

    def test_booking_directory_uses_responsive_contained_layout(self) -> None:
        self.assertIn("@media(max-width:1600px){.bookings-section .filters", self.styles)
        self.assertIn("repeat(3,minmax(0,1fr))", self.styles)
        self.assertIn("@media(max-width:1200px){.bookings-section .filters", self.styles)
        self.assertIn("repeat(2,minmax(0,1fr))", self.styles)
        self.assertIn("grid-template-columns:235px minmax(0,1fr)", self.styles)
        self.assertIn(".table-wrap { width:100%; max-width:100%;", self.styles)

    def test_manage_booking_uses_live_reschedule_availability(self) -> None:
        self.assertIn("exclude_booking_id: bookingId", self.script)
        self.assertIn("loadBookingEditAvailability(booking.start_time)", self.script)
        self.assertIn('bookingEditForm.elements.booking_date.addEventListener("change"', self.script)
        self.assertIn('slot.status === "available" && availableHalfHours >= requiredHalfHours', self.script)
        self.assertIn("insufficient time", self.script)
        self.assertIn("isCurrentStart", self.script)
        self.assertIn('" (current booking)"', self.script)
        self.assertIn("currentStartExists ? previous", self.script)
        self.assertIn("canKeepCurrentSchedule", self.script)
        self.assertIn("syncBookingEditPaymentEstimate", self.script)
        self.assertIn('" after studio change"', self.script)
        self.assertIn("configureBookingStudioOptions(booking)", self.script)
        self.assertIn('booking.space_id === "standard_small" && option.value === "premium_large"', self.script)
        self.assertIn('" (downgrade unavailable)"', self.script)
        self.assertIn(".booking-modal select option:disabled", self.styles)

    def test_manage_booking_keeps_identity_duration_and_purpose_read_only(self) -> None:
        self.assertIn('name="duration_display" readonly', self.html)
        self.assertIn('name="duration_hours" type="hidden"', self.html)
        self.assertIn('name="customer_name" maxlength="120" readonly', self.html)
        self.assertIn('name="phone_number" maxlength="32" readonly', self.html)
        self.assertIn('name="purpose" maxlength="1000" readonly', self.html)
        self.assertIn("Number(bookingEditForm.elements.duration_hours.value)", self.script)
        self.assertIn(".booking-modal input[readonly]", self.styles)

    def test_admin_can_open_and_submit_offline_booking_modal(self) -> None:
        self.assertIn('id="add-offline-booking-button"', self.html)
        self.assertIn('id="offline-booking-modal"', self.html)
        self.assertIn('id="offline-booking-form"', self.html)
        self.assertIn('name="total_amount" type="number"', self.html)
        self.assertIn('name="payment_method"', self.html)
        self.assertIn('<input value="Pay at studio" readonly>', self.html)
        self.assertNotIn('name="payment_mode"', self.html)
        self.assertIn('name="terms_accepted" type="checkbox" required', self.html)
        self.assertIn('api("/api/admin/bookings/offline"', self.script)
        self.assertIn('payment_method: data.get("payment_method") || null', self.script)
        self.assertNotIn('payment_mode: data.get("payment_mode")', self.script)
        self.assertIn('terms_accepted: data.has("terms_accepted")', self.script)
        self.assertIn("setupOfflineBookingOptions", self.script)
        self.assertIn("function halfHourOptions(selected = \"\", startIndex = 0, endIndex = 48, showRange = false)", self.script)
        self.assertIn("halfHourOptions(previousStart, openingIndex, latestStartIndex + 1, true)", self.script)
        self.assertIn('showRange ? `${displayTime(value)} - ${displayTime(rangeEnd)}`', self.script)
        self.assertNotIn('offlineBookingForm.elements.booking_date.min', self.script)

    def test_studio_duration_settings_include_one_hour(self) -> None:
        self.assertIn("function durationOptions(selected = 1)", self.script)
        self.assertIn("const value = 1 + (index / 2);", self.script)

    def test_manage_booking_has_no_razorpay_payment_qr_controls(self) -> None:
        self.assertNotIn('id="show-payment-qr-button"', self.html)
        self.assertNotIn('id="payment-qr-modal"', self.html)
        self.assertNotIn("/payment-qr", self.script)

    def test_manage_booking_records_payment_method_before_marking_paid(self) -> None:
        self.assertIn('id="payment-flow"', self.html)
        self.assertIn('id="payment-method"', self.html)
        self.assertIn('id="payment-amount"', self.html)
        self.assertIn('id="payment-history-list"', self.html)
        self.assertIn('booking.payment_method || ""', self.script)
        self.assertIn("PAYMENT_METHODS_BY_FLOW", self.script)
        self.assertIn('["pending", "partially_paid"].includes(booking.payment_status)', self.script)
        self.assertIn("renderPaymentHistory(booking)", self.script)
        self.assertIn('paymentFlow.value = paymentFlowLabel(booking.payment_mode)', self.script)
        self.assertIn("Choose the payment method before marking this booking as paid.", self.script)

    def test_staff_access_hides_owner_controls_and_keeps_exports_and_blocks(self) -> None:
        self.assertIn('id="staff-user-form"', self.html)
        self.assertIn('id="staff-users-list"', self.html)
        self.assertIn('class="settings-nav-group" data-owner-only', self.html)
        self.assertIn('id="settings-menu-toggle" class="section-menu-toggle"', self.html)
        self.assertIn('aria-expanded="false" aria-controls="settings-submenu">Settings</button>', self.html)
        self.assertIn('id="settings-submenu" class="section-submenu" aria-label="Settings submenu" hidden', self.html)
        self.assertIn('href="#staff-access">Staff Access</a>', self.html)
        self.assertIn('href="#studio-catalogue">Studio Catalogue</a>', self.html)
        self.assertNotIn('>i. Staff Access</a>', self.html)
        self.assertNotIn('>ii. Studio Catalogue</a>', self.html)
        self.assertIn('id="staff-access" class="settings-section" data-owner-only', self.html)
        self.assertIn('id="studio-catalogue" class="settings-section" data-owner-only', self.html)
        self.assertNotIn('id="settings" class="settings-section"', self.html)
        self.assertNotIn('href="#settings">Studio settings</a>', self.html)
        self.assertIn('id="add-offline-booking-button" data-owner-only', self.html)
        self.assertIn('id="booking-export" href="/api/admin/bookings/export.csv"', self.html)
        self.assertIn('id="availability-block-form"', self.html)
        self.assertIn('currentAdminRole = session.role === "owner" ? "owner" : "staff"', self.script)
        self.assertIn('document.querySelectorAll("[data-owner-only]")', self.script)
        self.assertIn('SETTINGS_SUBSECTION_IDS = new Set(["staff-access", "studio-catalogue"])', self.script)
        self.assertIn('allowedSections.find((section) => section.id === sectionId)', self.script)
        self.assertIn('settingsMenuToggle.addEventListener("click"', self.script)
        self.assertIn('submenu.hidden = expanded', self.script)
        self.assertNotIn('scrollIntoView({ block: "start", behavior: "auto" })', self.script)
        self.assertIn('.section-submenu {', self.styles)
        self.assertIn('.section-menu-toggle[aria-expanded="true"]::after', self.styles)
        mobile_settings = self.styles.split('@media(max-width:1000px){\n  .admin-shell aside nav {', 1)[1].split("\n}", 1)[0]
        self.assertIn("flex-wrap:wrap", mobile_settings)
        self.assertIn(".section-submenu { position:absolute", mobile_settings)
        self.assertIn("display:grid", mobile_settings)
        self.assertNotIn(".section-submenu{display:flex", mobile_settings)
        self.assertIn('const editable = isOwner() && booking.status === "confirmed";', self.script)

    def test_overview_has_separate_funds_bookings_and_unavailability_pages(self) -> None:
        self.assertIn('id="overview-menu-toggle" class="section-menu-toggle"', self.html)
        self.assertIn('id="overview-submenu" class="section-submenu"', self.html)
        self.assertIn('href="#funds">Funds</a>', self.html)
        self.assertIn('href="#overview-bookings">Bookings</a>', self.html)
        self.assertIn('href="#unavailability">Unavailability</a>', self.html)
        self.assertIn('id="funds" class="overview-section analytics-section"', self.html)
        self.assertIn('id="overview-bookings" class="overview-section analytics-section"', self.html)
        self.assertIn('id="unavailability" class="overview-section analytics-section"', self.html)
        self.assertNotIn('id="overview" class="overview-section"', self.html)
        self.assertIn('name="space_id"><option value="">All Spaces</option>', self.html)
        self.assertIn('<p class="funds-summary-label">OVERALL SUMMARY</p>', self.html)
        self.assertIn('id="funds-month-chart"', self.html)
        self.assertIn('id="funds-year-chart"', self.html)
        self.assertIn('name="month" type="month" required', self.html)
        self.assertIn('name="year" type="number"', self.html)
        self.assertIn('name="day_offset"><option value="-1">Yesterday</option><option value="0" selected>Today</option><option value="1">Tomorrow</option>', self.html)
        self.assertIn('id="overview-bookings-table"', self.html)
        self.assertIn('id="studio-utilisation-chart"', self.html)
        self.assertIn('id="unavailability-chart"', self.html)
        self.assertIn('/api/admin/overview/funds?${query}', self.script)
        self.assertIn('renderFundsMonthChart(overview)', self.script)
        self.assertIn('renderFundsYearChart(overview.yearly_collections)', self.script)
        self.assertIn(': Estimated ${currency.format(item.estimated_amount)}; Collected ${currency.format(collected)}; Pending ${currency.format(item.pending_amount)}`', self.script)
        self.assertIn('class="pending" style="height:${pendingHeight}%;bottom:${collectedHeight}%"', self.script)
        self.assertIn('<span><i class="collected"></i>Collected</span>', self.script)
        self.assertIn('<span><i class="pending"></i>Pending</span>', self.script)
        self.assertIn('fundsOverviewFilters.addEventListener("change"', self.script)
        self.assertIn('/api/admin/overview/bookings?${query}', self.script)
        self.assertIn('/api/admin/overview/unavailability?${new URLSearchParams({ month })}', self.script)
        self.assertIn('OVERVIEW_SUBSECTION_IDS = new Set(["funds", "overview-bookings", "unavailability"])', self.script)
        self.assertIn('navigateToAdminSection("funds")', self.script)
        self.assertIn('.analytics-bars {', self.styles)
        self.assertIn('.analytics-bar-track i {', self.styles)
        self.assertIn('.funds-donut {', self.styles)
        self.assertIn('.funds-year-bars {', self.styles)
        self.assertIn('.funds-year-track i.pending { background:#d8a034; }', self.styles)
        self.assertIn('.funds-year-chart > .analytics-empty { position:absolute; top:50%', self.styles)

    def test_manage_booking_allows_historical_studio_correction(self) -> None:
        self.assertNotIn('bookingEditForm.elements.booking_date.min', self.script)
        self.assertIn('currentInterval.every((candidate) => ["available", "past"].includes(candidate.status))', self.script)
        self.assertIn('originalBooking.booking_date === selectedDate', self.script)
        self.assertIn('originalBooking.start_time === slot.start_time', self.script)

    def test_blocked_tiles_expose_single_slot_unblock_menu(self) -> None:
        self.assertIn('id="slot-context-menu"', self.html)
        self.assertIn('addEventListener("contextmenu"', self.script)
        self.assertIn("/slot?${query}", self.script)
        self.assertIn("Right-click or tap to unblock", self.script)
        self.assertIn("text-decoration:line-through", self.styles)


if __name__ == "__main__":
    unittest.main()
