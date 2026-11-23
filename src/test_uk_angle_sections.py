"""Tests for UK rolled steel equal/unequal-angle SMLX polygons.

These examples are simple square-corner polygons, not assumed manufacturer
catalogue dimensions beyond the nominal height, width, and thickness.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smlx_reader import SectionDefinition, _properties_from_geometry, _section_dimensions


def _uk_angle(name: str = "UK RSEA 100X100X8", *, flip: bool = False,
              reverse: bool = False) -> SectionDefinition:
    points = [(0.0, 0.0), (0.100, 0.0), (0.100, 0.008),
              (0.008, 0.008), (0.008, 0.100), (0.0, 0.100)]
    if flip:
        points = [(0.100 - y, z) for y, z in points]
    if reverse:
        points.reverse()
    points.append(points[0])
    return SectionDefinition(
        source_id=1, name=name, standard="UK Rolled Steel Equal Angle",
        section_class="W", points=tuple(points),
        bulges=(0.0,) * len(points),
    )


class UKRolledAngleTests(unittest.TestCase):
    def test_rsea_thickness_and_geometry(self) -> None:
        for flip in (False, True):
            for reverse in (False, True):
                with self.subTest(flip=flip, reverse=reverse):
                    dims = _section_dimensions(_uk_angle(flip=flip, reverse=reverse))
                    self.assertEqual(dims["section_type"], "ANGLE")
                    self.assertAlmostEqual(dims["b"], 0.100)
                    self.assertAlmostEqual(dims["h"], 0.100)
                    self.assertAlmostEqual(dims["t"], 0.008)

    def test_alias_detected_without_angle_metadata(self) -> None:
        section = _uk_angle()
        section = SectionDefinition(
            source_id=section.source_id, name=section.name,
            standard="", section_class="W", points=section.points,
            bulges=section.bulges,
        )
        self.assertEqual(_section_dimensions(section)["section_type"], "ANGLE")

    @unittest.skipUnless(importlib.util.find_spec("sectionproperties"),
                         "sectionproperties is not installed")
    def test_rsea_sectionproperties(self) -> None:
        section = _uk_angle()
        props = _properties_from_geometry(
            section, _section_dimensions(section), mesh_factor=1.0
        )
        expected_area = 2 * 0.100 * 0.008 - 0.008 * 0.008
        self.assertAlmostEqual(props["A"], expected_area, delta=1e-8)
        self.assertGreater(props["Iy"], 0)
        self.assertGreater(props["Iz"], 0)
        self.assertGreater(props["J"], 0)


if __name__ == "__main__":
    unittest.main()
