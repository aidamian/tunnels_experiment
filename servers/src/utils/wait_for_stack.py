"""Wait for the DinD host to publish its topology readiness marker."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from utils.docker_runtime import docker_status
from utils.sdk_logging import build_console_logger, log_message


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the readiness wait helper.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.

  Examples
  --------
  ``python3 servers/src/utils/wait_for_stack.py --run-ts 260320_221836``
  """
  parser = argparse.ArgumentParser(
    description="Wait for the top-level DinD host container to report readiness.",
  )
  parser.add_argument("--run-ts", required=True, help="specific run identifier to wait for")
  parser.add_argument("--timeout-seconds", type=int, default=300)
  return parser.parse_args()


def main() -> int:
  """Wait until the topology-ready marker reports success.

  The helper prints Docker status updates while the DinD host is warming up so
  long first-time pulls and Neo4j initialization still look intentional rather
  than hung.

  Returns
  -------
  int
    Zero when the topology marker reports readiness, otherwise one.

  Examples
  --------
  ``python3 servers/src/utils/wait_for_stack.py --run-ts 260320_221836``
  """
  args = parse_args()
  log = build_console_logger("servers-wait")
  server_root = Path(__file__).resolve().parents[2]
  run_ts = args.run_ts
  ready_path = server_root / "_logs" / "raw" / f"{run_ts}_topology_ready.json"
  deadline = time.time() + args.timeout_seconds

  log_message(log, f"waiting for topology readiness marker {ready_path}", color="cyan")
  while time.time() < deadline:
    if ready_path.exists():
      payload = json.loads(ready_path.read_text(encoding="utf-8"))
      if payload.get("all_ready") is True:
        # The orchestrator writes this marker only after every discovered
        # service script has reported ready.
        log_message(log, "topology is ready", color="green")
        print(json.dumps(payload, indent=2), flush=True)
        return 0

    # Keep emitting progress so first-time image pulls and Neo4j startup delays
    # still look intentional rather than hung.
    log_message(log, f"current top-level container status: {docker_status()}", color="yellow")
    time.sleep(5)

  log_message(log, "timed out waiting for the DinD-host topology", color="red")
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
