import re
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.routes.bookings import _require_public_booking_enabled
from app.core.config import Settings, settings
from app.main import booking_page


class PublicBookingGateTests(unittest.TestCase):
    def test_public_booking_is_safe_by_default(self) -> None:
        self.assertFalse(Settings.model_fields["public_booking_enabled"].default)

    def test_render_preserves_dashboard_managed_booking_gate(self) -> None:
        manifest = Path(__file__).resolve().parents[1] / "render.yaml"
        content = manifest.read_text(encoding="utf-8")
        self.assertRegex(
            content,
            r"- key: PUBLIC_BOOKING_ENABLED\s+sync: false",
        )

    def test_disabled_booking_uses_maintenance_page(self) -> None:
        with patch.object(settings, "public_booking_enabled", False):
            response = booking_page()
        self.assertTrue(str(response.path).endswith("maintenance.html"))

    def test_enabled_booking_uses_booking_flow(self) -> None:
        with patch.object(settings, "public_booking_enabled", True):
            response = booking_page()
        self.assertTrue(str(response.path).endswith("index.html"))

    def test_disabled_gate_rejects_direct_booking_creation(self) -> None:
        with patch.object(settings, "public_booking_enabled", False):
            with self.assertRaises(HTTPException) as context:
                _require_public_booking_enabled()
        self.assertEqual(context.exception.status_code, 503)

    def test_maintenance_page_has_contact_path_and_no_booking_form(self) -> None:
        page = Path(__file__).resolve().parents[1] / "app" / "web" / "maintenance.html"
        content = page.read_text(encoding="utf-8")
        self.assertIn("We are under", content)
        self.assertIn("mailto:ynotframezstudios@gmail.com", content)
        self.assertIn("tel:+917200577341", content)
        self.assertIn("Survey No 712, 1A1", content)
        self.assertIn("https://maps.app.goo.gl/k3ZhASzdAr66mNFM6", content)
        self.assertNotIn("booking-form", content)


if __name__ == "__main__":
    unittest.main()
