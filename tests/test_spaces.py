import unittest

from app.services.spaces import get_space_by_slug


class StudioSpaceTest(unittest.TestCase):
    def test_public_slug_returns_rich_studio_details(self) -> None:
        space = get_space_by_slug("standard-studio")

        self.assertIsNotNone(space)
        self.assertEqual(space.id, "standard_small")
        self.assertGreaterEqual(len(space.equipment) + len(space.amenities), 4)
        self.assertIn("Maternity Shoot", space.booking_purposes)
        self.assertTrue(space.cover_image.startswith("https://images.unsplash.com/"))

    def test_unknown_slug_returns_none(self) -> None:
        self.assertIsNone(get_space_by_slug("not-a-studio"))

    def test_old_public_slug_remains_compatible(self) -> None:
        space = get_space_by_slug("standard-small-space")

        self.assertIsNotNone(space)
        self.assertEqual(space.slug, "standard-studio")


if __name__ == "__main__":
    unittest.main()
