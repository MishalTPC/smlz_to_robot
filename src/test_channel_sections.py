"""Regression tests for parallel-flange channel geometry in SMLX profiles."""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smlx_reader import SectionDefinition, _properties_from_geometry, _section_dimensions


def _channel(*, mirrored: bool = False, reverse: bool = False,
             name: str = "PFC260X90X35") -> SectionDefinition:
    # Synthetic, square-corner PFC for geometry tests; these 8/12 mm
    # thicknesses are illustrative, not nominal catalogue specifications.
    points = [
        (0.0, 0.0), (0.090, 0.0), (0.090, 0.012),
        (0.008, 0.012), (0.008, 0.248), (0.090, 0.248),
        (0.090, 0.260), (0.0, 0.260),
    ]
    if mirrored:
        points = [(0.090 - y, z) for y, z in points]
    if reverse:
        points.reverse()
    points.append(points[0])
    return SectionDefinition(
        source_id=101, name=name, standard="SA Parallel Flange Channel",
        section_class="C", points=tuple(points),
        bulges=(0.0,) * len(points),
    )


class ChannelSectionTests(unittest.TestCase):
    def test_extract_web_and_flange_thickness(self) -> None:
        for mirrored in (False, True):
            for reverse in (False, True):
                with self.subTest(mirrored=mirrored, reverse=reverse):
                    dims = _section_dimensions(
                        _channel(mirrored=mirrored, reverse=reverse)
                    )
                    self.assertEqual(dims["section_type"], "PFC")
                    self.assertAlmostEqual(dims["h"], 0.260)
                    self.assertAlmostEqual(dims["b"], 0.090)
                    self.assertAlmostEqual(dims["tw"], 0.008)
                    self.assertAlmostEqual(dims["tf"], 0.012)
                    self.assertTrue(math.isnan(dims["t"]))

    def test_cdin_alias_and_parallel_channel_metadata(self) -> None:
        for name in ("CDIN260X90X35", "C260X90X35"):
            with self.subTest(name=name):
                self.assertEqual(_section_dimensions(_channel(name=name))["section_type"], "PFC")

    def test_explicit_pfc_overrides_generic_i_class(self) -> None:
        section = replace(_channel(), section_class="I")
        self.assertEqual(_section_dimensions(section)["section_type"], "PFC")

    def test_rejects_non_channel_polygon(self) -> None:
        rect = SectionDefinition(
            source_id=9, name="PFC_FAULTY", standard="SA_PFC",
            section_class="C",
            points=((0, 0), (.09, 0), (.09, .26), (0, .26), (0, 0)),
            bulges=(0,) * 5,
        )
        with self.assertRaisesRegex(ValueError, "Cannot resolve web/flange geometry"):
            _section_dimensions(rect)

    @unittest.skipUnless(importlib.util.find_spec("sectionproperties"),
                         "sectionproperties is not installed")
    def test_sectionproperties_uses_actual_polygon(self) -> None:
        section = _channel()
        props = _properties_from_geometry(
            section, _section_dimensions(section), mesh_factor=1.0
        )
        expected_area = 2 * 0.090 * 0.012 + 0.008 * (0.260 - 2 * 0.012)
        self.assertAlmostEqual(props["A"], expected_area, delta=1e-8)
        self.assertGreater(props["Iy"], 0)
        self.assertGreater(props["Iz"], 0)
        self.assertGreater(props["J"], 0)


if __name__ == "__main__":
    unittest.main()
