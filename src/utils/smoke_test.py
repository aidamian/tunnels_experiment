"""Validate the machine-readable experiment report."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the smoke test.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.
  """
  parser = argparse.ArgumentParser(description="Validate the latest host-side experiment report.")
  parser.add_argument("--run-ts", required=True, help="specific run identifier to validate")
  return parser.parse_args()


def main() -> int:
  """Wait for and validate the generated experiment report.

  Returns
  -------
  int
    Zero when the report satisfies the expected proof checks, otherwise one.
  """
  args = parse_args()
  repo_root = Path(__file__).resolve().parents[2]
  run_ts = args.run_ts
  report_path = repo_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
  deadline = time.time() + 300
  last_error = "no report observed"

  print(f"waiting for experiment report {report_path}", flush=True)
  while time.time() < deadline:
    if report_path.exists():
      try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
      except json.JSONDecodeError as exc:
        # If another process is still writing the report, give it a moment and
        # retry instead of failing immediately.
        last_error = f"invalid json: {exc}"
        time.sleep(3)
        continue

      postgres_result = payload.get("results", {}).get("postgres_tunnel", {})
      neo4j_bolt_result = payload.get("results", {}).get("neo4j_bolt_tunnel", {})
      neo4j_https_result = payload.get("results", {}).get("neo4j_https", {})
      topology_result = payload.get("topology", {})

      # Keep the validation explicit so it is obvious which claims the
      # experiment must prove before a run is considered healthy.
      checks = [
        payload.get("run_id") == run_ts,
        payload.get("all_ok") is True,
        payload.get("cycles_completed", 0) >= 3,
        postgres_result.get("ok") is True,
        neo4j_bolt_result.get("ok") is True,
        neo4j_https_result.get("ok") is True,
        topology_result.get("top_level_published_ports") == [],
      ]
      if all(checks):
        print("smoke test passed", flush=True)
        print(json.dumps(payload, indent=2), flush=True)
        return 0

      # Keep the full payload text around so timeout output is actionable.
      last_error = json.dumps(payload, indent=2)

    print(f"waiting for healthy experiment report: {last_error}", flush=True)
    time.sleep(5)

  print("smoke test failed", flush=True)
  print(last_error, flush=True)
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
