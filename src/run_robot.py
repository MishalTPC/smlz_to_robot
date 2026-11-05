"""Single-click Excel -> Robot runner. Open this file in VS Code and press F5.

This creates a NEW, REVIEW-ONLY Robot project. Save any open Robot project first.
The sample steel's missing Poisson ratio is explicitly assumed as 0.30 here.
Check this assumption before using the model for engineering analysis.
"""
from __future__ import annotations

from pathlib import Path

from excel_model import read_excel_model
from robot_builder import RobotBuilder, _robot_constants, keep_robot_open_for_review

ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = ROOT / "output" / "smlx_model.xlsx"
ROBOT_FILE = ROOT / "output" / "smlx_from_excel.rtd"

# Settings for the example. Change here instead of passing terminal arguments.
ASSUMED_POISSON = 0.30
REVIEW_ONLY = True
# Search genuine South African steel profiles in ZA (SAISC 2010), then SADEF.
USE_SA_CATALOGUE = True
# False => clearly flagged numerical section fallback where Robot lacks a match.
# True  => stop rather than create any numerical fallback.
STRICT_CATALOGUE = False


def next_unused_path(path: Path) -> Path:
    """Avoid accidentally replacing an earlier Robot model."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def main() -> None:
    model = read_excel_model(WORKBOOK)
    destination = next_unused_path(ROBOT_FILE)
    print("Creating a NEW Robot project from:", WORKBOOK)
    print("Save any currently open Robot model before running this script.")
    # Keep the COM reference in this function's scope. If Robot was
    # launched by Python, releasing the final reference may close it.
    robot, constants = _robot_constants()
    builder = RobotBuilder(robot=robot, constants=constants)
    try:
        report = builder.build_model(
            model,
            create_new_project=True,
            allow_approximations=REVIEW_ONLY,
            poisson_override=ASSUMED_POISSON,
            output=destination,
            section_source="catalogue" if USE_SA_CATALOGUE else "numeric",
            strict_catalogue=STRICT_CATALOGUE,
        )
        print(f"Saved review-only Robot model to: {destination}")
        print(f"Imported {report.nodes} nodes and {report.bars} bars.")
        print("Review connectivity, local axes, offsets, supports and releases before analysis.")
    finally:
        # Also retain the application after a recoverable build exception.
        keep_robot_open_for_review(robot)


if __name__ == "__main__":
    main()
