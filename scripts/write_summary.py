#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a tracked iteration summary for the specified run.")
    parser.add_argument("--run-ts", help="specific run identifier to summarize")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    env = load_env_file(repo_root / ".runtime" / "tunnels.env")
    run_ts = args.run_ts or env["RUN_TS"]
    report_path = repo_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
    summary_path = repo_root / "_logs" / f"{run_ts}_summary.md"

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
        ]
    )
    summary_path.write_text(summary + "\n", encoding="utf-8")
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
