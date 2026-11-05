"""Command-line workflow: Excel workbook -> Robot building unit.

excel_model.py reads/validates the spreadsheet; robot_builder.py handles COM.
Existing function imports are re-exported for backward compatibility.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from excel_model import (WorkbookModel, ImportReport, DEFAULT_WORKBOOK,
                         read_excel_model, evaluate_model)
from robot_builder import (RobotBuilder, GRAVITY, DEFAULT_ROBOT_FILE,
                           material_label_name, section_label_name,
                           create_robot_model)


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