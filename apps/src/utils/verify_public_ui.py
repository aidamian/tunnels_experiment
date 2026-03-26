"""Verify that the app-host public HTTPS UI responds."""

from __future__ import annotations

import argparse
import http.client
import json
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Verify the app-host public HTTPS UI.")
  parser.add_argument("--run-ts", required=True)
  parser.add_argument("--timeout-seconds", type=int, default=20)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  app_root = Path(__file__).resolve().parents[2]
  topology_path = app_root / "_logs" / "raw" / f"{args.run_ts}_topology_ready.json"
  payload = json.loads(topology_path.read_text(encoding="utf-8"))
  public_host = payload["topology"]["public_hosts"]["app_ui_https"]
  deadline = time.time() + args.timeout_seconds
  last_error = {"public_host": public_host}

  while time.time() < deadline:
    for suffix in ("/misc/ping", "/login", "/"):
      url = f"https://{public_host}{suffix}"
      try:
        connection = http.client.HTTPSConnection(public_host, timeout=10)
        connection.request("GET", suffix)
        response = connection.getresponse()
        status = response.status
        body = response.read(128).decode("utf-8", errors="ignore")
        connection.close()
        if 200 <= status < 400:
          print(json.dumps({"ok": True, "url": url, "status": status, "body_sample": body}, indent=2))
          return 0
        last_error = {"url": url, "status": status, "body_sample": body}
      except OSError as exc:
        last_error = {"url": url, "reason": str(exc)}
        continue
    time.sleep(5)

  print(json.dumps({"ok": False, **last_error}, indent=2))
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
