"""Unit and fake-Robot integration tests for angle/CHS bending releases.

No installed Autodesk Robot or pywin32 required. Both ends should release
RY/RZ, but NOT RX or any translation. I/UB/UC/channel members remain rigid.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from excel_model import read_excel_model
from robot_builder import create_robot_model
from robot_releases import (
    BENDING_PIN_LABEL, FIXED_DOFS, RELEASED_DOFS,
    assign_bending_pin, create_bending_pin_label, needs_bending_pin,
)
from test_robot_from_excel import C, FakeRobot, make_workbook


class EndReleaseTests(unittest.TestCase):
    def test_classification_from_original_excel_section(self):
        cases = [
            ("CHS", "CHS101.6X4.0", True),
            ("ANGLE", "L60X60X6", True),
            ("ANGLE", "L75X50X6", True),
            ("OTHER", "AE 60X60X6", True),
            ("OTHER", "AU 75X50X6", True),
            ("I", "UB254X146X31", False),
            ("I", "UC152X152X30", False),
            ("PFC", "CDIN 200X75X23", False),
            ("OTHER", "UPN200", False),
        ]
        for kind, name, expected in cases:
            with self.subTest(section=name):
                record = SimpleNamespace(
                    section_type=kind, section_name=name, section_standard="",
                )
                self.assertEqual(needs_bending_pin(record), expected)

    def test_created_release_has_exact_local_dof_pattern_both_ends(self):
        robot = FakeRobot()
        name = create_bending_pin_label(robot.Labels, C)
        self.assertEqual(name, BENDING_PIN_LABEL)
        stored = robot.Labels.Get(C.I_LT_BAR_RELEASE, name).Data
        for side in ("StartNode", "EndNode"):
            end = getattr(stored, side)
            for dof in FIXED_DOFS:
                self.assertEqual(getattr(end, dof), C.I_BERV_NONE)
            for dof in RELEASED_DOFS:
                self.assertEqual(getattr(end, dof), C.I_BERV_STD)

    def test_assigns_end_release_without_removing_other_bar_labels(self):
        robot = FakeRobot()
        robot.Bars.Create(1, 1, 2)
        bar = robot.Bars.Get(1)
        bar.SetLabel(C.I_LT_BAR_SECTION, "SomeSection")
        name = create_bending_pin_label(robot.Labels, C)
        assign_bending_pin(bar, C, name)
        self.assertEqual(bar.labels[C.I_LT_BAR_SECTION], "SomeSection")
        self.assertEqual(bar.labels[C.I_LT_BAR_RELEASE], name)

    def test_builder_applies_release_only_to_angles_and_chs(self):
        cases = [
            ("CHS", "CHS101.6X4.0", True),
            ("ANGLE", "L60X60X6", True),
            ("ANGLE", "L75X50X6", True),
            ("I", "UB254X146X31", False),
            ("I", "UC152X152X30", False),
            ("PFC", "CDIN200X75X23", False),
        ]
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "fixture.xlsx"
            make_workbook(file)
            for kind, name, expected in cases:
                with self.subTest(section=name):
                    model = read_excel_model(file)
                    model.properties.loc[:, "section_type"] = kind
                    model.properties.loc[:, "section_name"] = name
                    robot = FakeRobot()
                    create_robot_model(
                        model, robot=robot, constants=C, output=None,
                        create_new_project=True, section_source="numeric",
                    )
                    bar = robot.Bars.Get(1)
                    self.assertEqual(
                        C.I_LT_BAR_RELEASE in bar.labels, expected,
                    )
                    if expected:
                        self.assertEqual(
                            bar.labels[C.I_LT_BAR_RELEASE],
                            BENDING_PIN_LABEL,
                        )

    def test_builder_uses_property_ids_not_member_name_to_select_release(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "fixture.xlsx"
            make_workbook(file)
            model = read_excel_model(file)
            # Add a second, independent property and member with same nodes.
            # The first bar is CHS; the second one is a UB.
            source = model.properties.iloc[0].copy()
            source["property_id"] = 2
            source["section_type"] = "I"
            source["section_name"] = "UB254X146X31"
            import pandas as pd
            model.properties = pd.concat(
                [model.properties, pd.DataFrame([source])], ignore_index=True,
            )
            top = model.topology.iloc[0].copy()
            top["element_id"] = 2
            top["property_id"] = 2
            model.topology = pd.concat(
                [model.topology, pd.DataFrame([top])], ignore_index=True,
            )
            robot = FakeRobot()
            create_robot_model(
                model, robot=robot, constants=C, output=None,
                create_new_project=True,
            )
            self.assertIn(C.I_LT_BAR_RELEASE, robot.Bars.Get(1).labels)
            self.assertNotIn(C.I_LT_BAR_RELEASE, robot.Bars.Get(2).labels)


if __name__ == "__main__":
    unittest.main()
