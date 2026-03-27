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


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the run-log writer.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.

  Examples
  --------
  Append a verified run entry:

  ``python3 clients/src/utils/append_runlog.py --run-ts 260320_221626``
  """
  parser = argparse.ArgumentParser(description="Append a verified end-to-end run entry to _logs/RUNLOG.md.")
  parser.add_argument("--run-ts", required=True, help="specific run identifier to append")
  return parser.parse_args()


def load_optional_app_state(repo_root: Path, run_ts: str) -> dict[str, object] | None:
  topology_path = repo_root / "apps" / "_logs" / "raw" / f"{run_ts}_topology_ready.json"
  verification_path = repo_root / "apps" / "_logs" / "raw" / f"{run_ts}_verify_public_ui.log"

  if not topology_path.exists() or not verification_path.exists():
    return None

  topology_payload = json.loads(topology_path.read_text(encoding="utf-8"))
  verification_payload = json.loads(verification_path.read_text(encoding="utf-8"))
  return {
    "public_host": topology_payload["topology"]["public_hosts"]["app_ui_https"],
    "ok": verification_payload.get("ok", False),
    "status": verification_payload.get("status"),
    "body_sample": verification_payload.get("body_sample", ""),
  }


def main() -> int:
  """Append the selected run to the tracked markdown log.

  The appended markdown entry is intentionally compact so the repository keeps
  a chronological summary of verified runs without forcing readers to open the
  full JSON report first.

  Returns
  -------
  int
    Zero when the markdown entry was appended successfully.

  Examples
  --------
  ``python3 clients/src/utils/append_runlog.py --run-ts 260320_221626``
  """
  args = parse_args()
  client_root = Path(__file__).resolve().parents[2]
  repo_root = Path(__file__).resolve().parents[3]
  run_ts = args.run_ts
  report_path = client_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
  runlog_path = repo_root / "_logs" / "RUNLOG.md"
  runlog_path.parent.mkdir(parents=True, exist_ok=True)
  runlog_path.touch(exist_ok=True)

  # Append a compact markdown summary so the repository keeps a readable,
  # chronological history of verified end-to-end runs.
  payload = json.loads(report_path.read_text(encoding="utf-8"))
  app_state = load_optional_app_state(repo_root, run_ts)
  lines = [
    f"## {datetime.now().isoformat()} | run {run_ts}",
    f"- Result: {'PASS' if payload['all_ok'] else 'FAIL'}",
    f"- Cycles completed: {payload['cycles_completed']}",
    f"- Top-level published ports: {payload['topology']['top_level_published_ports'] or 'none'}",
    f"- Neo4j HTTPS host: {payload['topology']['public_hosts']['neo4j_https']}",
    f"- Neo4j Bolt host: {payload['topology']['public_hosts']['neo4j_bolt']}",
    f"- PostgreSQL host: {payload['topology']['public_hosts']['postgres']}",
    f"- Local PostgreSQL forward: {payload['local_client_forwards']['postgres']}",
    f"- Local Neo4j Bolt forward: {payload['local_client_forwards']['neo4j_bolt']}",
    f"- PostgreSQL rows for run: {len(payload['results']['postgres_tunnel']['rows_for_run'])}",
    f"- Neo4j events for run: {len(payload['results']['neo4j_bolt_tunnel']['events_for_run'])}",
  ]
  if app_state is not None:
    lines.extend(
      [
        f"- App UI host: {app_state['public_host']}",
        f"- App UI check: {'PASS' if app_state['ok'] else 'FAIL'} ({app_state['status']}, {app_state['body_sample']})",
      ],
    )
  lines.extend(
    [
      f"- Raw report: `clients/_logs/raw/{run_ts}_experiment_report.json`",
      "",
    ],
  )

  with runlog_path.open("a", encoding="utf-8") as handle:
    handle.write("\n".join(lines))

  print(f"appended {runlog_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
