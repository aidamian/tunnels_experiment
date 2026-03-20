"""Start manual localhost bridges that relay directly to tunnel FQDNs.

This is the supported client-side operator path for tools such as DBeaver and
Bolt consumers when the client machine should remain independent of any
`cloudflared` tooling.
"""

from __future__ import annotations

import argparse
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from bridge.universal import UniversalBridgeServer
from utils.local_bridges import (
  LOCALHOST,
  bridge_state,
  default_specs,
  load_runtime_env,
  repo_root,
  verify_neo4j_bridge,
  verify_postgres_bridge,
)


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments."""
  parser = argparse.ArgumentParser(
    description=(
      "Start local Python TCP bridges so DBeaver and Bolt clients can connect "
      "without any client-side cloudflared dependency."
    )
  )
  parser.add_argument(
    "--service",
    choices=["all", "postgres", "neo4j"],
    default="all",
    help="Which localhost bridges to start.",
  )
  parser.add_argument(
    "--postgres-port",
    type=int,
    default=55432,
    help="Localhost port to expose for PostgreSQL clients.",
  )
  parser.add_argument(
    "--neo4j-port",
    type=int,
    default=57687,
    help="Localhost port to expose for Neo4j Bolt clients.",
  )
  parser.add_argument(
    "--verify",
    action="store_true",
    help="Run real PostgreSQL and Neo4j queries through the started bridges.",
  )
  parser.add_argument(
    "--duration-seconds",
    type=int,
    help="How long to keep the bridges running before exiting. Default is forever.",
  )
  parser.add_argument(
    "--run-ts",
    help="Specific run identifier to use in bridge log file names.",
  )
  return parser.parse_args()


def selected_specs(args: argparse.Namespace) -> list[Any]:
  """Filter bridge specs based on CLI selection."""
  specs = default_specs(args.postgres_port, args.neo4j_port)
  if args.service == "all":
    return specs
  return [spec for spec in specs if spec.service_key == args.service]


def print_connection_instructions(env: dict[str, str], started_bridges: list[dict[str, Any]]) -> None:
  """Print operator-facing connection details."""
  print("started local Python bridges:")
  for bridge in started_bridges:
    print(
      f"- {bridge['service_key']}: wss://{bridge['public_host']} -> "
      f"{bridge['local_host']}:{bridge['local_port']}"
    )

  started_keys = {bridge["service_key"] for bridge in started_bridges}

  if "postgres" in started_keys:
    postgres_port = next(item["local_port"] for item in started_bridges if item["service_key"] == "postgres")
    print("postgres client settings:")
    print(f"- host: {LOCALHOST}")
    print(f"- port: {postgres_port}")
    print(f"- database: {env['POSTGRES_DB']}")
    print(f"- user: {env['POSTGRES_USER']}")
    print(f"- password: {env['POSTGRES_PASSWORD']}")
    print("- ssl mode: disable")

  if "neo4j" in started_keys:
    neo4j_port = next(item["local_port"] for item in started_bridges if item["service_key"] == "neo4j")
    print("neo4j bolt client settings:")
    print(f"- uri: bolt://{LOCALHOST}:{neo4j_port}")
    print(f"- username: {env['NEO4J_USER']}")
    print(f"- password: {env['NEO4J_PASSWORD']}")
    print("- encryption: off for the localhost leg")


def maybe_verify(
  args: argparse.Namespace,
  env: dict[str, str],
  started_bridges: list[dict[str, Any]],
) -> dict[str, Any]:
  """Optionally verify the started bridges with real driver calls."""
  verification: dict[str, Any] = {}
  if not args.verify:
    return verification

  for bridge in started_bridges:
    if bridge["service_key"] == "postgres":
      verification["postgres"] = verify_postgres_bridge(bridge["local_port"], env)
    if bridge["service_key"] == "neo4j":
      verification["neo4j"] = verify_neo4j_bridge(bridge["local_port"], env)

  print("verification results:")
  for service_key, result in verification.items():
    print(f"- {service_key}: ok={result['ok']} query_result={result['query_result']}")

  return verification


def main() -> int:
  """Start the requested bridges and keep them alive."""
  args = parse_args()
  env = load_runtime_env()
  run_ts = args.run_ts or env["RUN_TS"]
  specs = selected_specs(args)
  raw_logs_dir = repo_root() / "_logs" / "raw"
  started_bridges: list[dict[str, Any]] = []
  servers: list[UniversalBridgeServer] = []

  try:
    with ExitStack() as stack:
      for spec in specs:
        server = UniversalBridgeServer(
          name=f"{spec.service_key}_manual_bridge",
          hostname=env[spec.public_host_env_key],
          local_port=spec.local_port,
          run_ts=run_ts,
          raw_logs_dir=raw_logs_dir,
        )
        stack.enter_context(server)
        servers.append(server)
        started_bridges.append(bridge_state(spec, env))

      verification = maybe_verify(args, env, started_bridges)
      print_connection_instructions(env, started_bridges)

      if args.duration_seconds is not None:
        deadline = time.monotonic() + args.duration_seconds
        while time.monotonic() < deadline:
          for server in servers:
            server.raise_if_failed()
          time.sleep(0.5)
        for server in servers:
          server.raise_if_failed()
        return 0

      print("bridges running; press Ctrl+C to stop")
      while True:
        for server in servers:
          server.raise_if_failed()
        time.sleep(1)
  except KeyboardInterrupt:
    print("stopping local Python bridges")
    return 0


if __name__ == "__main__":
  raise SystemExit(main())
