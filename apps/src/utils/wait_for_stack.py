"""Wait for the app DinD host to publish its topology readiness marker."""

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


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Wait for dind-host-app to report readiness.")
  parser.add_argument("--run-ts", required=True)
  parser.add_argument("--timeout-seconds", type=int, default=300)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  app_root = Path(__file__).resolve().parents[2]
  ready_path = app_root / "_logs" / "raw" / f"{args.run_ts}_topology_ready.json"
  deadline = time.time() + args.timeout_seconds

  print(f"waiting for app topology readiness marker {ready_path}", flush=True)
  while time.time() < deadline:
    if ready_path.exists():
      payload = json.loads(ready_path.read_text(encoding="utf-8"))
      if payload.get("all_ready") is True:
        print("app topology is ready", flush=True)
        print(json.dumps(payload, indent=2), flush=True)
        return 0

    print(f"current app top-level container status: {docker_status()}", flush=True)
    time.sleep(5)

  print("timed out waiting for the app DinD topology", flush=True)
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
