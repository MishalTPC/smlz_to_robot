"""Offline tests: Excel schema, engineering safeguards and fake Robot COM calls."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from robot_from_excel import (GRAVITY, create_robot_model, evaluate_model,
                              read_excel_model)


def make_workbook(path: Path, *, asymmetric: bool = False, offsets: bool = False,
                  missing_poisson: bool = False) -> None:
    nodes = pd.DataFrame([{"node_id": 1, "x": 0., "y": 0., "z": 0.},
                          {"node_id": 2, "x": 3., "y": 0., "z": 0.}])
    topology = pd.DataFrame([{"element_id": 1, "node1": 1, "node2": 2, "property_id": 1}])
    elements = topology.assign(smlx_member_id=32, member_type="Beam",
                               offset_start_x=0.02 if offsets else 0,
                               offset_start_y=0., offset_end_x=0., offset_end_y=0.,
                               normal_x=0., normal_y=0., normal_z=1.)
    standard_section = {"smlx_section_id": 64, "section_name": "TEST_CHS",
                        "section_type": "CHS", "h": .1, "b": .1, "tw": math.nan,
                        "tf": math.nan, "t": .006, "A": 0.0016,
                        "Iy": 1.2e-6, "Iz": 1.2e-6,
                        "Iyz": 2e-7 if asymmetric else 0,
                        "J": 2.4e-6, "Iw": 0., "Ay": .0012, "Az": .0012}
    sections = pd.DataFrame([standard_section])
    material = {"smlx_material_id": 48, "material_name": "S275JR", "E": 210e9,
                "G": math.nan if missing_poisson else 210e9/2.6,
                "nu": 0. if missing_poisson else .3,
                "fy": 275e6, "fu": 430e6, "density": 7850}
    materials = pd.DataFrame([material])
    properties = pd.DataFrame([{"property_id": 1, **standard_section, **material}])
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        for name, table in (("Nodes", nodes), ("Topology", topology),
                            ("Elements", elements), ("Sections", sections),
                            ("Materials", materials), ("Properties", properties)):
            table.to_excel(writer, index=False, sheet_name=name)


class FakeLabel:
    def __init__(self, name):
        self.Name = name
        self.Data = FakeData()


class FakeData:
    def __init__(self):
        self.values = {}

    def SetValue(self, value_type, value):
        self.values[value_type] = value

    def GetValue(self, value_type):
        return self.values[value_type]


class FakeLabels:
    def __init__(self):
        self.stored = {}

    def Create(self, label_type, name):
        label = FakeLabel(name)
        self.stored[(label_type, name)] = label
        return label

    def Store(self, label):
        pass

    def Get(self, label_type, name):
        return self.stored[(label_type, name)]


class FakeNodes:
    def __init__(self):
        self.values = {}

    def Create(self, number, x, y, z):
        self.values[number] = (x, y, z)

    def GetAll(self):
        return SimpleNamespace(Count=len(self.values))


class FakeBar:
    def __init__(self, n, node1, node2):
        self.Number = n
        self.nodes = (node1, node2)
        self.labels = {}

    def SetLabel(self, label_type, name):
        self.labels[label_type] = name


class FakeBars:
    def __init__(self):
        self.values = {}

    def Create(self, n, start, end):
        self.values[n] = FakeBar(n, start, end)

    def Get(self, n):
        return self.values[n]

    def GetAll(self):
        return SimpleNamespace(Count=len(self.values))


class FakeRobot:
    def __init__(self):
        self.Labels = FakeLabels()
        self.Nodes = FakeNodes()
        self.Bars = FakeBars()
        self.Structure = SimpleNamespace(Nodes=self.Nodes, Bars=self.Bars, Labels=self.Labels)
        self.Project = SimpleNamespace(New=MagicMock(), SaveAs=MagicMock(), Structure=self.Structure)


C = SimpleNamespace(I_PT_FRAME_3D=4, I_LT_MATERIAL=1, I_LT_BAR_SECTION=2,
                    I_MT_STEEL=3, I_BST_STANDARD=4, I_BSST_UNKNOWN=5,
                    I_BSDV_AX=6, I_BSDV_IY=7, I_BSDV_IZ=8,
                    I_BSDV_IX=9, I_BSDV_AY=10, I_BSDV_AZ=11)


class ExcelRobotTests(unittest.TestCase):
    def test_read_and_no_robot_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            fn = Path(temp)/"fixture.xlsx"
            make_workbook(fn)
            model = read_excel_model(fn)
            report = evaluate_model(model)
            self.assertEqual((report.nodes, report.bars, report.sections, report.materials), (2, 1, 1, 1))
            self.assertFalse(report.lossy)

    def test_requires_explicit_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            fn = Path(temp)/"fixture.xlsx"
            make_workbook(fn)
            model = read_excel_model(fn)
            with self.assertRaisesRegex(ValueError, "--new-project"):
                create_robot_model(model, robot=FakeRobot(), constants=C, output=None)

    def test_material_density_and_section_inertias(self):
        with tempfile.TemporaryDirectory() as temp:
            fn = Path(temp)/"fixture.xlsx"
            make_workbook(fn)
            model = read_excel_model(fn)
            fake = FakeRobot()
            create_robot_model(model, robot=fake, constants=C, create_new_project=True, output=None)
            fake.Project.New.assert_called_once_with(C.I_PT_FRAME_3D)
            mat = next(v.Data for (typ, _), v in fake.Labels.stored.items() if typ == C.I_LT_MATERIAL)
            self.assertAlmostEqual(mat.RO, 7850 * GRAVITY)
            self.assertAlmostEqual(mat.Kirchoff, 210e9/2.6)
            self.assertAlmostEqual(mat.RE, 275e6)
            section = next(v.Data for (typ, _), v in fake.Labels.stored.items() if typ == C.I_LT_BAR_SECTION)
            self.assertAlmostEqual(section.values[C.I_BSDV_IX], 2.4e-6)
            self.assertAlmostEqual(section.values[C.I_BSDV_IY], 1.2e-6)
            self.assertEqual(fake.Bars.Get(1).nodes, (1, 2))
            self.assertIn(C.I_LT_BAR_SECTION, fake.Bars.Get(1).labels)

    def test_requires_approval_for_asymmetric_and_offset_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            fn = Path(temp)/"fixture.xlsx"
            make_workbook(fn, asymmetric=True, offsets=True)
            model = read_excel_model(fn)
            self.assertEqual(len(evaluate_model(model).lossy), 2)
            with self.assertRaisesRegex(ValueError, "--allow-approximations"):
                create_robot_model(model, robot=FakeRobot(), constants=C,
                                   create_new_project=True, output=None)
            create_robot_model(model, robot=FakeRobot(), constants=C,
                               create_new_project=True, allow_approximations=True,
                               output=None)

    def test_blank_shear_modulus_requires_explicit_poisson_override(self):
        with tempfile.TemporaryDirectory() as temp:
            fn = Path(temp)/"fixture.xlsx"
            make_workbook(fn, missing_poisson=True)
            model = read_excel_model(fn)
            with self.assertRaisesRegex(ValueError, "--poisson"):
                evaluate_model(model)
            report = evaluate_model(model, poisson_override=.3)
            self.assertEqual(report.bars, 1)

    def test_conflicting_topology_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            fn = Path(temp)/"fixture.xlsx"
            make_workbook(fn)
            model = read_excel_model(fn)
            model.topology.loc[0, "node2"] = 1
            with self.assertRaisesRegex(ValueError, "zero-length"):
                # In-memory mutation does not revalidate; the read does.
                # Write back into a second workbook to demonstrate validation.
                with pd.ExcelWriter(Path(temp)/"broken.xlsx", engine="xlsxwriter") as w:
                    for sheet, frame in (("Nodes",model.nodes), ("Topology",model.topology),
                                         ("Elements",model.elements), ("Sections",model.sections),
                                         ("Materials",model.materials), ("Properties",model.properties)):
                        frame.to_excel(w, index=False, sheet_name=sheet)
                read_excel_model(Path(temp)/"broken.xlsx")


if __name__ == "__main__":
    unittest.main()