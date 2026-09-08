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

    def test_blocked_tiles_expose_single_slot_unblock_menu(self) -> None:
        self.assertIn('id="slot-context-menu"', self.html)
        self.assertIn('addEventListener("contextmenu"', self.script)
        self.assertIn("/slot?${query}", self.script)
        self.assertIn("Right-click or tap to unblock", self.script)
        self.assertIn("text-decoration:line-through", self.styles)


if __name__ == "__main__":
    unittest.main()
