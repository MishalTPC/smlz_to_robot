"""Catalogue matching regression tests for Robot's South African designations.

These tests use in-memory catalogue names; no Autodesk Robot needed.
"""
from __future__ import annotations

import unittest

from robot_section_catalog import CatalogueEntry, match_sections


class SouthAfricanCatalogueTests(unittest.TestCase):
    def test_equal_and_unequal_angles(self):
        database = [
            CatalogueEntry("ZA", "AE 60x60x6"),
            CatalogueEntry("ZA", "AU 75x50x6"),
        ]
        self.assertEqual(match_sections("L60X60X6", database).catalogue_name, "AE 60x60x6")
        self.assertEqual(match_sections("L75X50X6", database).catalogue_name, "AU 75x50x6")
        self.assertEqual(match_sections("L75X50X6", database).status, "matched")
        self.assertEqual(match_sections("L75X50X6", [database[0]]).status, "unmatched")

    def test_only_parallel_channels_match_cdin(self):
        catalogue = [CatalogueEntry("ZA", "CDIN 200x75x23")]
        self.assertEqual(match_sections("PFC200x75x23", catalogue).status, "matched")
        self.assertEqual(match_sections("C200x75x23", catalogue,
                                        section_standard="SA parallel flange channel").status, "matched")
        self.assertEqual(match_sections("C200x75x23", catalogue).status, "unmatched")
        self.assertEqual(match_sections("UPN200x75x23", catalogue).status, "unmatched")

    def test_chs_rounding_matches_102_not_101(self):
        catalogue = [CatalogueEntry("ZA", "RO 102x4")]
        result = match_sections("CHS101.6X4.0", catalogue)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.catalogue_name, "RO 102x4")
        self.assertIn("Rounded CHS nominal", result.reason)
        self.assertEqual(match_sections("CHS101.6X4.0", [
            CatalogueEntry("ZA", "RO 101x4")]).status, "unmatched")
        self.assertEqual(match_sections("CHS101.6X4.0", [
            CatalogueEntry("ZA", "RO 102x5")]).status, "unmatched")

    def test_exact_preferred_over_rounded_even_in_later_db(self):
        catalogue = [
            CatalogueEntry("ZA", "RO 102x4"),
            CatalogueEntry("SADEF", "CHS 101.6x4"),
        ]
        matched = match_sections("CHS101.6x4", catalogue)
        self.assertEqual(matched.status, "matched")
        self.assertEqual(matched.catalogue_name, "CHS 101.6x4")
        self.assertEqual(matched.database, "SADEF")

    def test_ambiguous_rounding_rejected(self):
        catalogue = [
            CatalogueEntry("ZA", "RO 102x4"),
            CatalogueEntry("ZA", "RK 102x4"),
        ]
        matched = match_sections("CHS101.6x4", catalogue)
        self.assertEqual(matched.status, "ambiguous")
        self.assertEqual(len(matched.candidates), 2)


if __name__ == "__main__":
    unittest.main()