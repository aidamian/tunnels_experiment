#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
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
    parser = argparse.ArgumentParser(description="Validate the latest host-side experiment report.")
    parser.add_argument("--run-ts", help="specific run identifier to validate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / ".runtime" / "tunnels.env"
    if not env_path.exists():
        raise SystemExit("missing .runtime/tunnels.env; run python3 scripts/prepare_runtime.py first")

    env = load_env_file(env_path)
    run_ts = args.run_ts or env["RUN_TS"]
    report_path = repo_root / "_logs" / "raw" / f"{run_ts}_experiment_report.json"
    deadline = time.time() + 300
    last_error = "no report observed"

    print(f"waiting for experiment report {report_path}", flush=True)
    while time.time() < deadline:
        if report_path.exists():
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                last_error = f"invalid json: {exc}"
                time.sleep(3)
                continue

            postgres_result = payload.get("results", {}).get("postgres_tunnel", {})
            neo4j_bolt_result = payload.get("results", {}).get("neo4j_bolt_tunnel", {})
            neo4j_https_result = payload.get("results", {}).get("neo4j_https", {})
            topology_result = payload.get("topology", {})

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

            last_error = json.dumps(payload, indent=2)

        print(f"waiting for healthy experiment report: {last_error}", flush=True)
        time.sleep(5)

    print("smoke test failed", flush=True)
    print(last_error, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
