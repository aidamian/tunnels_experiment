#!/usr/bin/env python3

from __future__ import annotations

import json
import time
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / ".runtime" / "tunnels.env"
    if not env_path.exists():
        raise SystemExit("missing .runtime/tunnels.env; run python3 scripts/prepare_runtime.py first")

    env = load_env_file(env_path)
    run_ts = env["RUN_TS"]
    report_path = repo_root / "_logs" / f"{run_ts}_consumer_report.json"
    deadline = time.time() + 300
    last_error = "no report observed"

    print(f"waiting for consumer report {report_path}")
    while time.time() < deadline:
        if report_path.exists():
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                last_error = f"invalid json: {exc}"
                time.sleep(3)
                continue

            if payload.get("run_id") != run_ts:
                last_error = f"unexpected run_id {payload.get('run_id')!r}"
            elif payload.get("all_ok"):
                print("smoke test passed")
                print(json.dumps(payload, indent=2))
                return 0
            else:
                last_error = json.dumps(payload.get("results", {}), indent=2)

        print(f"waiting for healthy consumer report: {last_error}")
        time.sleep(5)

    print("smoke test failed")
    print(last_error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
