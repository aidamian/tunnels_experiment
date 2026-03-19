"""Stop client-side `cloudflared access tcp` forward containers.

This complements `start_cloudflared_forwards.py` and removes the deterministic
Docker containers that expose localhost ports for DBeaver and Bolt clients.
"""

from __future__ import annotations

import argparse
import json

from tunnels_experiment.access.cloudflared_tcp import (
  default_specs,
  state_file_path,
  stop_selected_forwards,
)
from tunnels_experiment.utils.files import write_json_file


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments.

  Returns
  -------
  argparse.Namespace
    Parsed CLI flags.
  """
  parser = argparse.ArgumentParser(
    description="Stop the local client-side Cloudflare TCP forward containers."
  )
  parser.add_argument(
    "--service",
    choices=["all", "postgres", "neo4j"],
    default="all",
    help="Which local forwards to stop.",
  )
  parser.add_argument(
    "--postgres-port",
    type=int,
    default=55432,
    help="Localhost port used for PostgreSQL forwards.",
  )
  parser.add_argument(
    "--neo4j-port",
    type=int,
    default=57687,
    help="Localhost port used for Neo4j Bolt forwards.",
  )
  return parser.parse_args()


def main() -> int:
  """Stop selected forward containers and clean state.

  Returns
  -------
  int
    Shell exit status.
  """
  args = parse_args()
  specs = default_specs(args.postgres_port, args.neo4j_port)
  if args.service != "all":
    specs = [spec for spec in specs if spec.service_key == args.service]

  stopped = stop_selected_forwards(specs)

  # The state file describes the current live forwards. When only one service
  # is stopped we keep the remaining service metadata instead of deleting the
  # entire file and losing useful connection details.
  state_path = state_file_path()
  if state_path.exists():
    stopped_keys = {spec.service_key for spec in specs}
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["specs"] = [
      item for item in payload.get("specs", []) if item.get("service_key") not in stopped_keys
    ]
    payload["forwards"] = [
      item for item in payload.get("forwards", []) if item.get("service_key") not in stopped_keys
    ]
    payload["verification"] = {
      key: value
      for key, value in payload.get("verification", {}).items()
      if key not in stopped_keys
    }

    if payload["specs"] or payload["forwards"] or payload["verification"]:
      write_json_file(state_path, payload)
    else:
      state_path.unlink()

  print("stopped client-side cloudflared forwards:")
  for container_name in stopped:
    print(f"- {container_name}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
