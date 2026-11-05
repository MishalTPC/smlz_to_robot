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

import json
import logging
import math
import sys
from pathlib import Path
import pandas as pd

from excel_model import WorkbookModel, ImportReport, evaluate_model
from robot_section_catalog import (
    DEFAULT_DATABASES, Match, audit_record, get_database_sections,
    load_catalogue_section, match_sections,
)

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
                     material_names: dict[int, str], *,
                     prefs: object | None = None,
                     catalogue_matches: dict[int, Match] | None = None,
                     strict_catalogue: bool = False,
                     audit_rows: list[dict] | None = None) -> dict[int, str]:
    """Create Robot section labels, favouring real South African profiles.

    A requested database match is accepted only when the catalogue family
    and *all* nominal sizes agree. If unavailable, preserve the numerical
    fallback and log it; strict_catalogue rejects all such fallbacks.
    """
    names: dict[int, str] = {}
    for _, row in model.properties.sort_values("property_id").iterrows():
        prop_id = int(row.property_id)
        base_name = section_label_name(row)
        material_name = material_names[int(row.smlx_material_id)]
        match = catalogue_matches.get(prop_id) if catalogue_matches is not None else None
        failed_reason = ""

        if match is not None and match.status == "matched":
            if prefs is None:
                raise ValueError("Robot project preferences required for catalogue import")
            try:
                actual = load_catalogue_section(
                    structure.Labels, c, prefs, base_name, material_name, match,
                )
                names[prop_id] = base_name
                if audit_rows is not None:
                    audit_rows.append(audit_record(
                        prop_id, match, mode="robot_database",
                        robot_props=actual, source_row=row,
                    ))
                LOG.info("Robot database section: %s -> %s [%s]",
                         row.section_name, match.catalogue_name, match.database)
                if audit_rows is not None:
                    differences = audit_rows[-1].get("relative_differences", {})
                    significant = [f"{name}={100 * value:+.1f}%"
                                   for name, value in differences.items()
                                   if value is not None and abs(value) > 0.15]
                    if significant:
                        LOG.warning(
                            "Catalogue and sectionproperties differ for %s: %s. "
                            "Review cross-section axes, profile root radii and dimensions.",
                            row.section_name, ", ".join(significant),
                        )
                continue
            except Exception as exc:
                if strict_catalogue:
                    raise RuntimeError(
                        f"Failed to load Robot catalogue profile {match.catalogue_name!r} "
                        f"from {match.database}: {exc}"
                    ) from exc
                failed_reason = f"Robot database load/readback failed: {exc}"
                LOG.warning("%s; using numerical fallback for %s",
                            failed_reason, row.section_name)
        elif match is not None:
            failed_reason = match.reason or match.status
            if strict_catalogue:
                raise ValueError(
                    f"No unique Robot catalogue profile for {row.section_name!r}: "
                    f"{failed_reason}. Candidates: {list(match.candidates)}"
                )
            LOG.warning("No catalogue match for %s: %s. Using numerical fallback.",
                        row.section_name, failed_reason)

        # Numeric mode is the original behaviour, retained as a fallback and
        # for callers that explicitly select section_source='numeric'.
        name = base_name + "_NUM" if match is not None else base_name
        label = structure.Labels.Create(c.I_LT_BAR_SECTION, name)
        data = label.Data
        data.Type = c.I_BST_STANDARD
        data.ShapeType = c.I_BSST_UNKNOWN
        data.MaterialName = material_name
        for enum_name, value in (
            ("I_BSDV_AX", row.A), ("I_BSDV_IY", row.Iy),
            ("I_BSDV_IZ", row.Iz), ("I_BSDV_IX", row.J),
            ("I_BSDV_AY", row.Ay), ("I_BSDV_AZ", row.Az),
        ):
            if pd.notna(value):
                data.SetValue(getattr(c, enum_name), float(value))
        structure.Labels.Store(label)
        check = structure.Labels.Get(c.I_LT_BAR_SECTION, name).Data
        for enum_name, expected in (
            ("I_BSDV_AX", row.A), ("I_BSDV_IY", row.Iy),
            ("I_BSDV_IZ", row.Iz), ("I_BSDV_IX", row.J),
        ):
            observed = float(check.GetValue(getattr(c, enum_name)))
            if not math.isclose(observed, float(expected), rel_tol=1e-5, abs_tol=1e-14):
                raise RuntimeError(f"Robot section {name} {enum_name} readback mismatch")
        names[prop_id] = name
        if match is not None and audit_rows is not None:
            record = audit_record(prop_id, match, mode="numeric_fallback")
            record["fallback_reason"] = failed_reason
            audit_rows.append(record)
        LOG.info("Created numerical Robot section %s (A=%.6g m^2)",
                 name, float(row.A))
    return names

def create_robot_model(model: WorkbookModel, *, robot: object | None = None,
                       constants: object | None = None, poisson_override: float | None = None,
                       allow_approximations: bool = False,
                       output: str | Path | None = DEFAULT_ROBOT_FILE,
                       create_new_project: bool = False, overwrite: bool = False,
                       section_source: str = "numeric",
                       strict_catalogue: bool = False) -> ImportReport:
    """Create nodes/bars/labels in a new Robot project; never overwrite silently.

    For unit tests pass fake `robot` and `constants` objects, avoiding Windows COM.
    In normal use `create_new_project` must be True: Project.New could replace
    an unsaved active Robot project, hence this explicit consent requirement.
    """
    report = evaluate_model(model, poisson_override=poisson_override)
    if section_source not in ("numeric", "catalogue"):
        raise ValueError("section_source must be 'numeric' or 'catalogue'")
    if strict_catalogue and section_source != "catalogue":
        raise ValueError("strict_catalogue requires section_source='catalogue'")
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
    catalogue_matches: dict[int, Match] | None = None
    catalogue_problems: dict[str, str] = {}
    audit_rows: list[dict] = []
    if section_source == "catalogue":
        entries, catalogue_problems = get_database_sections(
            robot, constants, DEFAULT_DATABASES,
        )
        LOG.info("Robot section database entries found: %d", len(entries))
        for code, issue in catalogue_problems.items():
            LOG.warning("Robot section database %s: %s", code, issue)
        catalogue_matches = {
            int(row.property_id): match_sections(
                str(row.section_name), entries, priority=DEFAULT_DATABASES,
            )
            for _, row in model.properties.iterrows()
        }
        for prop_id, match in catalogue_matches.items():
            if match.status != "matched":
                LOG.warning("Property %s (%s): catalogue %s: %s",
                            prop_id, match.source_name, match.status, match.reason)
        if strict_catalogue:
            missing = [
                f"{item.source_name} ({item.reason})"
                for item in catalogue_matches.values()
                if item.status != "matched"
            ]
            if missing:
                raise ValueError(
                    "Robot catalogue matching failed; no model nodes/bars created: "
                    + "; ".join(missing)
                    + ". Confirm ZA/SADEF are available in Robot Job Preferences."
                )
    for _, row in model.nodes.sort_values("node_id").iterrows():
        structure.Nodes.Create(int(row.node_id), float(row.x), float(row.y), float(row.z))
    mat_names = _create_materials(structure, constants, model, poisson_override=poisson_override)
    sec_names = _create_sections(
        structure, constants, model, mat_names,
        prefs=robot.Project.Preferences if catalogue_matches is not None else None,
        catalogue_matches=catalogue_matches,
        strict_catalogue=strict_catalogue,
        audit_rows=audit_rows,
    )
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
        if section_source == "catalogue":
            # A separate audit never modifies the source Excel workbook.
            report_file = destination.with_suffix(".sections.json")
            summary = {
                "robot_model": str(destination),
                "databases": list(DEFAULT_DATABASES),
                "database_warnings": catalogue_problems,
                "sections": audit_rows,
            }
            try:
                report_file.write_text(
                    json.dumps(summary, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                LOG.info("Saved Robot catalogue section audit to %s", report_file)
            except OSError as exc:
                LOG.warning("Could not save section catalogue audit: %s", exc)
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
                    overwrite: bool = False,
                    section_source: str = "numeric",
                    strict_catalogue: bool = False) -> ImportReport:
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
            section_source=section_source,
            strict_catalogue=strict_catalogue,
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

