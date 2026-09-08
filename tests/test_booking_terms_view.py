import unittest
from pathlib import Path


class BookingTermsViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.booking_html = (cls.project_root / "app" / "web" / "index.html").read_text(encoding="utf-8")
        cls.booking_script = (cls.project_root / "app" / "static" / "app.js").read_text(encoding="utf-8")
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

    def test_make_another_booking_restores_the_studio_selection(self) -> None:
        self.assertIn("function startNewBooking()", self.booking_script)
        self.assertIn('document.querySelector("#confirmation").hidden = true;', self.booking_script)
        self.assertIn("form.hidden = false;", self.booking_script)
        self.assertIn("renderSpaces();", self.booking_script)
        self.assertNotIn(
            'document.querySelector("#new-booking").addEventListener("click", () => window.location.reload())',
            self.booking_script,
        )


if __name__ == "__main__":
    unittest.main()
