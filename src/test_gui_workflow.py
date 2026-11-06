"""Offline GUI pipeline tests: no Qt, Autodesk Robot, or pywin32 required."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gui_workflow import (
    AUTHOR, ConversionFailure, ConversionRequest,
    run_conversion, suggested_files, validate_request,
)


class GuiWorkflowTests(unittest.TestCase):
    def _paths(self, directory: str) -> tuple[Path, Path, Path]:
        root = Path(directory)
        source = root / "shaft model.smlx"
        source.write_text("dummy contents")
        return source, root / "Robot model.rtd", root / "Robot model.xlsx"

    def test_suggestions_match_source_name(self):
        robot, excel = suggested_files(Path("C:/Models/My Shaft.smlx"))
        self.assertEqual(robot.name, "My Shaft_Robot.rtd")
        self.assertEqual(excel.name, "My Shaft_model.xlsx")

    def test_validation_does_not_overwrite_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source, robot, excel = self._paths(folder)
            request = ConversionRequest(source=source, robot_file=robot, excel_file=excel)
            self.assertEqual(validate_request(request).source, source.resolve())
            excel.touch()
            with self.assertRaises(FileExistsError):
                validate_request(request)
            excel.unlink()
            robot.touch()
            with self.assertRaises(FileExistsError):
                validate_request(request)

    def test_validation_rejects_wrong_extension_and_bad_poisson(self):
        with tempfile.TemporaryDirectory() as folder:
            source, robot, excel = self._paths(folder)
            with self.assertRaisesRegex(ValueError, "Poisson"):
                validate_request(ConversionRequest(source, robot, excel, poisson_for_robot=0))
            with self.assertRaisesRegex(ValueError, ".xlsx"):
                validate_request(ConversionRequest(source, robot, excel.with_suffix(".csv")))
            source = source.with_suffix(".txt")
            source.touch()
            with self.assertRaisesRegex(ValueError, "Select an"):
                validate_request(ConversionRequest(source, robot, excel))

    def test_excel_only_skips_com_and_preserves_original_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source, robot, excel = self._paths(folder)
            events = []
            def parser(*args, **kwargs):
                events.append(("parser", args, kwargs))
                return [1, 2], [1], [1]
            def exporter(*args, **kwargs):
                events.append(("exporter", args, kwargs))
                excel.write_text("mock")
            def unexpected():
                raise AssertionError("Robot must not be launched in Excel-only mode")
            result, app = run_conversion(
                ConversionRequest(source, None, excel, excel_only=True),
                parser=parser, exporter=exporter, robot_connector=unexpected,
            )
            self.assertIsNone(app)
            self.assertIsNone(result.robot_file)
            self.assertEqual(result.nodes, 2)
            self.assertEqual(result.bars, 1)
            self.assertEqual(events[0][0], "parser")
            self.assertEqual(events[0][2], {})  # No Poisson override in Excel.
            self.assertEqual(events[1][0], "exporter")
            self.assertEqual(AUTHOR, "Mishal Mohanlal")

    def test_robot_build_follows_excel_uses_approved_settings_and_retains_app(self):
        with tempfile.TemporaryDirectory() as folder:
            source, robot_file, excel = self._paths(folder)
            events = []
            app = object()
            constants = object()
            def parser(source):
                events.append("parse")
                return [1, 2], [1], [1]
            def exporter(*args, **kwargs):
                events.append("excel")
                excel.write_text("mock")
            def reader(file):
                self.assertTrue(excel.exists())
                events.append("read")
                return "model"
            def connector():
                events.append("connect")
                return app, constants
            def builder(model, **kwargs):
                events.append("build")
                self.assertIs(kwargs["robot"], app)
                self.assertIs(kwargs["constants"], constants)
                self.assertEqual(kwargs["poisson_override"], .3)
                self.assertEqual(kwargs["section_source"], "catalogue")
                self.assertTrue(kwargs["create_new_project"])
                robot_file.write_text("RTD mock")
                return SimpleNamespace(nodes=2, bars=1, sections=1, materials=1)
            result, held = run_conversion(
                ConversionRequest(source, robot_file, excel),
                parser=parser, exporter=exporter, excel_reader=reader,
                robot_connector=connector, robot_builder=builder,
            )
            self.assertEqual(events, ["parse", "excel", "read", "connect", "build"])
            self.assertIs(held, app)
            self.assertEqual(result.robot_file, robot_file.resolve())
            self.assertEqual(result.materials, 1)

    def test_excel_still_exists_when_robot_connection_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            source, robot_file, excel = self._paths(folder)
            def exporter(*args, **kwargs):
                excel.write_text("workbook")
            def fail_connection():
                raise RuntimeError("Autodesk Robot not installed")
            with self.assertRaisesRegex(ConversionFailure, "Excel export completed") as raised:
                run_conversion(
                    ConversionRequest(source, robot_file, excel),
                    parser=lambda _source: ([1], [2], [3]),
                    exporter=exporter,
                    excel_reader=lambda _path: object(),
                    robot_connector=fail_connection,
                )
            self.assertEqual(raised.exception.excel_file, excel.resolve())
            self.assertTrue(excel.exists())


if __name__ == "__main__":
    unittest.main()
