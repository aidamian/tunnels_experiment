"""Run the app-host bridge as a long-lived foreground daemon."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from bridge.universal import UniversalBridgeServer


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Run a persistent local bridge inside dind-host-app.")
  parser.add_argument("--name", required=True)
  parser.add_argument("--hostname", required=True)
  parser.add_argument("--local-port", required=True, type=int)
  parser.add_argument("--run-ts", required=True)
  parser.add_argument("--raw-logs-dir", required=True)
  parser.add_argument("--log-color", default="green")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  raw_logs_dir = Path(args.raw_logs_dir)

  with UniversalBridgeServer(
    name=args.name,
    hostname=args.hostname,
    local_port=args.local_port,
    run_ts=args.run_ts,
    raw_logs_dir=raw_logs_dir,
    log_color=args.log_color,
  ) as bridge:
    while True:
      bridge.raise_if_failed()
      time.sleep(1)


if __name__ == "__main__":
  raise SystemExit(main())
