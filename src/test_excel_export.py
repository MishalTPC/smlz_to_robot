"""Checks for the multi-sheet SMLX Excel export (no Robot dependency)."""

import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd

from excel_export import (
    MATERIAL_COLUMNS, SECTION_COLUMNS, PROPERTIES_TRAILING_COLUMNS,
    export_smlx_workbook, properties_export_view,
)


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def fixture():
    nodes = pd.DataFrame([
        {"node_id": 1, "x": 0.0, "y": 0.0, "z": 0.0},
        {"node_id": 2, "x": 5.0, "y": 0.0, "z": 0.0},
        {"node_id": 3, "x": 10.0, "y": 0.0, "z": 0.0},
    ])
    elements = pd.DataFrame([
        {"element_id": 1, "node1": 1, "node2": 2, "property_id": 1,
         "smlx_member_id": 32, "normal_x": 0.0, "member_type": "Beam"},
        {"element_id": 2, "node1": 2, "node2": 3, "property_id": 2,
         "smlx_member_id": 96, "normal_x": 0.0, "member_type": "Column"},
    ])
    baseline = {col: math.nan for col in SECTION_COLUMNS}
    baseline.update({col: math.nan for col in MATERIAL_COLUMNS})
    baseline.update({"section_name": "UB254X146X31", "section_type": "I",
                     "section_standard": "SA_UB", "smlx_section_id": 112,
                     "h": 0.2515, "b": 0.1461, "tw": 0.0060, "tf": 0.0086,
                     "A": 0.00395, "Iy": 3.7e-5, "Iz": 2.6e-6, "J": 1.0e-7,
                     "material_name": "S275JR", "smlx_material_id": 48,
                     "E": 210e9, "G": math.nan, "nu": 0.0, "fy": 275e6,
                     "fu": 430e6, "density": 7850.,
                     "property_source": "test"})
    props = pd.DataFrame([
        {"property_id": 1, **baseline},
        {"property_id": 2, **{**baseline, "material_name": "S355JR",
                              "smlx_material_id": 49, "fy": 355e6}},
    ])
    return nodes, elements, props


class ExcelExportTests(unittest.TestCase):
    def test_all_sheets_and_source_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "smlx_model.xlsx"
            nodes, elements, props = fixture()
            returned = export_smlx_workbook(nodes, elements, props, path, source="sample.smlx")
            self.assertEqual(returned, path)
            with zipfile.ZipFile(path) as z:
                self.assertIsNone(z.testzip())
                root = ET.fromstring(z.read("xl/workbook.xml"))
                sheets = [e.attrib["name"] for e in root.findall("m:sheets/m:sheet", NS)]
                self.assertEqual(sheets, ["Overview", "Nodes", "Topology", "Elements",
                                          "Sections", "Materials", "Properties", "Field Units"])
                # Seven data sheets, Excel table filters on all of them.
                table_files = [n for n in z.namelist() if n.startswith("xl/tables/table") and n.endswith(".xml")]
                self.assertEqual(len(table_files), 7)
                table_info = {}
                for table_file in table_files:
                    table = ET.fromstring(z.read(table_file))
                    columns = [c.attrib["name"] for c in table.findall("m:tableColumns/m:tableColumn", NS)]
                    table_info[table.attrib["name"]] = (table.attrib["ref"], columns)
                self.assertEqual(table_info["SmlxTopology"],
                                 ("A1:D3", ["element_id", "node1", "node2", "property_id"]))
                self.assertEqual(table_info["SmlxSections"][0], "A1:W2")
                self.assertEqual(table_info["SmlxMaterials"][0], "A1:H3")
                property_fields = table_info["SmlxProperties"][1]
                self.assertEqual(property_fields[-4:], list(PROPERTIES_TRAILING_COLUMNS))
                self.assertEqual(
                    property_fields[:-4],
                    [col for col in props.columns if col not in PROPERTIES_TRAILING_COLUMNS],
                )
                self.assertEqual(len(property_fields), len(props.columns))
                self.assertEqual(set(property_fields), set(props.columns))
                self.assertIn("property_source", property_fields)
                self.assertIn("Iyz", property_fields)
                self.assertEqual(
                    table_info["SmlxSections"][1],
                    list(SECTION_COLUMNS),
                )
                self.assertEqual(
                    table_info["SmlxMaterials"][1],
                    list(MATERIAL_COLUMNS),
                )
                self.assertIn("smlx_member_id", table_info["SmlxElements"][1])

    def test_properties_reordering_retains_values_and_input_frame(self):
        _, _, original = fixture()
        before = original.copy(deep=True)
        view = properties_export_view(original)
        self.assertEqual(list(view.columns[-4:]), list(PROPERTIES_TRAILING_COLUMNS))
        self.assertEqual(
            list(view.columns[:-4]),
            [col for col in before.columns if col not in PROPERTIES_TRAILING_COLUMNS],
        )
        pd.testing.assert_frame_equal(original, before)
        pd.testing.assert_frame_equal(
            view.loc[:, original.columns], original,
        )
        self.assertEqual(view.loc[0, "material_name"], "S275JR")
        self.assertEqual(view.loc[1, "smlx_material_id"], 49)

    def test_future_columns_remain_before_smlx_metadata(self):
        _, _, original = fixture()
        original["opensees_section_tag"] = [101, 102]
        view = properties_export_view(original)
        self.assertEqual(
            list(view.columns[-5:]),
            ["opensees_section_tag", *PROPERTIES_TRAILING_COLUMNS],
        )

    def test_invalid_reference_rejected(self):
        nodes, elements, props = fixture()
        elements.at[0, "property_id"] = 999
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "missing from Properties"):
                export_smlx_workbook(nodes, elements, props, Path(temp) / "bad.xlsx")

    def test_missing_numeric_values_not_stringified(self):
        nodes, elements, props = fixture()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "blank.xlsx"
            export_smlx_workbook(nodes, elements, props, path)
            with zipfile.ZipFile(path) as z:
                strings = z.read("xl/sharedStrings.xml").decode("utf-8")
                self.assertNotIn("nan</t>", strings)
                self.assertNotIn("inf</t>", strings)


if __name__ == "__main__":
    unittest.main()