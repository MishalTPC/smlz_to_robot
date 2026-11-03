"""Build a new Autodesk Robot 3D-frame model from output/smlx_model.xlsx.

A Windows machine with licensed Robot and pywin32 is required for the COM step.
The Excel reader and the preflight checks work without Robot (--dry-run).

IMPORTANT: Imported CAD reference lines are not a verified analytical frame.
Source normals/offsets, Iyz coupling, warping, supports and loads are not
implemented in Robot. If these occur, explicit --allow-approximations is
required; that creates a *review-only* model, not a validated analysis model.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

LOG = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOOK = REPO_ROOT / "output" / "smlx_model.xlsx"
DEFAULT_ROBOT_FILE = REPO_ROOT / "output" / "smlx_from_excel.rtd"
GRAVITY = 9.80665  # m/s^2; Robot.Material.RO is N/m^3, not kg/m^3.
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


def material_label_name(row: pd.Series) -> str:
    return f"SMLX_M{int(row.smlx_material_id)}_{str(row.material_name).strip()}"


def section_label_name(row: pd.Series) -> str:
    return f"SMLX_P{int(row.property_id)}_{str(row.section_name).strip()}"


def _robot_constants() -> tuple[object, object]:
    if sys.platform != "win32":
        raise RuntimeError("Autodesk Robot COM automation runs on Windows only")
    try:
        import win32com.client as win32
    except ImportError as exc:
        raise RuntimeError("Install pywin32 into the Windows Python environment: python -m pip install pywin32") from exc
    try:
        app = win32.gencache.EnsureDispatch("Robot.Application")
    except Exception as exc:
        raise RuntimeError("Cannot launch Autodesk Robot through COM. Open licensed Robot and check registration/makepy.") from exc
    return app, win32.constants


def _create_materials(structure: object, c: object, model: WorkbookModel,
                      *, poisson_override: float | None) -> dict[int, str]:
    label_names: dict[int, str] = {}
    for _, row in model.materials.sort_values("smlx_material_id").iterrows():
        label_name = material_label_name(row)
        lab = structure.Labels.Create(c.I_LT_MATERIAL, label_name)
        data = lab.Data
        nu = float(poisson_override if poisson_override is not None else row.nu)
        data.Type = c.I_MT_STEEL
        data.E = float(row.E)
        data.NU = nu
        data.Kirchoff = float(row.E) / (2.0 * (1.0 + nu))
        data.RO = float(row.density) * GRAVITY
        data.RE = float(row.fy)
        # SMLX fu is retained in Excel. Robot's RT is a design limit,
        # not unambiguously identical to fu, so we do NOT set it silently.
        structure.Labels.Store(lab)
        check = structure.Labels.Get(c.I_LT_MATERIAL, label_name).Data
        for attr, expected in (("E", float(row.E)), ("NU", nu),
                               ("RO", float(row.density) * GRAVITY)):
            observed = float(getattr(check, attr))
            if not math.isclose(observed, expected, rel_tol=1e-7, abs_tol=1e-9):
                raise RuntimeError(f"Robot material {label_name} {attr} readback mismatch")
        label_names[int(row.smlx_material_id)] = label_name
        LOG.info("Created Robot material %s (E=%.4g Pa, RO=%.4g N/m^3)",
                 label_name, float(row.E), float(row.density)*GRAVITY)
    return label_names


def _create_sections(structure: object, c: object, model: WorkbookModel,
                     material_names: dict[int, str]) -> dict[int, str]:
    names: dict[int, str] = {}
    for _, row in model.properties.sort_values("property_id").iterrows():
        name = section_label_name(row)
        label = structure.Labels.Create(c.I_LT_BAR_SECTION, name)
        data = label.Data
        data.Type = c.I_BST_STANDARD
        data.ShapeType = c.I_BSST_UNKNOWN
        data.MaterialName = material_names[int(row.smlx_material_id)]
        # Robot: IX means Saint-Venant torsion, not second moment about X.
        for enum_name, value in (
            ("I_BSDV_AX", row.A), ("I_BSDV_IY", row.Iy),
            ("I_BSDV_IZ", row.Iz), ("I_BSDV_IX", row.J),
            ("I_BSDV_AY", row.Ay), ("I_BSDV_AZ", row.Az),
        ):
            if pd.notna(value):
                data.SetValue(getattr(c, enum_name), float(value))
        structure.Labels.Store(label)
        check = structure.Labels.Get(c.I_LT_BAR_SECTION, name).Data
        for enum_name, expected in (("I_BSDV_AX", row.A),
                                    ("I_BSDV_IY", row.Iy),
                                    ("I_BSDV_IZ", row.Iz),
                                    ("I_BSDV_IX", row.J)):
            observed = float(check.GetValue(getattr(c, enum_name)))
            if not math.isclose(observed, float(expected), rel_tol=1e-5, abs_tol=1e-14):
                raise RuntimeError(f"Robot section {name} {enum_name} readback mismatch")
        names[int(row.property_id)] = name
        LOG.info("Created Robot section %s (A=%.6g m^2)", name, float(row.A))
    return names


def create_robot_model(model: WorkbookModel, *, robot: object | None = None,
                       constants: object | None = None, poisson_override: float | None = None,
                       allow_approximations: bool = False,
                       output: str | Path | None = DEFAULT_ROBOT_FILE,
                       create_new_project: bool = False, overwrite: bool = False) -> ImportReport:
    """Create nodes/bars/labels in a new Robot project; never overwrite silently.

    For unit tests pass fake `robot` and `constants` objects, avoiding Windows COM.
    In normal use `create_new_project` must be True: Project.New could replace
    an unsaved active Robot project, hence this explicit consent requirement.
    """
    report = evaluate_model(model, poisson_override=poisson_override)
    if report.lossy and not allow_approximations:
        raise ValueError("Import would omit analysis-relevant data:\n- " +
                         "\n- ".join(report.lossy) +
                         "\nUse --allow-approximations for a REVIEW-ONLY model and verify it in Robot.")
    if not create_new_project:
        raise ValueError("Creating a new Robot project can replace an unsaved active project: pass --new-project explicitly")
    destination = Path(output).expanduser().resolve() if output is not None else None
    if destination is not None and destination.exists() and not overwrite:
        raise FileExistsError(f"Robot destination exists (will not overwrite): {destination}; use --overwrite if intended")

    if (robot is None) != (constants is None):
        raise ValueError("Provide both robot and constants for an injected test, or neither")
    if robot is None:
        robot, constants = _robot_constants()
    assert constants is not None
    robot.Visible = True
    robot.Interactive = True
    # This is deliberately a *new* project. Never mutate an existing model.
    robot.Project.New(constants.I_PT_FRAME_3D)
    structure = robot.Project.Structure
    for _, row in model.nodes.sort_values("node_id").iterrows():
        structure.Nodes.Create(int(row.node_id), float(row.x), float(row.y), float(row.z))
    mat_names = _create_materials(structure, constants, model, poisson_override=poisson_override)
    sec_names = _create_sections(structure, constants, model, mat_names)
    mat_id_by_prop = {int(row.property_id): int(row.smlx_material_id)
                      for _, row in model.properties.iterrows()}
    for _, row in model.topology.sort_values("element_id").iterrows():
        n = int(row.element_id)
        structure.Bars.Create(n, int(row.node1), int(row.node2))
        bar = structure.Bars.Get(n)
        bar.SetLabel(constants.I_LT_BAR_SECTION, sec_names[int(row.property_id)])
        bar.SetLabel(constants.I_LT_MATERIAL, mat_names[mat_id_by_prop[int(row.property_id)]])
        # NOT assigning Gamma: mapping SMLX normals to Robot local axes
        # has not been established. Does not support end releases/offsets.
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        robot.Project.SaveAs(str(destination))
    # Count verify: throw on mismatch instead of claiming success.
    if int(structure.Nodes.GetAll().Count) != report.nodes:
        raise RuntimeError("Robot node count does not equal Excel node count")
    if int(structure.Bars.GetAll().Count) != report.bars:
        raise RuntimeError("Robot bar count does not equal Excel member count")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Excel model workbook -> Autodesk Robot via pywin32")
    parser.add_argument("workbook", nargs="?", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--dry-run", action="store_true", help="Validate and report; do not connect to Robot")
    parser.add_argument("--new-project", action="store_true", help="Permit Robot.Project.New (replaces active project)")
    parser.add_argument("--allow-approximations", action="store_true",
                        help="Permit loss of unsymmetric coupling and source offsets (review-only model)")
    parser.add_argument("--poisson", type=float, default=None,
                        help="Explicit override of imported Poisson ratio; recalculates G")
    parser.add_argument("--robot-file", type=Path, default=DEFAULT_ROBOT_FILE,
                        help="Destination .rtd (default output/smlx_from_excel.rtd)")
    parser.add_argument("--overwrite", action="store_true", help="Permit overwriting an existing .rtd file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    model = read_excel_model(args.workbook)
    report = evaluate_model(model, poisson_override=args.poisson)
    print(f"Read {report.nodes} nodes, {report.bars} bars, {report.sections} property sets and {report.materials} materials")
    for warning in report.advisory:
        print("NOTE:", warning)
    for warning in report.lossy:
        print("REVIEW WARNING:", warning)
    if args.dry_run:
        print("Dry run complete. Robot was not opened or modified.")
        return
    result = create_robot_model(model, poisson_override=args.poisson,
                                allow_approximations=args.allow_approximations,
                                create_new_project=args.new_project,
                                output=args.robot_file, overwrite=args.overwrite)
    print(f"Saved REVIEW-ONLY Robot model to {Path(args.robot_file).resolve()}")
    print("Verify Robot section axes, eccentricities, connectivity and restraints before analysis.")


if __name__ == "__main__":
    main()