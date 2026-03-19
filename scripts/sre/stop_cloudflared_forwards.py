#!/usr/bin/env python3
"""Primary SRE entrypoint for stopping client-side Cloudflare TCP forwards."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from tunnels_experiment.sre.stop_cloudflared_forwards import main


if __name__ == "__main__":
  raise SystemExit(main())
