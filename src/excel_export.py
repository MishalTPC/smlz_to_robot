"""Export linked SMLX model DataFrames to a structured Excel workbook.

The workbook is a snapshot of the import, not an editable source of truth.
Source SI units are preserved. The full DataFrames remain intact in their
corresponding worksheets, with separate normalized section/material views.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import xlsxwriter


# Columns that identify a section regardless of which material it uses.
SECTION_COLUMNS = (
    "smlx_section_id", "section_name", "section_type", "section_standard",
    "h", "b", "tw", "tf", "t",
    "A", "Iy", "Iz", "Iyz", "J", "Iw", "Ay", "Az",
    "centroid_y", "centroid_z", "shear_centre_y", "shear_centre_z",
    "principal_axis_deg", "property_source",
)
MATERIAL_COLUMNS = (
    "smlx_material_id", "material_name", "E", "G", "nu", "fy", "fu", "density",
)
TOPOLOGY_COLUMNS = ("element_id", "node1", "node2", "property_id")

# Keep analysis-oriented section/material properties at the left of the
# Properties worksheet. These four columns are retained for SMLX provenance
# but always written at the far right, in this fixed order.
PROPERTIES_TRAILING_COLUMNS = (
    "section_standard", "material_name",
    "smlx_section_id", "smlx_material_id",
)


def properties_export_view(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a reordered Properties view without changing the source data.

    Other unrecognised columns (including future OpenSees-related fields)
    keep their original order before the SMLX-specific metadata columns.
    """
    columns = [c for c in frame.columns if c not in PROPERTIES_TRAILING_COLUMNS]
    columns.extend(c for c in PROPERTIES_TRAILING_COLUMNS if c in frame.columns)
    return frame.loc[:, columns].copy()


SI_UNITS = {
    "node_id": "-", "node1": "-", "node2": "-", "element_id": "-",
    "property_id": "-", "smlx_member_id": "-", "smlx_section_id": "-",
    "smlx_material_id": "-", "reference_axis": "-",
    "x": "m", "y": "m", "z": "m", "h": "m", "b": "m",
    "t": "m", "tw": "m", "tf": "m",
    "offset_start_x": "m", "offset_start_y": "m",
    "offset_end_x": "m", "offset_end_y": "m",
    "normal_x": "-", "normal_y": "-", "normal_z": "-",
    "A": "m²", "Ay": "m²", "Az": "m²",
    "Iy": "m⁴", "Iz": "m⁴", "Iyz": "m⁴", "J": "m⁴", "Iw": "m⁶",
    "centroid_y": "m", "centroid_z": "m",
    "shear_centre_y": "m", "shear_centre_z": "m",
    "principal_axis_deg": "deg", "E": "Pa", "G": "Pa",
    "nu": "-", "fy": "Pa", "fu": "Pa", "density": "kg/m³",
}

FIELD_NOTES = {
    "node_id": "Unique generated node identifier",
    "node1": "Starting node identifier (Nodes.node_id)",
    "node2": "Ending node identifier (Nodes.node_id)",
    "property_id": "Section/material combination (Properties.property_id)",
    "smlx_section_id": "Original SMLX section reference",
    "smlx_material_id": "Original SMLX material reference",
    "smlx_member_id": "Original member ID from the SMLX document",
    "Iy": "Centroidal inertia about the local section y axis; see README axis convention",
    "Iz": "Centroidal inertia about the local section z axis; see README axis convention",
    "Iyz": "Centroidal product of inertia in the local y-z coordinates",
    "J": "Saint-Venant torsion constant",
    "Iw": "Warping constant",
    "Ay": "Effective shear area in the local y direction",
    "Az": "Effective shear area in the local z direction",
    "nu": "Preserved from SMLX unless user explicitly overrides it",
    "G": "Blank when exported Poisson's ratio is zero and no override is supplied",
    "section_name": "Designation of section in SMLX",
    "property_source": "Origin of section-property values / analysis status",
    "normal_x": "Exported member local normal vector component",
    "normal_y": "Exported member local normal vector component",
    "normal_z": "Exported member local normal vector component",
    "offset_start_x": "Exported member offset; not yet applied to analytical line",
    "offset_start_y": "Exported member offset; not yet applied to analytical line",
    "offset_end_x": "Exported member offset; not yet applied to analytical line",
    "offset_end_y": "Exported member offset; not yet applied to analytical line",
}

# Keep section and material numbers legible: tiny inertias need scientific notation.
_SCIENTIFIC = {"Iy", "Iz", "Iyz", "J", "Iw", "E", "G", "fy", "fu"}
_DECIMAL = {"x", "y", "z", "h", "b", "tw", "tf", "t", "A", "Ay", "Az",
            "centroid_y", "centroid_z", "shear_centre_y", "shear_centre_z",
            "offset_start_x", "offset_start_y", "offset_end_x", "offset_end_y"}
_INTEGER = {"node_id", "node1", "node2", "element_id", "property_id",
            "smlx_member_id", "smlx_section_id", "smlx_material_id", "reference_axis"}


def _validate_frames(nodes: pd.DataFrame, elements: pd.DataFrame,
                     properties: pd.DataFrame) -> None:
    required = (
        (nodes, {"node_id", "x", "y", "z"}, "Nodes"),
        (elements, set(TOPOLOGY_COLUMNS), "Topology"),
        (properties, {"property_id", *SECTION_COLUMNS, *MATERIAL_COLUMNS}, "Properties"),
    )
    for frame, fields, label in required:
        missing = fields.difference(frame.columns)
        if missing:
            raise ValueError(f"{label} DataFrame missing columns: {sorted(missing)}")
        if frame.empty:
            raise ValueError(f"{label} DataFrame is empty")
    if not nodes.node_id.is_unique or not elements.element_id.is_unique:
        raise ValueError("Duplicate node or element IDs in export")
    if not properties.property_id.is_unique:
        raise ValueError("Duplicate property_id in export")
    if not set(elements.node1).issubset(set(nodes.node_id)) or not set(elements.node2).issubset(set(nodes.node_id)):
        raise ValueError("Topology references a node that is missing from Nodes")
    if not set(elements.property_id).issubset(set(properties.property_id)):
        raise ValueError("Topology references a property that is missing from Properties")


def _xlsx_cell(value: Any) -> Any:
    """Convert numpy/pandas scalars and missing values into Excel-safe values."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (ValueError, TypeError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool, datetime)):
        return value
    return str(value)


def _write_data_sheet(workbook: xlsxwriter.Workbook, name: str,
                      frame: pd.DataFrame, formats: dict[str, Any]) -> None:
    sheet = workbook.add_worksheet(name)
    sheet.hide_gridlines(2)
    sheet.set_tab_color("#2563A6" if name in ("Nodes", "Topology", "Properties") else "#61788B")
    sheet.freeze_panes(1, 0)
    sheet.set_row(0, 25)

    headers = [str(c) for c in frame.columns]
    records = [[_xlsx_cell(v) for v in row]
               for row in frame.itertuples(index=False, name=None)]
    columns = []
    for index, field in enumerate(headers):
        column_format = (
            formats["scientific"] if field in _SCIENTIFIC else
            formats["decimal"] if field in _DECIMAL else
            formats["integer"] if field in _INTEGER else
            formats["generic"]
        )
        columns.append({"header": field, "format": column_format})
        # Maintain readable widths without stretching the entire workbook.
        if field in ("section_standard", "property_source", "section_name", "material_name"):
            width = 31 if field in ("section_standard", "property_source") else 22
        elif field in _SCIENTIFIC:
            width = 17
        elif field in _DECIMAL:
            width = 16
        elif field.endswith("_id") or field in ("element_id", "node1", "node2"):
            width = max(14, min(len(field) + 3, 21))
        else:
            width = max(14, min(len(field) + 3, 26))
        sheet.set_column(index, index, width)
    sheet.add_table(0, 0, len(records), len(headers) - 1, {
        "name": "Smlx" + name.replace(" ", ""),
        "style": "Table Style Medium 2",
        "columns": columns,
        "data": records,
    })


def _create_overview(workbook: xlsxwriter.Workbook, source: str | Path | None,
                     nodes: pd.DataFrame, elements: pd.DataFrame,
                     properties: pd.DataFrame, sections: pd.DataFrame,
                     materials: pd.DataFrame) -> None:
    sheet = workbook.add_worksheet("Overview")
    sheet.hide_gridlines(2)
    sheet.set_tab_color("#19466E")
    sheet.set_column("A:A", 28)
    sheet.set_column("B:B", 64)
    title = workbook.add_format({"bold": True, "font_size": 17, "font_color": "#FFFFFF",
                                 "bg_color": "#19466E", "valign": "vcenter"})
    key = workbook.add_format({"bold": True, "font_color": "#19466E"})
    count = workbook.add_format({"bold": True, "num_format": "#,##0"})
    warning = workbook.add_format({"bg_color": "#FEF2E1", "font_color": "#7B4D00",
                                   "text_wrap": True, "valign": "top"})
    sheet.merge_range("A1:B2", "SMLX  |  STRUCTURAL MODEL DATA", title)
    sheet.set_row(0, 24)
    sheet.set_row(1, 20)
    details = [
        ("SMLX input", str(source) if source is not None else "Not supplied"),
        ("Export format", "Excel (.xlsx) / SI units"),
        ("Nodes", len(nodes)),
        ("Elements", len(elements)),
        ("Property assignments", len(properties)),
        ("Unique sections", len(sections)),
        ("Unique materials", len(materials)),
    ]
    for i, (label, value) in enumerate(details, start=3):
        sheet.write(i, 0, label, key)
        sheet.write(i, 1, value, count if isinstance(value, int) else None)
    sheet.write("A13", "Worksheet", key)
    sheet.write("B13", "Contents", key)
    descriptions = [
        ("Nodes", "All generated node IDs and 3D coordinates"),
        ("Topology", "Element/node/property connectivity"),
        ("Elements", "Full element record with SMLX IDs, normals, offsets and role"),
        ("Sections", "Unique profile dimensions and calculated section properties"),
        ("Materials", "Unique material mechanical properties"),
        ("Properties", "Complete section/material property assignments"),
        ("Field Units", "Column units and interpretation"),
    ]
    for i, (label, description) in enumerate(descriptions, start=13):
        sheet.write(i, 0, label)
        sheet.write(i, 1, description)
    sheet.merge_range("A23:B24", "Member coordinates are exported CAD reference lines, not yet a validated analytical Robot model.", warning)
    sheet.merge_range("A26:B27", "Check exported material Poisson ratios: a zero value leaves the shear modulus G blank unless an override is explicitly supplied.", warning)
    sheet.set_row(22, 24)
    sheet.set_row(25, 24)


def export_smlx_workbook(df_nodes: pd.DataFrame, df_elements: pd.DataFrame,
                         df_properties: pd.DataFrame, destination: str | Path,
                         *, source: str | Path | None = None) -> Path:
    """Write one formatted .xlsx workbook containing every imported data field.

    Sheets: Overview, Nodes, Topology, Elements, Sections, Materials,
    Properties and Field Units. Sections/materials are deduplicated by their
    original SMLX IDs; property_id remains the join key for element assignments.
    Missing/uncomputed numerical properties are exported as blank cells.
    The Properties sheet alone places the four SMLX provenance fields last.
    """
    _validate_frames(df_nodes, df_elements, df_properties)
    destination = Path(destination).expanduser()
    if destination.suffix.lower() != ".xlsx":
        raise ValueError(f"Excel destination must end with .xlsx: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    sections = (df_properties.loc[:, list(SECTION_COLUMNS)]
                .drop_duplicates(subset="smlx_section_id")
                .sort_values("smlx_section_id")
                .reset_index(drop=True))
    materials = (df_properties.loc[:, list(MATERIAL_COLUMNS)]
                 .drop_duplicates(subset="smlx_material_id")
                 .sort_values("smlx_material_id")
                 .reset_index(drop=True))
    topology = df_elements.loc[:, list(TOPOLOGY_COLUMNS)].copy()
    properties = properties_export_view(df_properties)
    sheet_data = [
        ("Nodes", df_nodes), ("Topology", topology), ("Elements", df_elements),
        ("Sections", sections), ("Materials", materials), ("Properties", properties),
    ]
    dictionary_rows = [
        {"worksheet": sheet_name, "field": field, "SI_unit": SI_UNITS.get(field, "-"),
         "description": FIELD_NOTES.get(field, "")}
        for sheet_name, frame in sheet_data for field in frame.columns
    ]
    dictionary = pd.DataFrame(dictionary_rows)

    # A new workbook is written atomically by xlsxwriter when it closes.
    with xlsxwriter.Workbook(str(destination), {
        "strings_to_formulas": False, "strings_to_urls": False,
    }) as workbook:
        formats = {
            "scientific": workbook.add_format({"num_format": "0.000000E+00"}),
            "decimal": workbook.add_format({"num_format": "0.000000"}),
            "integer": workbook.add_format({"num_format": "0"}),
            "generic": workbook.add_format({}),
        }
        _create_overview(workbook, source, df_nodes, df_elements,
                         df_properties, sections, materials)
        for name, frame in sheet_data:
            _write_data_sheet(workbook, name, frame, formats)
        _write_data_sheet(workbook, "Field Units", dictionary, formats)
    return destination