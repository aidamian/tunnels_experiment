"""Run the host-side end-to-end proof workload.

This module coordinates the host-side local TCP bridges, PostgreSQL proof
queries, Neo4j Bolt proof queries, and direct Neo4j HTTPS reads. The actual
database-specific checks live in dedicated modules so concerns remain separate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
SHARED_SRC_DIR = Path(__file__).resolve().parents[2] / "shared" / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))
if str(SHARED_SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SHARED_SRC_DIR))

from simulators.neo4j_bolt import run_neo4j_bolt_cycle
from simulators.neo4j_https import run_neo4j_https_read
from simulators.postgres import run_postgres_cycle
from tunnel_common.universal import LOCALHOST, UniversalBridgeServer
from utils.console import colorize, format_line
from utils.demo_config import (
  DEFAULT_EXPERIMENT_CYCLE_INTERVAL_SECONDS,
  DEFAULT_EXPERIMENT_DURATION_SECONDS,
)
from utils.docker_runtime import top_level_published_ports
from utils.files import write_json_file
from utils.services import load_services, public_host_map, require_service


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

  ``python3 clients/src/experiment_runner.py --run-ts 260320_221626``

  Override the run duration:

  ``python3 clients/src/experiment_runner.py --run-ts 260320_221626 --duration-seconds 10``
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

  ``python3 clients/src/experiment_runner.py --run-ts 260320_221626 --duration-seconds 1``
  """
  args = parse_args()
  client_root = Path(__file__).resolve().parents[1]
  services = load_services()
  public_hosts = public_host_map(services)
  postgres_service = require_service(services, "postgres")
  neo4j_bolt_service = require_service(services, "neo4j_bolt")
  neo4j_https_service = require_service(services, "neo4j_https")
  if postgres_service.bridge is None or neo4j_bolt_service.bridge is None:
    raise SystemExit("clients/services.json must define bridge settings for postgres and neo4j_bolt")
  run_id = args.run_ts
  duration_seconds = args.duration_seconds or DEFAULT_EXPERIMENT_DURATION_SECONDS
  cycle_interval_seconds = args.cycle_interval_seconds or DEFAULT_EXPERIMENT_CYCLE_INTERVAL_SECONDS
  raw_logs_dir = client_root / "_logs" / "raw"
  report_path = raw_logs_dir / f"{run_id}_experiment_report.json"

  topology = {
    "top_level_container": "dind-host-server",
    "top_level_service": "dind-host-server",
    "managed_service_containers": ["neo4j-demo", "postgres-demo"],
    "public_hosts": public_hosts,
    "services": [service.to_dict() for service in services],
  }
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
      hostname=postgres_service.public_host,
      local_port=postgres_service.bridge.local_port,
      run_ts=run_id,
      raw_logs_dir=raw_logs_dir,
      log_color="green",
    ) as postgres_bridge, UniversalBridgeServer(
      name="neo4j_bolt_client_bridge",
      hostname=neo4j_bolt_service.public_host,
      local_port=neo4j_bolt_service.bridge.local_port,
      run_ts=run_id,
      raw_logs_dir=raw_logs_dir,
      log_color="blue",
    ) as neo4j_bridge:
      print(colorize(format_line("experiment", f"run_id={run_id}"), "cyan"), flush=True)
      print(colorize(format_line("experiment", f"postgres local bridge: {postgres_service.bridge.local_host}:{postgres_service.bridge.local_port}"), "green"), flush=True)
      print(colorize(format_line("experiment", f"neo4j bolt local bridge: {neo4j_bolt_service.bridge.local_host}:{neo4j_bolt_service.bridge.local_port}"), "blue"), flush=True)
      print(colorize(format_line("experiment", f"neo4j https public endpoint: {neo4j_https_service.display_url}"), "cyan"), flush=True)
      print(colorize(format_line("experiment", "bridge model: local TCP client -> host-side bridge -> wss://public-hostname -> private TCP origin"), "yellow"), flush=True)

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
        print(colorize(format_line("experiment", f"cycle {cycle}: writing proof {proof}"), "cyan"), flush=True)

        postgres_result = run_postgres_cycle(run_id, cycle, proof, postgres_service.bridge.local_port)
        neo4j_bolt_result = run_neo4j_bolt_cycle(run_id, cycle, proof, neo4j_bolt_service.bridge.local_port)
        neo4j_https_result = run_neo4j_https_read(run_id, neo4j_https_service.public_host)

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
      "postgres": f"{postgres_service.bridge.local_host}:{postgres_service.bridge.local_port}",
      "neo4j_bolt": f"{neo4j_bolt_service.bridge.local_host}:{neo4j_bolt_service.bridge.local_port}",
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
