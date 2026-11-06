"""Regression tests for South African Robot section naming conventions."""
from __future__ import annotations

import unittest
from robot_profile_names import profile_key, match_quality, nominal_chs_note


class ProfileNamingTests(unittest.TestCase):
    def test_equal_angle_AE(self):
        source=profile_key('L60X60X6')
        self.assertEqual(source, profile_key('AE 60 x 60 x 6'))
        self.assertEqual(source, profile_key('EA 60*60*6'))
        self.assertEqual(source[0], 'AE')

    def test_unequal_angle_AU(self):
        self.assertEqual(profile_key('L75X50X6'), profile_key('AU 75x50x6'))
        self.assertEqual(profile_key('UA 75 x 50 x 6'), profile_key('AU 75x50x6'))
        self.assertNotEqual(profile_key('AE 75x50x6'), profile_key('L75x50x6'))
        self.assertIsNone(profile_key('AU60x60x6'))
        self.assertIsNone(profile_key('AE75x50x6'))

    def test_parallel_channel_only(self):
        self.assertEqual(profile_key('PFC200X75X23'), profile_key('CDIN 200x75x23'))
        self.assertIsNone(profile_key('UPN200x75x23'))
        self.assertIsNone(profile_key('C200x75x23'))
        self.assertEqual(profile_key('C200x75x23', section_standard='SA parallel flange channel'),
                         profile_key('CDIN200x75x23'))
        self.assertIsNone(profile_key('C200x75x23', section_standard='SA tapered channel'))

    def test_chs_rounding_only_outer_diameter(self):
        src=profile_key('CHS101.6x4.0')
        exact=profile_key('CHS 101.6x4')
        nominal=profile_key('RO 102x4')
        self.assertEqual(match_quality(src,exact), 'exact')
        self.assertEqual(match_quality(src,nominal),'rounded_chs')
        self.assertIn('101.6 mm to 102 mm',nominal_chs_note(src,nominal))
        self.assertIsNone(match_quality(src, profile_key('RO 101x4')))
        self.assertIsNone(match_quality(src, profile_key('RO 102x5')))
        self.assertIsNone(match_quality(src, profile_key('RO 103x4')))
        self.assertIsNone(match_quality(profile_key('UB254x146x31'), profile_key('UB254x146x32')))

    def test_never_round_non_chs(self):
        self.assertIsNone(match_quality(profile_key('L60x60x6'),profile_key('AE61x61x6')))
        self.assertIsNone(match_quality(profile_key('PFC200x75x23'),profile_key('CDIN200x76x23')))

    def test_chs_other_common_nominal_diameters(self):
        for s,c in [('CHS114.3x4','RO114x4'),('CHS88.9x3.2','RO89x3.2'),('CHS48.3x3.2','RO48x3.2')]:
            with self.subTest(s=s):
                self.assertEqual(match_quality(profile_key(s),profile_key(c)),'rounded_chs')


if __name__=='__main__':
    unittest.main()