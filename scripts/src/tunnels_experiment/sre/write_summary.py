"""Write the tracked markdown summary for a specific run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tunnels_experiment.utils.envfiles import load_env_file


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the summary writer.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.
  """
  parser = argparse.ArgumentParser(description="Write a tracked iteration summary for the specified run.")
  parser.add_argument("--run-ts", help="specific run identifier to summarize")
  return parser.parse_args()


def main() -> int:
  """Write the markdown summary for the selected run.

  Returns
  -------
  int
    Zero when the summary file was written successfully.
  """
  args = parse_args()
  repo_root = Path(__file__).resolve().parents[4]
  env = load_env_file(repo_root / ".runtime" / "tunnels.env")
  run_ts = args.run_ts or env["RUN_TS"]
  report_path = repo_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
  summary_path = repo_root / "_logs" / f"{run_ts}_summary.md"

  # The summary file is the short tracked markdown artifact for a single run.
  payload = json.loads(report_path.read_text(encoding="utf-8"))
  summary = "\n".join(
    [
      f"# {run_ts} summary",
      "",
      "## Result",
      f"- Overall status: {'PASS' if payload['all_ok'] else 'FAIL'}",
      f"- Cycles completed: {payload['cycles_completed']}",
      f"- Top-level published ports: {payload['topology']['top_level_published_ports'] or 'none'}",
      "",
      "## Verified Paths",
      f"- Neo4j HTTPS: https://{payload['topology']['public_hosts']['neo4j_https']}",
      f"- Neo4j Bolt: {payload['topology']['public_hosts']['neo4j_bolt']}",
      f"- PostgreSQL TCP: {payload['topology']['public_hosts']['postgres_tcp']}",
      "",
      "## Proof",
      f"- PostgreSQL rows written for this run: {len(payload['results']['postgres_tunnel']['rows_for_run'])}",
      f"- Neo4j events written for this run: {len(payload['results']['neo4j_bolt_tunnel']['events_for_run'])}",
      f"- Raw report: `_logs/raw/{run_ts}_experiment_report.json`",
      "",
    ],
  )

  # Overwrite the per-run summary so rerunning the same run id keeps a single
  # authoritative markdown snapshot for that run identifier.
  summary_path.write_text(summary + "\n", encoding="utf-8")
  print(f"wrote {summary_path}")
  return 0
