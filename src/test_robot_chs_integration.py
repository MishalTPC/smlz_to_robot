"""End-to-end Robot CHS catalogue/fallback tests using offline fake COM objects.

These tests intentionally simulate catalogue names containing RO instead of CHS,
and an unavailable catalogue profile. No real Robot installation is required.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from excel_model import read_excel_model
from robot_builder import create_robot_model
from robot_section_catalog import CatalogueEntry, match_sections
from robot_tube import expected_annulus_properties
from test_robot_from_excel import C, FakeData, FakeLabel, FakeLabels, FakeRobot, make_workbook
from test_robot_section_catalog import FakeDbList

CC = SimpleNamespace(
    **vars(C),
    I_DT_SECTIONS=22,
    I_BST_NS_TUBE=30,
    I_BSST_USER_TUBE=31,
    I_BSNDV_TUBE_D=32,
    I_BSNDV_TUBE_T=33,
)


class _Dimensions:
    def __init__(self):
        self.values = {}
    def SetValue(self, k, v):
        self.values[k] = v


class _SectionData(FakeData):
    def __init__(self, wrong_catalogue=False):
        super().__init__()
        self.shape = _Dimensions()
        self.wrong_catalogue = wrong_catalogue
    def CreateNonstd(self, selector):
        assert selector == 0
        return self.shape
    def CalcNonstdGeometry(self):
        exact = expected_annulus_properties(
            self.shape.values[CC.I_BSNDV_TUBE_D],
            self.shape.values[CC.I_BSNDV_TUBE_T],
        )
        self.values.update({
            CC.I_BSDV_AX: exact['A'], CC.I_BSDV_IY: exact['Iy'],
            CC.I_BSDV_IZ: exact['Iz'], CC.I_BSDV_IX: exact['J'],
        })
    def LoadFromDBase2(self, name, database):
        if (name, database) != ('RO 101.6x4', 'ZA'):
            raise ValueError(f'Unexpected database profile {name} [{database}]')
        exact = expected_annulus_properties(.1016, .004)
        self.values.update({
            CC.I_BSDV_AX: exact['A'], CC.I_BSDV_IY: exact['Iy'],
            CC.I_BSDV_IZ: exact['Iz'], CC.I_BSDV_IX: exact['J'],
        })
        if self.wrong_catalogue:
            # The same nominal numbers actually describe a non-hollow shape.
            self.values[CC.I_BSDV_AX] = .008107


class _SectionLabels(FakeLabels):
    def __init__(self, wrong_catalogue=False):
        super().__init__()
        self.wrong_catalogue = wrong_catalogue
    def Create(self, typ, name):
        label = FakeLabel(name)
        label.Data = _SectionData(wrong_catalogue=self.wrong_catalogue)
        self.stored[(typ, name)] = label
        return label


def _ready_model(path):
    make_workbook(path)
    model = read_excel_model(path)
    exact = expected_annulus_properties(.1016, .004)
    for frame in (model.properties, model.sections):
        frame.loc[:, 'section_name'] = 'CHS101.6X4.0'
        frame.loc[:, 'section_type'] = 'CHS'
        frame.loc[:, 'h'] = .1016
        frame.loc[:, 'b'] = .1016
        frame.loc[:, 't'] = .004
        for k, v in exact.items():
            frame.loc[:, k] = v
    return model


def _robot(profile_names, *, wrong_catalogue=False):
    robot = FakeRobot()
    robot.Labels = _SectionLabels(wrong_catalogue=wrong_catalogue)
    robot.Structure.Labels = robot.Labels
    active = FakeDbList()
    active.names['ZA']._names = profile_names
    active.names['SADEF']._names = []
    robot.Project.Preferences = SimpleNamespace(
        SectionsActive=active, SetCurrentDatabase=lambda *args: None,
    )
    return robot


class RobotCHSIntegrationTests(unittest.TestCase):
    def test_catalogue_ro_alias_is_shortlisted_by_exact_dimensions(self):
        found = match_sections('CHS101.6X4.0', [
            CatalogueEntry('ZA', 'RO 101.6x4'),
        ])
        self.assertEqual((found.status, found.catalogue_name),
                         ('matched', 'RO 101.6x4'))
        missed = match_sections('CHS101.6X4.0', [
            CatalogueEntry('ZA', 'RO 114.3x4'),
        ])
        self.assertEqual(missed.status, 'unmatched')

    def test_unmatched_chs_is_renderable_parametric_tube(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = _ready_model(root / 'input.xlsx')
            robot = _robot([])
            out = root / 'sample.rtd'
            report = create_robot_model(model, robot=robot, constants=CC,
                                        section_source='catalogue',
                                        create_new_project=True, output=out)
            self.assertEqual(report.bars, 1)
            label = robot.Bars.Get(1).labels[CC.I_LT_BAR_SECTION]
            self.assertTrue(label.endswith('_TUBE'), label)
            data = robot.Labels.Get(CC.I_LT_BAR_SECTION, label).Data
            self.assertEqual(data.Type, CC.I_BST_NS_TUBE)
            self.assertEqual(data.ShapeType, CC.I_BSST_USER_TUBE)
            self.assertEqual(data.shape.values[CC.I_BSNDV_TUBE_D], .1016)
            self.assertEqual(data.shape.values[CC.I_BSNDV_TUBE_T], .004)
            audit = json.loads(out.with_suffix('.sections.json').read_text())
            self.assertEqual(audit['sections'][0]['assignment'], 'parametric_tube')

    def test_valid_ro_catalogue_uses_robot_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = _ready_model(root / 'input.xlsx')
            robot = _robot(['RO 101.6x4'])
            out = root / 'sample.rtd'
            create_robot_model(model, robot=robot, constants=CC,
                               section_source='catalogue',
                               create_new_project=True, output=out)
            name = robot.Bars.Get(1).labels[CC.I_LT_BAR_SECTION]
            self.assertFalse(name.endswith('_TUBE'))
            audit = json.loads(out.with_suffix('.sections.json').read_text())
            self.assertEqual(audit['sections'][0]['assignment'], 'robot_database')

    def test_solid_lookalike_is_rejected_for_parametric_tube(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = _ready_model(root / 'input.xlsx')
            robot = _robot(['RO 101.6x4'], wrong_catalogue=True)
            out = root / 'sample.rtd'
            create_robot_model(model, robot=robot, constants=CC,
                               section_source='catalogue',
                               create_new_project=True, output=out)
            name = robot.Bars.Get(1).labels[CC.I_LT_BAR_SECTION]
            self.assertTrue(name.endswith('_TUBE'))
            audit = json.loads(out.with_suffix('.sections.json').read_text())
            self.assertIn('not a verified CHS',audit['sections'][0]['fallback_reason'])


if __name__ == '__main__':
    unittest.main()