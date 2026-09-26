import unittest
from pathlib import Path


class HomeViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[1]
        cls.home_html = (project_root / "app" / "web" / "home.html").read_text(encoding="utf-8")
        cls.booking_html = (project_root / "app" / "web" / "index.html").read_text(encoding="utf-8")
        cls.studio_html = (project_root / "app" / "web" / "studio.html").read_text(encoding="utf-8")
        cls.my_booking_html = (project_root / "app" / "web" / "my_booking.html").read_text(encoding="utf-8")
        cls.home_script = (project_root / "app" / "static" / "home.js").read_text(encoding="utf-8")
        cls.booking_script = (project_root / "app" / "static" / "app.js").read_text(encoding="utf-8")
        cls.studio_script = (project_root / "app" / "static" / "studio.js").read_text(encoding="utf-8")
        cls.my_booking_script = (project_root / "app" / "static" / "my_booking.js").read_text(encoding="utf-8")
        cls.cache_script = (project_root / "app" / "static" / "studio_cache.js").read_text(encoding="utf-8")
        cls.marketing_styles = (project_root / "app" / "static" / "marketing.css").read_text(encoding="utf-8")

    def test_studio_cards_show_all_amenities_in_an_accessible_slider(self) -> None:
        self.assertIn("space.amenities.map", self.home_script)
        self.assertNotIn("space.amenities.slice(0, 5)", self.home_script)
        self.assertNotIn("sort(", self.home_script)
        self.assertIn("data-amenities-carousel", self.home_script)
        self.assertIn("amenities-viewport", self.home_script)
        self.assertNotIn("Show previous", self.home_script)
        self.assertIn("Show more", self.home_script)
        self.assertIn("viewport.scrollBy", self.home_script)
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', self.home_script)
        self.assertNotIn("setInterval", self.home_script)
        self.assertIn(".amenities-viewport", self.marketing_styles)
        self.assertIn("overflow-x:auto", self.marketing_styles)

    def test_home_script_is_cache_versioned(self) -> None:
        self.assertIn("/static/home.js?v=20260914-1", self.home_html)
        self.assertIn("/static/marketing.css?v=20260914-1", self.home_html)

    def test_public_booking_copy_uses_the_one_hour_minimum(self) -> None:
        self.assertIn("Bookings from 1 hour", self.home_html)
        self.assertIn("Every booking must be at least 1 hour.", self.home_html)
        self.assertIn("minimum 1-hour booking", self.booking_html)
        self.assertIn("/static/app.js?v=20260924-1", self.booking_html)

    def test_booking_status_values_use_title_case_labels(self) -> None:
        self.assertIn("/static/my_booking.js?v=20260926-2", self.my_booking_html)
        self.assertIn("function statusLabel(value)", self.my_booking_script)
        self.assertIn("statusLabel(booking.booking_status)", self.my_booking_script)
        self.assertIn("`Payment ${statusLabel(booking.payment_status)}`", self.my_booking_script)

    def test_public_pages_reuse_and_refresh_cached_studio_data(self) -> None:
        cache_asset = "/static/studio_cache.js?v=20260908-1"
        self.assertIn(cache_asset, self.home_html)
        self.assertIn(cache_asset, self.booking_html)
        self.assertIn(cache_asset, self.studio_html)
        self.assertIn("window.localStorage.getItem(storageKey)", self.cache_script)
        self.assertIn("window.YNFStudioCache?.read()", self.home_script)
        self.assertIn("window.YNFStudioCache?.read()", self.booking_script)
        self.assertIn("window.YNFStudioCache?.findBySlug(slug)", self.studio_script)

    def test_contact_section_has_official_details(self) -> None:
        self.assertIn('id="contact"', self.home_html)
        self.assertIn("tel:+917200577341", self.home_html)
        self.assertIn("ynotframezstudios@gmail.com", self.home_html)
        self.assertIn("Survey No 712, 1A1", self.home_html)
        self.assertIn("https://maps.app.goo.gl/k3ZhASzdAr66mNFM6", self.home_html)


if __name__ == "__main__":
    unittest.main()
