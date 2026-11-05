"""Unit tests for the F5 runner without launching Robot."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from run_robot import next_unused_path


class RunnerTests(unittest.TestCase):
    def test_default_path_if_unused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smlx_from_excel.rtd"
            self.assertEqual(next_unused_path(path), path)

    def test_existing_results_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smlx_from_excel.rtd"
            path.touch()
            (Path(tmp) / "smlx_from_excel_002.rtd").touch()
            self.assertEqual(next_unused_path(path).name, "smlx_from_excel_003.rtd")


if __name__ == "__main__":
    unittest.main()
