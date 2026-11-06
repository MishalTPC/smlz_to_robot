"""Offline integration contract for loading a named SA catalogue profile."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from excel_model import read_excel_model
from robot_builder import create_robot_model
from test_robot_from_excel import C, FakeRobot, FakeData, FakeLabel, FakeLabels, make_workbook
from test_robot_section_catalog import FakeDbList
from robot_tube import expected_annulus_properties


class CatalogueData(FakeData):
    def LoadFromDBase2(self, name, database):
        if (name, database) != ("CHS 101.6x4", "SADEF"):
            raise ValueError("Unexpected catalogue selection")
        exact = expected_annulus_properties(.1016, .004)
        self.values[C.I_BSDV_AX] = exact["A"]
        self.values[C.I_BSDV_IY] = exact["Iy"]
        self.values[C.I_BSDV_IZ] = exact["Iz"]
        self.values[C.I_BSDV_IX] = exact["J"]


class CatalogueLabelServer(FakeLabels):
    def Create(self, label_type, name):
        label = FakeLabel(name)
        label.Data = CatalogueData()
        self.stored[(label_type, name)] = label
        return label


class CatalogueIntegrationTests(unittest.TestCase):
    def test_builder_uses_database_profile_instead_of_numeric_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.xlsx"
            make_workbook(path)
            model = read_excel_model(path)
            model.properties.loc[:, "section_name"] = "CHS101.6X4"
            model.sections.loc[:, "section_name"] = "CHS101.6X4"
            # The base mock is 100x6; ensure its dimensions and mechanical
            # properties actually describe the intended 101.6x4 tube.
            exact = expected_annulus_properties(.1016, .004)
            for frame in (model.properties, model.sections):
                frame.loc[:, "h"] = .1016
                frame.loc[:, "b"] = .1016
                frame.loc[:, "t"] = .004
                for key, value in exact.items():
                    frame.loc[:, key] = value
            robot = FakeRobot()
            robot.Labels = CatalogueLabelServer()
            robot.Structure.Labels = robot.Labels
            prefs = SimpleNamespace(SectionsActive=FakeDbList(),
                                    SetCurrentDatabase=lambda *args: None)
            robot.Project.Preferences = prefs
            constants = SimpleNamespace(**vars(C), I_DT_SECTIONS=22)
            report = create_robot_model(model, robot=robot, constants=constants,
                                        create_new_project=True, output=None,
                                        section_source="catalogue", strict_catalogue=True)
            self.assertEqual(report.bars, 1)
            selected = robot.Bars.Get(1).labels[constants.I_LT_BAR_SECTION]
            section = robot.Labels.Get(constants.I_LT_BAR_SECTION, selected).Data
            self.assertAlmostEqual(
                section.values[constants.I_BSDV_AX], exact["A"],
            )
            self.assertFalse(selected.endswith("_NUM"))


if __name__ == "__main__":
    unittest.main()