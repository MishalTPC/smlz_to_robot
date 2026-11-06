"""Reusable SMLX -> Excel -> Autodesk Robot workflow for the desktop GUI.

Author: Mishal Mohanlal | Version: 0.1.0

No GUI imports and no Robot COM work occur at module-import time. The Excel
workbook is deliberately generated first using the unmodified SMLX values;
any approved Poisson override is supplied only to the subsequent Robot build.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

AUTHOR = "Mishal Mohanlal"
VERSION = "0.1.0"
APP_NAME = "SMLX to Robot"
SMLX_FILE_TYPES = frozenset({".smlx", ".smlz", ".zip", ".xml"})


@dataclass(frozen=True)
class ConversionRequest:
    source: Path
    robot_file: Path | None
    excel_file: Path
    excel_only: bool = False
    poisson_for_robot: float = 0.30
    use_sa_catalogue: bool = True
    allow_review_approximations: bool = True


@dataclass(frozen=True)
class ConversionResult:
    excel_file: Path
    robot_file: Path | None
    nodes: int
    bars: int
    sections: int
    materials: int


class ConversionFailure(RuntimeError):
    """Retain the Excel location when a later Robot operation fails."""
    def __init__(self, message: str, *, excel_file: Path):
        super().__init__(message)
        self.excel_file = excel_file


def suggested_files(source: str | Path) -> tuple[Path, Path]:
    """Suggest separate Robot and Excel output paths next to the SMLX input."""
    source = Path(source).expanduser()
    root = source.parent
    stem = source.stem if source.suffix else source.name
    stem = stem.strip() or "model"
    robot = root / f"{stem}_Robot.rtd"
    return robot, root / f"{stem}_model.xlsx"


def validate_request(request: ConversionRequest) -> ConversionRequest:
    source = Path(request.source).expanduser().resolve()
    excel = Path(request.excel_file).expanduser().resolve()
    robot = (Path(request.robot_file).expanduser().resolve()
             if request.robot_file is not None else None)
    if not source.exists():
        raise FileNotFoundError(f"SMLX input does not exist: {source}")
    if source.is_file() and source.suffix.lower() not in SMLX_FILE_TYPES:
        raise ValueError("Select an .smlx, .smlz, .zip, .xml file, or an extracted SMLX folder")
    if not source.is_file() and not source.is_dir():
        raise ValueError("SMLX input must be a file or extracted folder")
    if excel.suffix.lower() != ".xlsx":
        raise ValueError("Excel output must be an .xlsx file")
    if excel.exists():
        raise FileExistsError(f"Excel output already exists. Choose a new filename: {excel}")
    if source == excel:
        raise ValueError("Excel output cannot overwrite the SMLX input")
    if not request.excel_only:
        if robot is None or robot.suffix.lower() != ".rtd":
            raise ValueError("Select a Robot output filename ending in .rtd")
        if robot.exists():
            raise FileExistsError(f"Robot model already exists. Choose a new filename: {robot}")
        if robot == source or robot == excel:
            raise ValueError("Robot, Excel and input paths must be different")
        if not 0 < request.poisson_for_robot < 0.5:
            raise ValueError("Robot Poisson ratio must be strictly between 0 and 0.5")
    return ConversionRequest(
        source=source, excel_file=excel, robot_file=robot,
        excel_only=request.excel_only,
        poisson_for_robot=request.poisson_for_robot,
        use_sa_catalogue=request.use_sa_catalogue,
        allow_review_approximations=request.allow_review_approximations,
    )


def run_conversion(
    request: ConversionRequest, *,
    progress: Callable[[str], None] | None = None,
    parser: Callable[..., tuple[Any, Any, Any]] | None = None,
    exporter: Callable[..., Path] | None = None,
    excel_reader: Callable[..., Any] | None = None,
    robot_connector: Callable[..., tuple[Any, Any]] | None = None,
    robot_builder: Callable[..., Any] | None = None,
) -> tuple[ConversionResult, Any | None]:
    """Generate the full workbook, then optionally the Robot model.

    Return (result, live_robot_com_reference). Keep this reference alive in the
    caller while Robot is being inspected; dropping the final COM reference
    can close an application instance that Python launched.

    Dependencies are injectable to allow fast offline tests without Autodesk.
    """
    req = validate_request(request)
    notify = progress or (lambda _message: None)
    if parser is None:
        from smlx_reader import read_smlx as parser
    if exporter is None:
        from excel_export import export_smlx_workbook as exporter

    notify("Reading SMLX geometry and calculating section properties...")
    # Preserve original source Poisson ratio and all calculated source values.
    nodes, elements, properties = parser(req.source)
    req.excel_file.parent.mkdir(parents=True, exist_ok=True)
    notify("Writing complete Excel workbook (including Properties worksheet)...")
    exporter(nodes, elements, properties, req.excel_file, source=req.source)
    notify(f"Excel saved: {req.excel_file}")

    if req.excel_only:
        section_count = (int(properties["smlx_section_id"].nunique())
                         if hasattr(properties, "columns") and
                         "smlx_section_id" in properties.columns else len(properties))
        material_count = (int(properties["smlx_material_id"].nunique())
                          if hasattr(properties, "columns") and
                          "smlx_material_id" in properties.columns else len(properties))
        return (ConversionResult(
            excel_file=req.excel_file, robot_file=None,
            nodes=len(nodes), bars=len(elements),
            sections=section_count, materials=material_count,
        ), None)

    try:
        if excel_reader is None:
            from excel_model import read_excel_model as excel_reader
        if robot_connector is None:
            from robot_builder import _robot_constants as robot_connector
        if robot_builder is None:
            from robot_builder import create_robot_model as robot_builder
        notify("Validating Excel model and connecting to Autodesk Robot...")
        model = excel_reader(req.excel_file)
        robot, constants = robot_connector()
        notify("Building Robot model with SA sections and member releases...")
        report = robot_builder(
            model, robot=robot, constants=constants,
            poisson_override=req.poisson_for_robot,
            allow_approximations=req.allow_review_approximations,
            create_new_project=True,
            section_source="catalogue" if req.use_sa_catalogue else "numeric",
            strict_catalogue=False,
            output=req.robot_file, overwrite=False,
        )
    except Exception as exc:
        raise ConversionFailure(
            f"Excel export completed at:\n{req.excel_file}\n\n"
            f"Robot model creation failed: {exc}",
            excel_file=req.excel_file,
        ) from exc

    notify(f"Robot saved: {req.robot_file}")
    return (ConversionResult(
        excel_file=req.excel_file, robot_file=req.robot_file,
        nodes=report.nodes, bars=report.bars,
        sections=report.sections, materials=report.materials,
    ), robot)
