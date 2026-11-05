"""Excel model unit: read, cross-check and preflight SMLX workbook data.

No Autodesk Robot or Windows COM dependency. All numeric fields are in SI units.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOOK = REPO_ROOT / "output" / "smlx_model.xlsx"
CORE_TOPOLOGY = ("element_id", "node1", "node2", "property_id")
SECTION_NUMERIC = ("A", "Iy", "Iz", "J", "Ay", "Az")


@dataclass
class WorkbookModel:
    nodes: pd.DataFrame
    topology: pd.DataFrame
    elements: pd.DataFrame
    sections: pd.DataFrame
    materials: pd.DataFrame
    properties: pd.DataFrame


@dataclass(frozen=True)
class ImportReport:
    nodes: int
    bars: int
    sections: int
    materials: int
    advisory: tuple[str, ...]
    lossy: tuple[str, ...]


def _required(frame: pd.DataFrame, columns: tuple[str, ...], sheet: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Worksheet '{sheet}' is missing fields: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"Worksheet '{sheet}' is empty")


def _ids(frame: pd.DataFrame, column: str, sheet: str) -> None:
    values = pd.to_numeric(frame[column], errors="coerce")
    if (values.isna().any() or not (values > 0).all()
            or not (values == values.round()).all()):
        raise ValueError(f"'{sheet}.{column}' must contain positive integer IDs")
    frame[column] = values.astype(int)


def _unique(frame: pd.DataFrame, column: str, sheet: str) -> None:
    if not frame[column].is_unique:
        raise ValueError(f"Duplicate '{column}' values in worksheet '{sheet}'")


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be numeric, got {value!r}") from None
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be {'positive and ' if positive else ''}finite")
    return result


def _close(a: object, b: object) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    return math.isclose(float(a), float(b), rel_tol=1e-7, abs_tol=1e-12)


def _check_repeated_fields(left: pd.DataFrame, right: pd.DataFrame,
                           key: str, fields: tuple[str, ...], left_name: str,
                           right_name: str) -> None:
    other = right.set_index(key)
    for _, row in left.iterrows():
        identifier = int(row[key])
        if identifier not in other.index:
            raise ValueError(f"{left_name} references missing {right_name} key {identifier}")
        matched = other.loc[identifier]
        for field in fields:
            if field in left.columns and field in right.columns and not _close(row[field], matched[field]):
                raise ValueError(f"Conflicting {field} for ID {identifier} between {left_name} and {right_name}")


def read_excel_model(source: str | Path = DEFAULT_WORKBOOK) -> WorkbookModel:
    """Read and cross-check all six model worksheets; ignore cosmetic sheets."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Excel workbook not found: {source}")
    names = ("Nodes", "Topology", "Elements", "Sections", "Materials", "Properties")
    with pd.ExcelFile(source, engine="openpyxl") as xls:
        missing = set(names) - set(xls.sheet_names)
        if missing:
            raise ValueError(f"Missing required Excel worksheets: {sorted(missing)}")
        values = {name: pd.read_excel(xls, sheet_name=name) for name in names}
    model = WorkbookModel(*(values[name] for name in names))

    _required(model.nodes, ("node_id", "x", "y", "z"), "Nodes")
    _required(model.topology, CORE_TOPOLOGY, "Topology")
    _required(model.elements, CORE_TOPOLOGY + ("smlx_member_id",), "Elements")
    _required(model.sections, ("smlx_section_id", "section_name"), "Sections")
    _required(model.materials, ("smlx_material_id", "material_name", "E", "nu", "G", "density", "fy"), "Materials")
    _required(model.properties, ("property_id", "smlx_section_id", "smlx_material_id", "section_name", "material_name", *SECTION_NUMERIC), "Properties")
    for frame, column, name in (
        (model.nodes, "node_id", "Nodes"),
        (model.topology, "element_id", "Topology"),
        (model.topology, "node1", "Topology"),
        (model.topology, "node2", "Topology"),
        (model.topology, "property_id", "Topology"),
        (model.elements, "element_id", "Elements"),
        (model.elements, "node1", "Elements"),
        (model.elements, "node2", "Elements"),
        (model.elements, "property_id", "Elements"),
        (model.properties, "property_id", "Properties"),
        (model.properties, "smlx_section_id", "Properties"),
        (model.properties, "smlx_material_id", "Properties"),
        (model.sections, "smlx_section_id", "Sections"),
        (model.materials, "smlx_material_id", "Materials"),
    ):
        _ids(frame, column, name)
    for frame, key, name in (
        (model.nodes, "node_id", "Nodes"),
        (model.topology, "element_id", "Topology"),
        (model.elements, "element_id", "Elements"),
        (model.properties, "property_id", "Properties"),
        (model.sections, "smlx_section_id", "Sections"),
        (model.materials, "smlx_material_id", "Materials"),
    ):
        _unique(frame, key, name)

    if not set(model.topology.node1).issubset(set(model.nodes.node_id)) or not set(model.topology.node2).issubset(set(model.nodes.node_id)):
        raise ValueError("Topology references node IDs not in Nodes")
    if (model.topology.node1 == model.topology.node2).any():
        raise ValueError("Topology includes zero-length connectivity (same node at both ends)")
    if not set(model.topology.property_id).issubset(set(model.properties.property_id)):
        raise ValueError("Topology refers to undefined property IDs")
    if set(model.topology.element_id) != set(model.elements.element_id):
        raise ValueError("Topology and Elements contain different member IDs")
    _check_repeated_fields(model.topology, model.elements, "element_id", CORE_TOPOLOGY[1:], "Topology", "Elements")
    _check_repeated_fields(model.properties, model.sections, "smlx_section_id",
                           ("section_name", "section_type", "h", "b", "tw", "tf", "t", "A", "Iy", "Iz", "Iyz", "J", "Iw", "Ay", "Az"),
                           "Properties", "Sections")
    _check_repeated_fields(model.properties, model.materials, "smlx_material_id",
                           ("material_name", "E", "G", "nu", "fy", "fu", "density"),
                           "Properties", "Materials")
    for _, node in model.nodes.iterrows():
        for col in ("x", "y", "z"):
            _finite(node[col], f"Nodes[{int(node.node_id)}].{col}")
    coordinates = model.nodes.set_index("node_id")[["x", "y", "z"]]
    for _, member in model.topology.iterrows():
        first = tuple(float(v) for v in coordinates.loc[int(member.node1)])
        second = tuple(float(v) for v in coordinates.loc[int(member.node2)])
        if math.dist(first, second) <= 1e-9:
            raise ValueError(f"Member {int(member.element_id)} has coincident geometric endpoints")
    for _, prop in model.properties.iterrows():
        for col in ("A", "Iy", "Iz", "J"):
            _finite(prop[col], f"Properties[{int(prop.property_id)}].{col}", positive=True)
        for col in ("Ay", "Az"):
            if pd.notna(prop[col]):
                _finite(prop[col], f"Properties[{int(prop.property_id)}].{col}", positive=True)
    return model


def evaluate_model(model: WorkbookModel, *, poisson_override: float | None = None) -> ImportReport:
    """Preflight: identify source fields not representable by a standard Robot bar."""
    if poisson_override is not None and not (0 < poisson_override < 0.5):
        raise ValueError("--poisson must be between 0 and 0.5 (exclusive)")
    advisory: list[str] = [
        "CAD reference lines have not been transformed into analytical centrelines or split at internal intersections.",
        "SMLX member normals/reference_axis are retained in Excel but no Robot bar Gamma is assigned.",
        "No supports, releases, load cases or loads were present in the imported workbook.",
        "Warping constant Iw, shear centre and profile dimensions remain in Excel; numerical Robot bar labels use A/Iy/Iz/J/Ay/Az.",
    ]
    lossy: list[str] = []
    if "Iyz" in model.properties:
        unsym = [str(p.section_name) for _, p in model.properties.iterrows()
                 if pd.notna(p.Iyz) and abs(float(p.Iyz)) > 1e-5 * max(abs(float(p.Iy)), abs(float(p.Iz)))]
        if unsym:
            lossy.append("Nonzero product of inertia Iyz is not transferred (affected sections: " + ", ".join(sorted(set(unsym))) + ").")
    offcols = ("offset_start_x", "offset_start_y", "offset_end_x", "offset_end_y")
    for col in offcols:
        if col in model.elements and pd.to_numeric(model.elements[col], errors="coerce").abs().gt(1e-9).any():
            lossy.append("SMLX member offsets are not applied to Robot (see Elements offset_* columns).")
            break
    for _, material in model.materials.iterrows():
        nu = poisson_override if poisson_override is not None else material.nu
        E = _finite(material.E, f"Materials[{material.material_name}].E", positive=True)
        _finite(material.density, f"Materials[{material.material_name}].density", positive=True)
        _finite(material.fy, f"Materials[{material.material_name}].fy", positive=True)
        nu = _finite(nu, f"Materials[{material.material_name}].nu")
        if not (0 < nu < 0.5):
            raise ValueError(f"Material {material.material_name}: nu={nu!r} is not acceptable for transfer; provide --poisson 0.30 only if approved")
        if poisson_override is None and pd.isna(material.G):
            raise ValueError(f"Material {material.material_name}: G is blank; rerun SMLX exporter with approved --poisson or specify --poisson on this importer")
        if poisson_override is None:
            G = _finite(material.G, f"Materials[{material.material_name}].G", positive=True)
            if not math.isclose(G, E / (2 * (1 + nu)), rel_tol=1e-4):
                raise ValueError(f"Material {material.material_name}: E, G and nu are inconsistent")
    if poisson_override is not None:
        advisory.append(f"Poisson ratio expressly overridden to {poisson_override:g}; G recalculated from E.")
    return ImportReport(len(model.nodes), len(model.topology), len(model.properties),
                        len(model.materials), tuple(advisory), tuple(lossy))


