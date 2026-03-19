#!/usr/bin/env python3

from __future__ import annotations

import json
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
    consumer_host = env["CONSUMER_HTTP_PUBLIC_HOST"]
    report_url = f"https://{consumer_host}/report"
    deadline = time.time() + 240
    last_error = "no attempt made"
    context = ssl.create_default_context()

    print(f"probing {report_url}")
    while time.time() < deadline:
        try:
            request = Request(
                report_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "curl/8.0",
                },
            )
            with urlopen(request, timeout=20, context=context) as response:
                payload = json.loads(response.read().decode("utf-8"))
            all_ok = bool(payload.get("all_ok"))
            if all_ok:
                print("public smoke test passed")
                print(json.dumps(payload, indent=2))
                return 0
            last_error = json.dumps(payload.get("results", {}), indent=2)
        except HTTPError as exc:
            last_error = f"http {exc.code}: {exc.reason}"
        except URLError as exc:
            last_error = str(exc)
        except Exception as exc:  # pragma: no cover - integration-oriented fallback
            last_error = str(exc)

        print(f"waiting for healthy public report: {last_error}")
        time.sleep(5)

    print("public smoke test failed")
    print(last_error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
