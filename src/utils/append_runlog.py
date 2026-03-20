"""Append a compact markdown record for a verified run."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from utils.envfiles import load_env_file


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the run-log writer.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.
  """
  parser = argparse.ArgumentParser(description="Append a verified end-to-end run entry to _logs/RUNLOG.md.")
  parser.add_argument("--run-ts", help="specific run identifier to append")
  return parser.parse_args()


def main() -> int:
  """Append the selected run to the tracked markdown log.

  Returns
  -------
  int
    Zero when the markdown entry was appended successfully.
  """
  args = parse_args()
  repo_root = Path(__file__).resolve().parents[2]
  env = load_env_file(repo_root / ".runtime" / "tunnels.env")
  run_ts = args.run_ts or env["RUN_TS"]
  report_path = repo_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
  runlog_path = repo_root / "_logs" / "RUNLOG.md"

  # Append a compact markdown summary so the repository keeps a readable,
  # chronological history of verified end-to-end runs.
  payload = json.loads(report_path.read_text(encoding="utf-8"))
  lines = [
    f"## {datetime.now().isoformat()} | run {run_ts}",
    f"- Result: {'PASS' if payload['all_ok'] else 'FAIL'}",
    f"- Cycles completed: {payload['cycles_completed']}",
    f"- Top-level published ports: {payload['topology']['top_level_published_ports'] or 'none'}",
    f"- Neo4j HTTPS host: {payload['topology']['public_hosts']['neo4j_https']}",
    f"- Neo4j Bolt host: {payload['topology']['public_hosts']['neo4j_bolt']}",
    f"- PostgreSQL host: {payload['topology']['public_hosts']['postgres_tcp']}",
    f"- Local PostgreSQL forward: {payload['local_client_forwards']['postgres']}",
    f"- Local Neo4j Bolt forward: {payload['local_client_forwards']['neo4j_bolt']}",
    f"- PostgreSQL rows for run: {len(payload['results']['postgres_tunnel']['rows_for_run'])}",
    f"- Neo4j events for run: {len(payload['results']['neo4j_bolt_tunnel']['events_for_run'])}",
    f"- Raw report: `_logs/raw/{run_ts}_experiment_report.json`",
    "",
  ]

  with runlog_path.open("a", encoding="utf-8") as handle:
    handle.write("\n".join(lines))

  print(f"appended {runlog_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
