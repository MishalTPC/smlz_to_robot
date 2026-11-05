"""Tests for direct import/use of the Pascal-style robot_builder unit."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from excel_model import read_excel_model
from robot_builder import RobotBuilder
from test_robot_from_excel import C, FakeRobot, make_workbook


class RobotBuilderUnitTests(unittest.TestCase):
    def test_unit_builds_a_frame_from_data_model(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "sample.xlsx"
            make_workbook(file)
            model = read_excel_model(file)
            fake = FakeRobot()
            builder = RobotBuilder(robot=fake, constants=C)
            report = builder.build_model(
                model, output=None, create_new_project=True,
            )
            self.assertEqual((report.nodes, report.bars), (2, 1))
            fake.Project.New.assert_called_once_with(C.I_PT_FRAME_3D)
            self.assertEqual(fake.Bars.Get(1).nodes, (1, 2))
            fake.Project.SaveAs.assert_not_called()

    def test_rejects_partial_fake_com_injection(self):
        with self.assertRaisesRegex(ValueError, "both robot and constants"):
            RobotBuilder(robot=FakeRobot())

    def test_does_not_modify_robot_before_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "sample.xlsx"
            make_workbook(file, offsets=True)
            model = read_excel_model(file)
            fake = FakeRobot()
            builder = RobotBuilder(robot=fake, constants=C)
            with self.assertRaisesRegex(ValueError, "--allow-approximations"):
                builder.build_model(model, output=None, create_new_project=True)
            fake.Project.New.assert_not_called()


if __name__ == "__main__":
    unittest.main()
