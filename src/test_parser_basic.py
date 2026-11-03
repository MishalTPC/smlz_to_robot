"""Small self-contained reader tests; no external SMLX fixture required."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smlx_reader import read_smlx


def _field(parent: ET.Element, key: str, value: object, kind: str) -> ET.Element:
    return ET.SubElement(parent, key, {kind: str(value)})


def _wrapped(parent: ET.Element, tag: str, object_class: str) -> ET.Element:
    return ET.SubElement(ET.SubElement(parent, tag, {"class": object_class}), "Members")


def _object_metadata(obj: ET.Element, object_id: int) -> None:
    metadata = _wrapped(obj, "Object", "CGREXObject")
    _field(metadata, "m_nID", object_id, "long")


def _reference(parent: ET.Element, tag: str, ref: int) -> None:
    members = _wrapped(parent, tag, "CGREXObjectReference")
    _field(members, "m_nID", ref, "long")


def _vector(parent: ET.Element, tag: str, xyz: tuple[float, float, float]) -> None:
    members = _wrapped(parent, tag, "CGREXGeometryPoint")
    for field, value in zip(("m_dfX", "m_dfY", "m_dfZ"), xyz):
        _field(members, field, value, "double")


def _fixture() -> bytes:
    root = ET.Element("Document")
    material = ET.SubElement(root, "Object", {"class": "CGREXMaterial"})
    _object_metadata(material, 48)
    material_fields = ET.SubElement(material, "Members")
    for name, value in {
        "m_strName": "S275JR", "m_dfYoung": 210e9, "m_dfPoisson": 0,
        "m_dfFy": 275e6, "m_dfFu": 430e6, "m_dfDensity": 7850,
    }.items():
        _field(material_fields, name, value, "string" if isinstance(value, str) else "double")

    section = ET.SubElement(root, "Object", {"class": "CGREXSection"})
    _object_metadata(section, 64)
    section_fields = ET.SubElement(section, "Members")
    for name, value in {
        "m_strName": "L60X60X6", "m_strStandard": "SA Angle equal", "m_strClass": "W"
    }.items():
        _field(section_fields, name, value, "string")
    # A proper equal-angle polygon in SMLX local y/z, including the closure point.
    polygon = [(-.0169, .0431), (-.0169, -.0169), (.0431, -.0169),
               (.0431, -.0109), (-.0109, -.0109), (-.0109, .0431),
               (-.0169, .0431)]
    for index, (y, z) in enumerate(polygon):
        _vector(section_fields, f"m_tabGeometryPoints_{index}", (0, y, z))
        _field(section_fields, f"m_tabBulges_{index}", 0, "double")
    for member_id, a, b in [
        (32, (0, 0, 0), (1, 0, 0)),
        (96, (1 + 2e-7, 0, 0), (2, 0, 0)),
    ]:
        member = ET.SubElement(root, "Object", {"class": "CGREXBeam"})
        line = ET.SubElement(member, "Object", {"class": "CGREXLine"})
        cg_member = ET.SubElement(line, "Object", {"class": "CGREXMember"})
        _object_metadata(cg_member, member_id)
        member_fields = ET.SubElement(cg_member, "Members")
        _field(member_fields, "m_strRole", "Beam", "string")
        _reference(member_fields, "m_pMaterial", 48)
        line_fields = ET.SubElement(line, "Members")
        _reference(line_fields, "m_pSectionStart", 64)
        _reference(line_fields, "m_pSectionEnd", 64)
        _vector(line_fields, "m_pCADStart", a)
        _vector(line_fields, "m_pCADEnd", b)
        _vector(line_fields, "m_pNormal", (0, 0, 1))
        for field in ("m_vecOffsetStartX", "m_vecOffsetStartY", "m_vecOffsetEndX", "m_vecOffsetEndY"):
            _field(line_fields, field, 0, "double")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class ReaderTest(unittest.TestCase):
    def test_parse_linked_dataframes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            xml_path = Path(folder) / "model.xml"
            xml_path.write_bytes(_fixture())
            nodes, elements, props = read_smlx(xml_path, calculate_properties=False)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(len(elements), 2)
        self.assertEqual(len(props), 1)
        self.assertEqual(elements.node1.tolist(), [1, 2])
        self.assertEqual(elements.node2.tolist(), [2, 3])
        self.assertEqual(elements.smlx_member_id.tolist(), [32, 96])
        self.assertEqual(elements.property_id.tolist(), [1, 1])
        self.assertAlmostEqual(props.iloc[0].t, .006)
        self.assertTrue(math.isnan(props.iloc[0].A))
        self.assertTrue(math.isnan(props.iloc[0].G))

    def test_poisson_override(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            xml_path = Path(folder) / "model.xml"
            xml_path.write_bytes(_fixture())
            _, _, props = read_smlx(xml_path, calculate_properties=False, poisson_override=.3)
        self.assertAlmostEqual(props.iloc[0].G, 210e9 / 2.6)


if __name__ == "__main__":
    unittest.main()