"""Offline Robot parametric tube API tests."""
from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from robot_tube import (
    expected_annulus_properties, is_chs, chs_dimensions, check_tube_properties,
    create_parametric_chs,
)


C = SimpleNamespace(
    I_LT_BAR_SECTION=1, I_BST_NS_TUBE=2, I_BSST_USER_TUBE=3,
    I_BSNDV_TUBE_D=4, I_BSNDV_TUBE_T=5,
    I_BSDV_AX=6, I_BSDV_IY=7, I_BSDV_IZ=8, I_BSDV_IX=9,
)

class FakeShape:
    def __init__(self):
        self.values = {}
    def SetValue(self, kind, value):
        self.values[kind] = value

class FakeData:
    def __init__(self):
        self.shape = FakeShape()
        self.calculated = False
        self.MaterialName = None
        self.Type = None
        self.ShapeType = None
        self.props = {}
    def CreateNonstd(self, arg):
        assert arg == 0
        return self.shape
    def CalcNonstdGeometry(self):
        self.calculated = True
        p = expected_annulus_properties(self.shape.values[C.I_BSNDV_TUBE_D], self.shape.values[C.I_BSNDV_TUBE_T])
        self.props = {C.I_BSDV_AX: p['A'], C.I_BSDV_IY: p['Iy'], C.I_BSDV_IZ: p['Iz'], C.I_BSDV_IX: p['J']}
    def GetValue(self, kind):
        return self.props[kind]

class FakeLabels:
    def __init__(self):
        self.entries = {}
    def Create(self, typ, name):
        label = SimpleNamespace(Data=FakeData())
        self.entries[(typ, name)] = label
        return label
    def Store(self, lab):
        pass
    def Get(self, typ, name):
        return self.entries[(typ, name)]

class TubeTests(unittest.TestCase):
    def test_example_1016x4_properties(self):
        props = expected_annulus_properties(.1016, .004)
        self.assertAlmostEqual(props['A'], .001226, places=6)
        self.assertAlmostEqual(props['Iy'], 1.463e-6, delta=1e-9)
        self.assertAlmostEqual(props['J'], 2*props['Iy'])

    def test_is_chs_and_get_dimensions(self):
        row=SimpleNamespace(section_type='CHS',section_name='CHS101.6X4.0',h=.1016,b=.1016,t=.004)
        self.assertTrue(is_chs(row))
        self.assertEqual(chs_dimensions(row),(.1016,.004))
        row.b=.12
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            chs_dimensions(row)

    def test_shape_api_values_and_material(self):
        labels=FakeLabels()
        result=create_parametric_chs(labels,C,'P4_CHS','S275JR',.1016,.004)
        section=labels.Get(C.I_LT_BAR_SECTION,'P4_CHS').Data
        self.assertTrue(section.calculated)
        self.assertEqual(section.Type,C.I_BST_NS_TUBE)
        self.assertEqual(section.ShapeType,C.I_BSST_USER_TUBE)
        self.assertEqual(section.shape.values[C.I_BSNDV_TUBE_D],.1016)
        self.assertEqual(section.shape.values[C.I_BSNDV_TUBE_T],.004)
        self.assertEqual(section.MaterialName,'S275JR')
        self.assertGreater(result['A'],0)

    def test_reject_wrong_solid_or_rectangular_catalogue(self):
        props=expected_annulus_properties(.1016,.004)
        self.assertEqual(len(check_tube_properties(props,.1016,.004)),4)
        props['A'] = math.pi/4*(.1016**2)  # solid bar cannot pass a hollow check
        with self.assertRaisesRegex(ValueError,'Refusing catalogue'):
            check_tube_properties(props,.1016,.004)

    def test_invalid_wall(self):
        for d,t in ((.1,-.001),(.1,0),(.1,.05),(.1,.08),(-.1,.004)):
            with self.subTest(d=d,t=t), self.assertRaises(ValueError):
                expected_annulus_properties(d,t)

if __name__=='__main__':
    unittest.main()