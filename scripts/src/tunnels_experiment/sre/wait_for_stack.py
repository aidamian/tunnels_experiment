"""Wait for the DinD host to publish its topology readiness marker."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tunnels_experiment.utils.docker_runtime import docker_status
from tunnels_experiment.utils.envfiles import load_env_file


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the readiness wait helper.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.
  """
  parser = argparse.ArgumentParser(
    description="Wait for the top-level DinD host container to report readiness.",
  )
  parser.add_argument("--run-ts", help="specific run identifier to wait for")
  parser.add_argument("--timeout-seconds", type=int, default=300)
  return parser.parse_args()


def main() -> int:
  """Wait until the topology-ready marker reports success.

  Returns
  -------
  int
    Zero when the topology marker reports readiness, otherwise one.
  """
  args = parse_args()
  repo_root = Path(__file__).resolve().parents[4]
  env = load_env_file(repo_root / ".runtime" / "tunnels.env")
  run_ts = args.run_ts or env["RUN_TS"]
  ready_path = repo_root / "_logs" / "raw" / f"{run_ts}_topology_ready.json"
  deadline = time.time() + args.timeout_seconds

  print(f"waiting for topology readiness marker {ready_path}", flush=True)
  while time.time() < deadline:
    if ready_path.exists():
      payload = json.loads(ready_path.read_text(encoding="utf-8"))
      if payload.get("all_ready") is True:
        # The orchestrator writes this marker only after every discovered
        # service script has reported ready.
        print("topology is ready", flush=True)
        print(json.dumps(payload, indent=2), flush=True)
        return 0

    # Keep emitting progress so first-time image pulls and Neo4j startup delays
    # still look intentional rather than hung.
    print(f"current top-level container status: {docker_status()}", flush=True)
    time.sleep(5)

  print("timed out waiting for the DinD-host topology", flush=True)
  return 1
