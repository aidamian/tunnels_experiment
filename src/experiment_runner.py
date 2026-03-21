"""Run the host-side end-to-end proof workload.

This module coordinates the host-side local TCP bridges, PostgreSQL proof
queries, Neo4j Bolt proof queries, and direct Neo4j HTTPS reads. The actual
database-specific checks live in dedicated modules so concerns remain separate.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bridge.universal import LOCALHOST, UniversalBridgeServer
from simulators.neo4j_bolt import run_neo4j_bolt_cycle
from simulators.neo4j_https import run_neo4j_https_read
from simulators.postgres import run_postgres_cycle
from utils.demo_config import (
  DEFAULT_EXPERIMENT_CYCLE_INTERVAL_SECONDS,
  DEFAULT_EXPERIMENT_DURATION_SECONDS,
  HOST_NEO4J_BOLT_FORWARD_PORT,
  HOST_POSTGRES_FORWARD_PORT,
)
from utils.docker_runtime import top_level_published_ports
from utils.envfiles import load_public_hosts_file
from utils.files import write_json_file
from utils.topology import load_topology_snapshot


def now_utc() -> str:
  """Return the current UTC timestamp in ISO 8601 format.

  This helper keeps report timestamps consistent across the coordinator and its
  output artifacts.

  Returns
  -------
  str
    Current UTC timestamp.

  Examples
  --------
  >>> now_utc().endswith("+00:00")
  True
  """
  return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the host-side experiment.

  Returns a namespace describing which run identifier should be used and, when
  requested, which timing defaults should be overridden.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.

  Examples
  --------
  Run the coordinator for a specific run identifier:

  ``python3 src/experiment_runner.py --run-ts 260320_221626``

  Override the run duration:

  ``python3 src/experiment_runner.py --run-ts 260320_221626 --duration-seconds 10``
  """
  parser = argparse.ArgumentParser(description="Run the host-side tunnel experiment.")
  parser.add_argument("--run-ts", required=True, help="specific run identifier to use")
  parser.add_argument("--duration-seconds", type=int, help="total experiment duration")
  parser.add_argument("--cycle-interval-seconds", type=int, help="delay between cycles")
  return parser.parse_args()


def main() -> int:
  """Run the full host-side proof workload and write its report.

  The coordinator starts the localhost PostgreSQL and Neo4j Bolt bridges,
  executes repeated proof cycles through those bridges plus the direct Neo4j
  HTTPS path, and always writes a machine-readable report even when the run
  fails.

  Returns
  -------
  int
    Zero when all proof paths succeeded, otherwise one.

  Examples
  --------
  Execute a short end-to-end proof manually:

  ``python3 src/experiment_runner.py --run-ts 260320_221626 --duration-seconds 1``
  """
  args = parse_args()
  repo_root = Path(__file__).resolve().parents[1]
  public_hosts = load_public_hosts_file(repo_root / ".runtime" / "public_hosts.json")
  run_id = args.run_ts
  duration_seconds = args.duration_seconds or DEFAULT_EXPERIMENT_DURATION_SECONDS
  cycle_interval_seconds = args.cycle_interval_seconds or DEFAULT_EXPERIMENT_CYCLE_INTERVAL_SECONDS
  raw_logs_dir = repo_root / "_logs" / "raw"
  report_path = raw_logs_dir / f"{run_id}_experiment_report.json"

  # Prefer the orchestrator's aggregated topology snapshot so the report
  # reflects the actual service set started inside the DinD host.
  topology = load_topology_snapshot(raw_logs_dir / f"{run_id}_topology_ready.json", public_hosts)
  topology["top_level_published_ports"] = top_level_published_ports()

  results: dict[str, Any] = {
    "neo4j_https": {"ok": False},
    "neo4j_bolt_tunnel": {"ok": False},
    "postgres_tunnel": {"ok": False},
  }
  cycle_results: list[dict[str, Any]] = []
  experiment_error: str | None = None

  try:
    # Start dedicated local TCP bridge listeners before the proof cycles begin.
    # From the point of view of local clients, these look like normal local
    # sockets even though the public hop uses Cloudflare's WebSocket carrier.
    with UniversalBridgeServer(
      name="postgres_client_bridge",
      hostname=public_hosts["postgres"],
      local_port=HOST_POSTGRES_FORWARD_PORT,
      run_ts=run_id,
      raw_logs_dir=raw_logs_dir,
    ) as postgres_bridge, UniversalBridgeServer(
      name="neo4j_bolt_client_bridge",
      hostname=public_hosts["neo4j_bolt"],
      local_port=HOST_NEO4J_BOLT_FORWARD_PORT,
      run_ts=run_id,
      raw_logs_dir=raw_logs_dir,
    ) as neo4j_bridge:
      print(f"run_id={run_id}")
      print(f"postgres local bridge: {LOCALHOST}:{HOST_POSTGRES_FORWARD_PORT}")
      print(f"neo4j bolt local bridge: {LOCALHOST}:{HOST_NEO4J_BOLT_FORWARD_PORT}")
      print(f"neo4j https public endpoint: https://{public_hosts['neo4j_http']}")
      print("bridge model: local TCP client -> host-side bridge -> wss://public-hostname -> private TCP origin")

      start_time = time.monotonic()
      cycle = 0
      while True:
        cycle += 1

        # Surface any background bridge failures before attempting the next
        # proof cycle so later errors are easier to attribute.
        postgres_bridge.raise_if_failed()
        neo4j_bridge.raise_if_failed()

        # The proof string is written into both databases so the final report
        # can show that each cycle really traversed the expected path.
        proof = f"{run_id}-cycle-{cycle}-{datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')}"
        print(f"cycle {cycle}: writing proof {proof}")

        postgres_result = run_postgres_cycle(run_id, cycle, proof, HOST_POSTGRES_FORWARD_PORT)
        neo4j_bolt_result = run_neo4j_bolt_cycle(run_id, cycle, proof, HOST_NEO4J_BOLT_FORWARD_PORT)
        neo4j_https_result = run_neo4j_https_read(run_id, public_hosts["neo4j_http"])

        results["postgres_tunnel"] = postgres_result
        results["neo4j_bolt_tunnel"] = neo4j_bolt_result
        results["neo4j_https"] = neo4j_https_result
        cycle_results.append(
          {
            "cycle": cycle,
            "proof": proof,
            "postgres_rows_seen": len(postgres_result["rows_for_run"]),
            "neo4j_bolt_events_seen": len(neo4j_bolt_result["events_for_run"]),
            "neo4j_https_events_seen": len(neo4j_https_result["events_for_run"]),
          },
        )

        # Emit a compact per-cycle snapshot so operators can watch progress.
        print(json.dumps(cycle_results[-1], indent=2), flush=True)

        elapsed = time.monotonic() - start_time
        if cycle >= 3 and elapsed >= duration_seconds:
          break

        # Keep looping until the requested duration has elapsed, but never
        # sleep past the configured deadline.
        sleep_seconds = min(cycle_interval_seconds, max(0.0, duration_seconds - elapsed))
        if sleep_seconds > 0:
          time.sleep(sleep_seconds)
  except Exception as exc:
    experiment_error = str(exc)

  # Always write a report, even on failure, so later validation and markdown
  # logging steps have a concrete artifact to inspect.
  report = {
    "run_id": run_id,
    "timestamp_utc": now_utc(),
    "duration_seconds": duration_seconds,
    "cycle_interval_seconds": cycle_interval_seconds,
    "cycles_completed": len(cycle_results),
    "topology": topology,
    "local_client_forwards": {
      "postgres": f"{LOCALHOST}:{HOST_POSTGRES_FORWARD_PORT}",
      "neo4j_bolt": f"{LOCALHOST}:{HOST_NEO4J_BOLT_FORWARD_PORT}",
    },
    "log_files": {
      "postgres_bridge": str(raw_logs_dir / f"{run_id}_postgres_client_bridge.log"),
      "neo4j_bolt_bridge": str(raw_logs_dir / f"{run_id}_neo4j_bolt_client_bridge.log"),
    },
    "cycle_results": cycle_results,
    "results": results,
    "error": experiment_error,
    "all_ok": (
      experiment_error is None
      and topology["top_level_published_ports"] == []
      and len(cycle_results) >= 3
      and results["postgres_tunnel"].get("ok") is True
      and results["neo4j_bolt_tunnel"].get("ok") is True
      and results["neo4j_https"].get("ok") is True
    ),
  }
  write_json_file(report_path, report)
  print(json.dumps(report, indent=2), flush=True)
  return 0 if report["all_ok"] else 1


if __name__ == "__main__":
  raise SystemExit(main())
