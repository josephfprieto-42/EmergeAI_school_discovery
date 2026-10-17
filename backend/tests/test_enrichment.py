import sys
import unittest
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))

from program_themes import themes_for_program  # noqa: E402
from app.services.zones import point_in_rings  # noqa: E402


class ThemeTests(unittest.TestCase):
    def test_official_title_only(self):
        themes = themes_for_program("International Baccalaureate/International Studies - Spanish", "magnet")
        self.assertIn("language", themes)
        self.assertIn("gifted", themes)
        self.assertIn("magnet", themes)

    def test_plain_name_is_not_a_program(self):
        self.assertEqual(themes_for_program("Coral Reef Senior High", None), [])


class PointInPolygonTests(unittest.TestCase):
    def test_square_and_hole(self):
        square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        hole = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
        self.assertTrue(point_in_rings(-80.2, 25.8, [[[-80.3, 25.7], [-80.1, 25.7], [-80.1, 25.9], [-80.3, 25.9], [-80.3, 25.7]]]))
        self.assertFalse(point_in_rings(3, 3, [square]))
        self.assertTrue(point_in_rings(0.2, 0.2, [square]))
        self.assertFalse(point_in_rings(1, 1, [square, hole]))


if __name__ == "__main__":
    unittest.main()
