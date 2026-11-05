"""Offline section matching and Robot catalogue API fakes."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from robot_section_catalog import (
    CatalogueEntry, match_sections, get_database_sections,
    load_catalogue_section, compare_geometry,
)


class FakeNames:
    def __init__(self, names):
        self.names = names
        self.Count = len(names)
    def Get(self, i):
        return self.names[i - 1]


class FakeDb:
    def __init__(self, name, names):
        self.Name = name
        self._names = names
    def GetAll(self):
        return FakeNames(self._names)


class FakeDbList:
    def __init__(self):
        self.names = {"ZA": FakeDb("ZA", ["UB 254x146x31", "UC 152x152x30", "EA 60x60x6"]),
                      "SADEF": FakeDb("SADEF", ["CHS 101.6x4"])}
        self.active = []
    @property
    def Count(self):
        return len(self.active)
    def GetDatabase(self, i):
        return self.active[i - 1]
    def Add(self, name):
        if name not in self.names:
            return False
        self.active.append(self.names[name])
        return True


class FakeData:
    def __init__(self):
        self.values = {}
        self.MaterialName = ""
    def LoadFromDBase2(self, name, database):
        self.values = {11: 0.003919, 12: 4.3e-5, 13: 4.1e-6, 14: 1.1e-7}
    def GetValue(self, enum):
        return self.values[enum]


class FakeLabels:
    def __init__(self):
        self.labels = {}
    def Create(self, typ, name):
        label = SimpleNamespace(Data=FakeData())
        self.labels[(typ, name)] = label
        return label
    def Store(self, lab):
        return None
    def Get(self, typ, name):
        return self.labels[(typ, name)]


class SectionCatalogueTests(unittest.TestCase):
    def test_four_sample_sections(self):
        catalog = [CatalogueEntry("ZA", "UB 254x146x31"),
                   CatalogueEntry("ZA", "UC152x152x30"),
                   CatalogueEntry("ZA", "EA 60X60X6"),
                   CatalogueEntry("SADEF", "CHS 101.6x4")]
        cases = {"UB254X146X31": "UB 254x146x31",
                 "UC152X152X30": "UC152x152x30",
                 "L60X60X6": "EA 60X60X6",
                 "CHS101.6X4.0": "CHS 101.6x4"}
        for source, expected in cases.items():
            with self.subTest(source=source):
                result = match_sections(source, catalog)
                self.assertEqual(result.status, "matched")
                self.assertEqual(result.catalogue_name, expected)

    def test_does_not_select_nearest_different_size(self):
        result = match_sections("UB254X146X31", [CatalogueEntry("ZA", "UB 254x146x37")])
        self.assertEqual(result.status, "unmatched")

    def test_ambiguous_names_not_automatically_selected(self):
        result = match_sections("L60x60x6", [CatalogueEntry("ZA", "EA 60x60x6"),
                                              CatalogueEntry("ZA", "L60X60X6")])
        self.assertEqual(result.status, "ambiguous")

    def test_first_database_has_precedence(self):
        result = match_sections("CHS101.6X4", [CatalogueEntry("SADEF", "CHS 101.6x4"),
                                                CatalogueEntry("ZA", "CHS 101.6x4")])
        self.assertEqual(result.database, "ZA")

    def test_database_scan(self):
        dbs = FakeDbList()
        robot = SimpleNamespace(Project=SimpleNamespace(Preferences=SimpleNamespace(SectionsActive=dbs)))
        entries, errors = get_database_sections(robot, SimpleNamespace())
        self.assertFalse(errors)
        self.assertEqual(len(entries), 4)
        self.assertEqual(set(d.database for d in entries), {"ZA", "SADEF"})

    def test_real_catalogue_label_path(self):
        labels = FakeLabels()
        prefs = SimpleNamespace(SetCurrentDatabase=lambda *args: None)
        constants = SimpleNamespace(I_DT_SECTIONS=2, I_LT_BAR_SECTION=3, I_BSDV_AX=11,
                                    I_BSDV_IY=12, I_BSDV_IZ=13, I_BSDV_IX=14)
        match = match_sections("UB254X146X31", [CatalogueEntry("ZA", "UB 254x146x31")])
        results = load_catalogue_section(labels, constants, prefs, "SMLX_P1", "Steel", match)
        self.assertAlmostEqual(results["A"], 0.003919)
        self.assertEqual(labels.Get(3, "SMLX_P1").Data.MaterialName, "Steel")
        comp = compare_geometry({"A": 0.003919, "Iy": 4.3e-5,
                                 "Iz": 4.1e-6, "J": 1.1e-7}, results)
        self.assertAlmostEqual(comp["A_relative_difference"], 0)


if __name__ == "__main__":
    unittest.main()