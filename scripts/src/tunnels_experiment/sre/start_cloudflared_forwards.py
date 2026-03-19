"""Start client-side `cloudflared access tcp` forwards for local tools.

This SRE entrypoint is the supported replacement for the repository's custom
Python bridge when an operator wants to:

- connect DBeaver to PostgreSQL on a localhost port; or
- connect the Neo4j Python Bolt driver to a localhost port.

It deliberately uses Cloudflare's own client-side helper instead of opening a
custom WebSocket relay in Python.
"""

from __future__ import annotations

import argparse
from typing import Any

from tunnels_experiment.access.cloudflared_tcp import (
  LOCALHOST,
  build_state_payload,
  default_specs,
  load_runtime_env,
  start_forward,
  verify_neo4j_forward,
  verify_postgres_forward,
  write_forward_state,
)


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments.

  Returns
  -------
  argparse.Namespace
    Parsed CLI flags.
  """
  parser = argparse.ArgumentParser(
    description=(
      "Start local client-side Cloudflare TCP forwards so DBeaver and Bolt "
      "clients can connect without using the repository's Python bridge."
    )
  )
  parser.add_argument(
    "--service",
    choices=["all", "postgres", "neo4j"],
    default="all",
    help="Which local forwards to start.",
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
    help="Run real PostgreSQL and Neo4j queries through the started forwards.",
  )
  return parser.parse_args()


def selected_specs(args: argparse.Namespace) -> list[Any]:
  """Filter forward specs based on CLI selection.

  Parameters
  ----------
  args:
    Parsed CLI arguments.

  Returns
  -------
  list[Any]
    Selected `ForwardSpec` objects.
  """
  specs = default_specs(args.postgres_port, args.neo4j_port)
  if args.service == "all":
    return specs
  return [spec for spec in specs if spec.service_key == args.service]


def print_connection_instructions(env: dict[str, str], started_forwards: list[dict[str, Any]]) -> None:
  """Print operator-facing connection details.

  Parameters
  ----------
  env:
    Parsed runtime environment.
  started_forwards:
    Structured started-forward state.
  """
  print("started client-side cloudflared forwards:")
  for forward in started_forwards:
    print(
      f"- {forward['service_key']}: {forward['public_host']} -> "
      f"{forward['local_host']}:{forward['local_port']} "
      f"({forward['container_name']})"
    )

  started_keys = {forward["service_key"] for forward in started_forwards}

  if "postgres" in started_keys:
    print("postgres client settings:")
    print(f"- host: {LOCALHOST}")
    print(f"- port: {next(item['local_port'] for item in started_forwards if item['service_key'] == 'postgres')}")
    print(f"- database: {env['POSTGRES_DB']}")
    print(f"- user: {env['POSTGRES_USER']}")
    print(f"- password: {env['POSTGRES_PASSWORD']}")
    print("- ssl mode: disable")
    print("- works for DBeaver because the local port now speaks native PostgreSQL")

  if "neo4j" in started_keys:
    print("neo4j bolt client settings:")
    print(
      f"- uri: bolt://{LOCALHOST}:"
      f"{next(item['local_port'] for item in started_forwards if item['service_key'] == 'neo4j')}"
    )
    print(f"- username: {env['NEO4J_USER']}")
    print(f"- password: {env['NEO4J_PASSWORD']}")
    print("- encryption: off for the localhost leg")


def maybe_verify(
  args: argparse.Namespace,
  env: dict[str, str],
  started_forwards: list[dict[str, Any]],
) -> dict[str, Any]:
  """Optionally verify the started forwards with real driver calls.

  Parameters
  ----------
  args:
    Parsed CLI arguments.
  env:
    Parsed runtime environment.
  started_forwards:
    Structured started-forward state.

  Returns
  -------
  dict[str, Any]
    Verification results keyed by service key.
  """
  verification: dict[str, Any] = {}
  if not args.verify:
    return verification

  for forward in started_forwards:
    if forward["service_key"] == "postgres":
      verification["postgres"] = verify_postgres_forward(forward["local_port"], env)
    if forward["service_key"] == "neo4j":
      verification["neo4j"] = verify_neo4j_forward(forward["local_port"], env)

  print("verification results:")
  for service_key, result in verification.items():
    print(f"- {service_key}: ok={result['ok']} query_result={result['query_result']}")

  return verification


def main() -> int:
  """Start the requested forwards and print connection details.

  Returns
  -------
  int
    Shell exit status.
  """
  args = parse_args()
  env = load_runtime_env()
  specs = selected_specs(args)
  started_forwards = [start_forward(spec, env) for spec in specs]
  verification = maybe_verify(args, env, started_forwards)
  write_forward_state(build_state_payload(specs, started_forwards, verification))
  print_connection_instructions(env, started_forwards)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
