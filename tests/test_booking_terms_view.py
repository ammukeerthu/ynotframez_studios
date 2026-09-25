import unittest
from pathlib import Path


class BookingTermsViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.booking_html = (cls.project_root / "app" / "web" / "index.html").read_text(encoding="utf-8")
        cls.booking_script = (cls.project_root / "app" / "static" / "app.js").read_text(encoding="utf-8")
        cls.admin_script = (cls.project_root / "app" / "static" / "admin.js").read_text(encoding="utf-8")
        cls.styles = (cls.project_root / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        cls.pdf_path = (
            cls.project_root
            / "app"
            / "static"
            / "legal"
            / "ynotframez-studio-booking-terms.pdf"
        )

    def test_booking_page_links_to_accessible_terms_dialog(self) -> None:
        self.assertIn('id="terms-open"', self.booking_html)
        self.assertIn('id="terms-dialog"', self.booking_html)
        self.assertIn('aria-labelledby="terms-title"', self.booking_html)
        self.assertEqual(self.booking_html.count("data-close-terms"), 2)
        self.assertIn("Open original PDF", self.booking_html)
        self.assertNotIn("VERSION", self.booking_html)

    def test_terms_dialog_has_responsive_interaction(self) -> None:
        self.assertIn("termsDialog.showModal()", self.booking_script)
        self.assertIn("termsDialog.close()", self.booking_script)
        self.assertIn("height: 100dvh", self.styles)

    def test_original_terms_pdf_is_bundled(self) -> None:
        self.assertTrue(self.pdf_path.is_file())
        self.assertTrue(self.pdf_path.read_bytes().startswith(b"%PDF"))

    def test_terms_state_the_one_hour_minimum(self) -> None:
        self.assertIn("The minimum studio booking duration is 1 hour.", self.booking_html)
        self.assertNotIn("The minimum studio booking duration is 2 hours.", self.booking_html)
        self.assertEqual(self.booking_html.count("ynotframez-studio-booking-terms.pdf?v=2"), 2)
        pdf_bytes = self.pdf_path.read_bytes()
        self.assertIn(b"The minimum studio booking duration is 1 hour.", pdf_bytes)
        self.assertNotIn(b"The minimum studio booking duration is 2 hours.", pdf_bytes)

    def test_make_another_booking_restores_the_studio_selection(self) -> None:
        self.assertIn("function startNewBooking()", self.booking_script)
        self.assertIn('document.querySelector("#confirmation").hidden = true;', self.booking_script)
        self.assertIn("form.hidden = false;", self.booking_script)
        self.assertIn("renderSpaces();", self.booking_script)
        self.assertNotIn(
            'document.querySelector("#new-booking").addEventListener("click", () => window.location.reload())',
            self.booking_script,
        )

    def test_half_hour_slots_show_the_complete_interval(self) -> None:
        interval_template = "`${displayTime(slot.start_time)} - ${displayTime(slot.end_time)}`"
        self.assertIn(interval_template, self.booking_script)
        self.assertIn(interval_template, self.admin_script)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", self.styles)

    def test_booking_page_has_an_in_flow_studio_preview(self) -> None:
        self.assertIn('id="selected-space-preview"', self.booking_html)
        self.assertIn('id="studio-preview-dialog"', self.booking_html)
        self.assertIn('id="studio-preview-switcher"', self.booking_html)
        self.assertEqual(self.booking_html.count("data-close-studio-preview"), 2)
        self.assertIn("function openStudioPreview(", self.booking_script)
        self.assertIn("studioPreviewDialog.showModal()", self.booking_script)
        self.assertIn("space.gallery_images", self.booking_script)
        self.assertIn('data-preview-space-id=', self.booking_script)
        self.assertIn('data-preview-switch-space=', self.booking_script)
        self.assertIn(
            "Changing the studio will clear your selected time because availability and pricing may differ.",
            self.booking_script,
        )
        self.assertIn(".studio-preview-dialog", self.styles)
        self.assertIn(".studio-preview-actions", self.styles)


if __name__ == "__main__":
    unittest.main()
