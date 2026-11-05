"""Robot-building unit (Pascal-style unit, implemented in Python).

Owns Robot COM connection, project creation, material/section labels,
nodes, bars, property assignment, result checks and RTD saving.

Does not open Excel. Call this module with a validated WorkbookModel from
excel_model.py. Imports safely on non-Windows systems; pywin32 is loaded
only when an actual Robot model is being built.

IMPORTANT: This builds a REVIEW-ONLY model. SMLX CAD offsets, member Gamma,
Iyz coupling, releases, supports and loads are not translated.
"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
import pandas as pd

from excel_model import WorkbookModel, ImportReport, evaluate_model

LOG = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROBOT_FILE = REPO_ROOT / "output" / "smlx_from_excel.rtd"
GRAVITY = 9.80665  # Convert mass density kg/m^3 to Robot unit weight N/m^3.


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



class RobotBuilder:
    """Reusable Robot model-building interface, analogous to a Pascal unit.

    A Robot/constant pair can be injected for testing. No COM connection is
    created until build_model is called and engineering preflight has passed.

    Example:
        model = read_excel_model("output/smlx_model.xlsx")
        builder = RobotBuilder()
        builder.build_model(model, create_new_project=True,
                            allow_approximations=True,
                            poisson_override=0.30)
    """

    def __init__(self, *, robot: object | None = None,
                 constants: object | None = None) -> None:
        if (robot is None) != (constants is None):
            raise ValueError("Provide both robot and constants, or neither")
        self.robot = robot
        self.constants = constants

    def build_model(self, model: WorkbookModel, *,
                    poisson_override: float | None = None,
                    allow_approximations: bool = False,
                    output: str | Path | None = DEFAULT_ROBOT_FILE,
                    create_new_project: bool = False,
                    overwrite: bool = False) -> ImportReport:
        """Create the review-only Robot model from an already-loaded model."""
        return create_robot_model(
            model,
            robot=self.robot,
            constants=self.constants,
            poisson_override=poisson_override,
            allow_approximations=allow_approximations,
            output=output,
            create_new_project=create_new_project,
            overwrite=overwrite,
        )

def keep_robot_open_for_review(robot: object, *, prompt_fn=None) -> None:
    """Keep a live COM application reference until the user finishes review.

    The script may be the only COM client keeping an auto-launched Robot
    instance alive. This pause is intentional for interactive VS Code runs.
    Inject prompt_fn for offline tests. EOF (non-interactive runs) is safe.
    """
    if robot is None:
        raise ValueError("Robot application reference is required")
    if prompt_fn is None:
        prompt_fn = input
    try:
        prompt_fn(
            "\nRobot model is available. Inspect it now. "
            "Press Enter in this terminal when finished (Robot may then close): "
        )
    except EOFError:
        print("No interactive console; reopen the saved .rtd file in Robot if needed.")

