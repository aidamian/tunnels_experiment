"""Write the tracked markdown summary for a specific run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from utils.sdk_logging import build_console_logger, log_message


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for the summary writer.

  Returns
  -------
  argparse.Namespace
    Parsed CLI options.

  Examples
  --------
  ``python3 clients/src/utils/write_summary.py --run-ts 260320_221626``
  """
  parser = argparse.ArgumentParser(description="Write a tracked iteration summary for the specified run.")
  parser.add_argument("--run-ts", required=True, help="specific run identifier to summarize")
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
    "postgres_bridge": topology_payload["topology"]["local_origins_inside_dind_host"]["postgres_bridge"],
    "ok": verification_payload.get("ok", False),
    "status": verification_payload.get("status"),
    "body_sample": verification_payload.get("body_sample", ""),
  }


def main() -> int:
  """Write the markdown summary for the selected run.

  The summary file is the short tracked markdown artifact meant for repository
  readers who want the verified outcome without opening the full JSON report.

  Returns
  -------
  int
    Zero when the summary file was written successfully.

  Examples
  --------
  ``python3 clients/src/utils/write_summary.py --run-ts 260320_221626``
  """
  args = parse_args()
  log = build_console_logger("write-summary")
  client_root = Path(__file__).resolve().parents[2]
  repo_root = Path(__file__).resolve().parents[3]
  run_ts = args.run_ts
  report_path = client_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
  summary_path = repo_root / "_logs" / f"{run_ts}_summary.md"
  summary_path.parent.mkdir(parents=True, exist_ok=True)

  # The summary file is the short tracked markdown artifact for a single run.
  payload = json.loads(report_path.read_text(encoding="utf-8"))
  app_state = load_optional_app_state(repo_root, run_ts)
  lines = [
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
    f"- PostgreSQL TCP: {payload['topology']['public_hosts']['postgres']}",
  ]
  if app_state is not None:
    lines.extend(
      [
        f"- App UI HTTPS: https://{app_state['public_host']}",
        "",
        "## App Consumer Proof",
        f"- App-host PostgreSQL bridge: {app_state['postgres_bridge']}",
        f"- App UI probe: {'PASS' if app_state['ok'] else 'FAIL'} ({app_state['status']}, {app_state['body_sample']})",
        f"- Raw app topology: `apps/_logs/raw/{run_ts}_topology_ready.json`",
        f"- Raw app UI check: `apps/_logs/raw/{run_ts}_verify_public_ui.log`",
      ],
    )
  lines.extend(
    [
      "",
      "## Proof",
      f"- PostgreSQL rows written for this run: {len(payload['results']['postgres_tunnel']['rows_for_run'])}",
      f"- Neo4j events written for this run: {len(payload['results']['neo4j_bolt_tunnel']['events_for_run'])}",
      f"- Raw report: `clients/_logs/raw/{run_ts}_experiment_report.json`",
      "",
    ],
  )
  summary = "\n".join(lines)

  # Overwrite the per-run summary so rerunning the same run id keeps a single
  # authoritative markdown snapshot for that run identifier.
  summary_path.write_text(summary + "\n", encoding="utf-8")
  log_message(log, f"wrote {summary_path}", color="green")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
