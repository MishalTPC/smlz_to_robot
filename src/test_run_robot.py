"""Unit tests for the F5 runner without launching Robot."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from run_robot import next_unused_path
from robot_builder import keep_robot_open_for_review


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

    def test_keep_open_prompts_while_com_reference_is_held(self):
        robot = object()
        seen = []
        def fake_prompt(message):
            seen.append((message, robot))
            return ""
        keep_robot_open_for_review(robot, prompt_fn=fake_prompt)
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0][1], robot)
        self.assertIn("Press Enter", seen[0][0])

    def test_keep_open_accepts_missing_terminal(self):
        def fake_prompt(message):
            raise EOFError()
        keep_robot_open_for_review(object(), prompt_fn=fake_prompt)


if __name__ == "__main__":
    unittest.main()
