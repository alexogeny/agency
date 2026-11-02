from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Tools"))
from sprite_atlas import components, arrange, validate_names


class SpriteTests(unittest.TestCase):
    def test_diagonal_pixels_are_connected_and_transparent_pixels_excluded(self):
        parts = components(bytes([255, 0, 0, 255]), 2, 2, 16)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["pixels"], [0, 3])
        self.assertEqual(parts[0]["bbox"], [0, 0, 2, 2])

    def test_disconnected_components_ordered_by_rows_and_columns(self):
        alpha = bytes([0, 255, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 255, 0])
        parts = components(alpha, 6, 3, 16)
        ordered = arrange(parts, count=4, columns=2, satellite_distance=0)
        self.assertEqual(
            [p["bbox"][:2] for p in ordered], [[1, 0], [4, 0], [1, 2], [4, 2]]
        )

    def test_nearby_satellite_is_assigned_without_copying_adjacent_sprite(self):
        parts = components(bytes([255, 255, 0, 255, 0, 0, 0, 255, 255]), 9, 1, 16)
        ordered = arrange(parts, count=2, columns=2, satellite_distance=2)
        self.assertEqual(ordered[0]["pixels"], [0, 1, 3])
        self.assertEqual(ordered[1]["pixels"], [7, 8])

    def test_insufficient_components_and_invalid_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            arrange([], count=1, columns=1, satellite_distance=0)
        with self.assertRaises(ValueError):
            components(bytes([255]), 2, 2, 16)

    def test_unsafe_duplicate_or_reserved_names_rejected(self):
        for names in [["../outside"], ["x", "x"], ["manifest"], [""], ["/absolute"]]:
            with self.assertRaises(ValueError):
                validate_names(names)
        validate_names(["paper-star", "npc_1"])
