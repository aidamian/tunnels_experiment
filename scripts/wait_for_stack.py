#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
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
    parser = argparse.ArgumentParser(description="Wait for the top-level DinD host container to report readiness.")
    parser.add_argument("--run-ts", help="specific run identifier to wait for")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


def docker_status() -> str:
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=^/dind-host-container$", "--format", "{{.Status}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "container not running yet"


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    env = load_env_file(repo_root / ".runtime" / "tunnels.env")
    run_ts = args.run_ts or env["RUN_TS"]
    ready_path = repo_root / "_logs" / "raw" / f"{run_ts}_topology_ready.json"
    deadline = time.time() + args.timeout_seconds

    print(f"waiting for topology readiness marker {ready_path}", flush=True)
    while time.time() < deadline:
        if ready_path.exists():
            payload = json.loads(ready_path.read_text(encoding="utf-8"))
            if payload.get("all_ready") is True:
                print("topology is ready", flush=True)
                print(json.dumps(payload, indent=2), flush=True)
                return 0

        print(f"current top-level container status: {docker_status()}", flush=True)
        time.sleep(5)

    print("timed out waiting for the nested topology", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
