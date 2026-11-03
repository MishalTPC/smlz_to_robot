"""Smoke/integrity tests against the example committed to the dev branch.

Run from the repository root: python -m unittest discover -s src -p 'test_*.py' -v
"""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smlx_reader import DEFAULT_SAMPLE, read_smlx


@unittest.skipUnless(DEFAULT_SAMPLE.exists(), "Extracted SMLX example not checked out")
class ActualSMLXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes, cls.elements, cls.props = read_smlx(
            DEFAULT_SAMPLE, calculate_properties=False
        )

    def test_record_counts_and_references(self):
        self.assertEqual(len(self.nodes), 200)
        self.assertEqual(len(self.elements), 212)
        self.assertEqual(len(self.props), 4)
        self.assertEqual(set(self.elements.member_type), {"Beam", "Column"})
        self.assertEqual(self.elements.member_type.value_counts()["Beam"], 208)
        self.assertEqual(self.elements.member_type.value_counts()["Column"], 4)
        self.assertTrue(set(self.elements.node1).issubset(set(self.nodes.node_id)))
        self.assertTrue(set(self.elements.node2).issubset(set(self.nodes.node_id)))
        self.assertTrue(set(self.elements.property_id).issubset(set(self.props.property_id)))
        self.assertEqual(self.elements.smlx_member_id.nunique(), 212)

    def test_cross_section_dimensions(self):
        sections = self.props.set_index("section_name")
        self.assertEqual(set(sections.index), {
            "UB254X146X31", "UC152X152X30", "L60X60X6", "CHS101.6X4.0"
        })
        expected = {
            "UB254X146X31": (0.2515, 0.1461, 0.0060, 0.0086),
            "UC152X152X30": (0.1575, 0.1529, 0.0066, 0.0094),
        }
        for name, (h, b, tw, tf) in expected.items():
            with self.subTest(name=name):
                record = sections.loc[name]
                for field, value in (("h", h), ("b", b), ("tw", tw), ("tf", tf)):
                    self.assertAlmostEqual(record[field], value, places=9)
        angle = sections.loc["L60X60X6"]
        self.assertAlmostEqual(angle.h, 0.06)
        self.assertAlmostEqual(angle.b, 0.06)
        self.assertAlmostEqual(angle.t, 0.006)
        chs = sections.loc["CHS101.6X4.0"]
        self.assertAlmostEqual(chs.h, 0.1016)
        self.assertAlmostEqual(chs.t, 0.004)

    def test_material_metadata_is_not_guessed(self):
        self.assertEqual(set(self.props.material_name), {"S275JR"})
        record = self.props.iloc[0]
        self.assertAlmostEqual(record.E, 210e9)
        self.assertAlmostEqual(record.fy, 275e6)
        self.assertAlmostEqual(record.fu, 430e6)
        self.assertAlmostEqual(record.density, 7850.0)
        self.assertEqual(record.nu, 0.0)
        self.assertTrue(math.isnan(record.G))

    def test_poisson_override_is_explicit(self):
        _, _, props = read_smlx(
            DEFAULT_SAMPLE, calculate_properties=False, poisson_override=0.3
        )
        self.assertTrue(all(abs(v - 0.3) < 1e-12 for v in props.nu))
        self.assertTrue(all(abs(v - 210e9 / 2.6) < 1e-4 for v in props.G))

    @unittest.skipUnless(importlib.util.find_spec("sectionproperties"),
                         "sectionproperties is not installed")
    def test_section_properties_from_mesh(self):
        _, _, props = read_smlx(DEFAULT_SAMPLE, mesh_factor=0.75,
                                poisson_override=0.3)
        for _, record in props.iterrows():
            with self.subTest(section=record.section_name):
                self.assertGreater(record.A, 0)
                self.assertGreater(record.Iy, 0)
                self.assertGreater(record.Iz, 0)
                self.assertGreater(record.J, 0)
                self.assertGreater(record.Ay, 0)
                self.assertGreater(record.Az, 0)
                self.assertGreaterEqual(record.Iw, 0)
        # Exact annulus area, up to the small polygonal approximation of n=96.
        chs = props.set_index("section_name").loc["CHS101.6X4.0"]
        exact_area = math.pi / 4 * (0.1016**2 - 0.0936**2)
        self.assertAlmostEqual(chs.A / exact_area, 1.0, delta=0.005)


if __name__ == "__main__":
    unittest.main()