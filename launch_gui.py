"""Launch the branded Python GUI for SMLX -> Autodesk Robot.

Author: Mishal Mohanlal | Version: 0.1.0

From the repository root:
    python launch_gui.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from smlx_robot_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
