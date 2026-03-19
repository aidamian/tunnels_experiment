#!/usr/bin/env python3
"""Compatibility wrapper for runtime preparation.

The real implementation now lives under `scripts/src/tunnels_experiment/sre/`
so the repository has clearer separation of concerns. This wrapper keeps the
historical `python3 scripts/prepare_runtime.py` command working.
"""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from tunnels_experiment.sre.prepare_runtime import main


if __name__ == "__main__":
  raise SystemExit(main())
