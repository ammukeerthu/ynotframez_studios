import unittest
from pathlib import Path


class HomeViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[1]
        cls.home_html = (project_root / "app" / "web" / "home.html").read_text(encoding="utf-8")
        cls.home_script = (project_root / "app" / "static" / "home.js").read_text(encoding="utf-8")

    def test_studio_cards_show_only_first_five_amenities(self) -> None:
        self.assertIn("space.amenities.slice(0, 5)", self.home_script)
        self.assertNotIn("sort(", self.home_script)

    def test_home_script_is_cache_versioned(self) -> None:
        self.assertIn("/static/home.js?v=20260908-4", self.home_html)

    def test_contact_section_has_official_details(self) -> None:
        self.assertIn('id="contact"', self.home_html)
        self.assertIn("tel:+917200577341", self.home_html)
        self.assertIn("ynotframezstudios@gmail.com", self.home_html)
        self.assertIn("Survey No 712, 1A1", self.home_html)
        self.assertIn("https://maps.app.goo.gl/k3ZhASzdAr66mNFM6", self.home_html)


if __name__ == "__main__":
    unittest.main()
