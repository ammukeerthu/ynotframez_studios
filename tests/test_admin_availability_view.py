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
        self.assertIn("Minimum block: 30 minutes.", self.html)
        self.assertNotIn("Minimum block: 2 hours.", self.html)
        self.assertIn("const duration = 0.5 + (index / 2);", self.script)
        self.assertIn("30 minutes", self.script)
        self.assertIn(" disabled", self.script)

    def test_admin_block_reason_is_a_fixed_dropdown(self) -> None:
        self.assertIn('<select name="reason" required>', self.html)
        for reason in ("Maintenance", "Power Shutdown", "Technical Issue", "Mandatory Holiday"):
            self.assertIn(f'<option value="{reason}">{reason}</option>', self.html)
        self.assertNotIn('<input name="reason"', self.html)

    def test_dashboard_date_views_open_on_today(self) -> None:
        self.assertIn("availabilityFilters.elements.booking_date.value = localDate();", self.script)
        self.assertIn("bookingFilters.elements.date_from.value = localDate();", self.script)
        self.assertIn("bookingFilters.elements.date_to.value = localDate();", self.script)
        self.assertNotIn("availabilityFilters.elements.booking_date.value = localDate(1);", self.script)

    def test_booking_table_has_purpose_terms_and_persisted_column_controls(self) -> None:
        self.assertIn('data-table-column="purpose">Purpose', self.html)
        self.assertIn('data-table-column="terms">Terms accepted', self.html)
        self.assertIn('value="reference" data-booking-column-toggle checked disabled', self.html)
        self.assertIn('value="actions" data-booking-column-toggle checked disabled', self.html)
        self.assertIn('BOOKING_COLUMN_STORAGE_KEY = "ynf_admin_booking_columns"', self.script)
        self.assertIn('data-table-column="purpose" class="booking-purpose-cell"', self.script)
        self.assertIn('data-table-column="terms">${terms}', self.script)
        self.assertIn('localStorage.setItem(BOOKING_COLUMN_STORAGE_KEY', self.script)

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
        self.assertIn('api("/api/admin/bookings/offline"', self.script)
        self.assertIn("setupOfflineBookingOptions", self.script)
        self.assertNotIn('offlineBookingForm.elements.booking_date.min', self.script)

    def test_manage_booking_has_no_razorpay_payment_qr_controls(self) -> None:
        self.assertNotIn('id="show-payment-qr-button"', self.html)
        self.assertNotIn('id="payment-qr-modal"', self.html)
        self.assertNotIn("/payment-qr", self.script)

    def test_blocked_tiles_expose_single_slot_unblock_menu(self) -> None:
        self.assertIn('id="slot-context-menu"', self.html)
        self.assertIn('addEventListener("contextmenu"', self.script)
        self.assertIn("/slot?${query}", self.script)
        self.assertIn("Right-click or tap to unblock", self.script)
        self.assertIn("text-decoration:line-through", self.styles)


if __name__ == "__main__":
    unittest.main()
