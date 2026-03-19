"""Manage client-side `cloudflared access tcp` forwards for local tools.

This module exists to replace the repository's custom Python WebSocket bridge
when the operator wants to use Cloudflare's own client-side helper instead.

The important distinction is:

- The published PostgreSQL and Neo4j Bolt hostnames are Cloudflare TCP
  applications, not native raw database sockets on the public Internet.
- End-user tools therefore need a local TCP endpoint on the real machine.
- `cloudflared access tcp` provides that endpoint and carries the byte stream
  to the Cloudflare edge over the transport Cloudflare expects.

In this repository we launch `cloudflared` in short-lived Docker containers so
the real machine does not need a separate native binary installation.
"""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tunnels_experiment.utils.dependencies import get_graph_database_class, get_psycopg_module
from tunnels_experiment.utils.envfiles import load_env_file
from tunnels_experiment.utils.files import write_json_file


LOCALHOST = "127.0.0.1"
CLOUDFLARED_IMAGE = "cloudflare/cloudflared:latest"
STATE_FILE_NAME = "cloudflared_client_forwards.json"


@dataclass(frozen=True)
class ForwardSpec:
  """Describe one local `cloudflared access tcp` forward.

  Parameters
  ----------
  service_key:
    Stable service identifier used in state files and CLI filters.
  container_name:
    Docker container name used for the local forward helper.
  public_host_env_key:
    Runtime env key that contains the public tunnel hostname.
  local_port:
    Real-machine TCP port that local clients will connect to.
  purpose:
    Human-readable explanation of the service.
  """

  service_key: str
  container_name: str
  public_host_env_key: str
  local_port: int
  purpose: str


def repo_root() -> Path:
  """Return the repository root.

  Returns
  -------
  Path
    Absolute path to the repository root.
  """
  # The module lives at `scripts/src/tunnels_experiment/access/`, so the
  # repository root is four levels above this file.
  return Path(__file__).resolve().parents[4]


def runtime_env_path() -> Path:
  """Return the generated runtime env-file path."""
  return repo_root() / ".runtime" / "tunnels.env"


def state_file_path() -> Path:
  """Return the client-forward state file path."""
  return repo_root() / ".runtime" / STATE_FILE_NAME


def load_runtime_env() -> dict[str, str]:
  """Load the generated runtime environment.

  Returns
  -------
  dict[str, str]
    Parsed key-value pairs from `.runtime/tunnels.env`.

  Raises
  ------
  FileNotFoundError
    If the runtime env file has not been generated yet.
  """
  path = runtime_env_path()
  if not path.exists():
    raise FileNotFoundError(
      f"{path} does not exist. Run `python3 scripts/sre/prepare_runtime.py` first."
    )
  return load_env_file(path)


def default_specs(postgres_port: int, neo4j_port: int) -> list[ForwardSpec]:
  """Return the default local-forward specifications.

  Parameters
  ----------
  postgres_port:
    Real-machine local port for PostgreSQL clients such as DBeaver.
  neo4j_port:
    Real-machine local port for Neo4j Bolt clients.

  Returns
  -------
  list[ForwardSpec]
    Forward descriptions in deterministic order.
  """
  return [
    ForwardSpec(
      service_key="postgres",
      container_name="tunnel-demo-cf-postgres-forward",
      public_host_env_key="POSTGRES_PUBLIC_HOST",
      local_port=postgres_port,
      purpose="PostgreSQL local TCP listener for DBeaver-style clients",
    ),
    ForwardSpec(
      service_key="neo4j",
      container_name="tunnel-demo-cf-neo4j-forward",
      public_host_env_key="NEO4J_BOLT_PUBLIC_HOST",
      local_port=neo4j_port,
      purpose="Neo4j Bolt local TCP listener for Bolt drivers",
    ),
  ]


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
  """Run a subprocess with captured text output.

  Parameters
  ----------
  command:
    Exact command argv list.
  check:
    Whether a non-zero exit code should raise an exception.

  Returns
  -------
  subprocess.CompletedProcess[str]
    Completed process data including stdout/stderr.
  """
  return subprocess.run(
    command,
    check=check,
    capture_output=True,
    text=True,
  )


def remove_forward_container(container_name: str) -> None:
  """Remove a local forward container if it already exists.

  Parameters
  ----------
  container_name:
    Deterministic Docker container name.
  """
  # Repeated operator runs should be idempotent. Removing the prior helper
  # first avoids confusing port-binding failures and stale hostname mappings.
  run_command(["docker", "rm", "-f", container_name], check=False)


def wait_for_local_listener(port: int, timeout_seconds: int = 15) -> None:
  """Wait until a local TCP listener accepts connections.

  Parameters
  ----------
  port:
    Local TCP port to probe on `127.0.0.1`.
  timeout_seconds:
    Maximum number of seconds to wait.

  Raises
  ------
  TimeoutError
    If the local listener never becomes reachable.
  """
  deadline = time.monotonic() + timeout_seconds
  while time.monotonic() < deadline:
    try:
      with socket.create_connection((LOCALHOST, port), timeout=1):
        return
    except OSError:
      time.sleep(0.25)
  raise TimeoutError(f"local listener on {LOCALHOST}:{port} did not open in time")


def docker_logs(container_name: str) -> str:
  """Return logs for a running forward container.

  Parameters
  ----------
  container_name:
    Docker container name.

  Returns
  -------
  str
    Captured container log text.
  """
  result = run_command(["docker", "logs", container_name], check=False)
  return (result.stdout + result.stderr).strip()


def start_forward(spec: ForwardSpec, env: dict[str, str]) -> dict[str, Any]:
  """Start one client-side `cloudflared access tcp` forward.

  Parameters
  ----------
  spec:
    Forward description for the target service.
  env:
    Parsed runtime environment from `.runtime/tunnels.env`.

  Returns
  -------
  dict[str, Any]
    Structured state describing the started forward.
  """
  public_host = env[spec.public_host_env_key]
  remove_forward_container(spec.container_name)

  # We publish the container's listener port back to the real machine so GUI
  # tools such as DBeaver can target a stable localhost address.
  result = run_command(
    [
      "docker",
      "run",
      "--rm",
      "-d",
      "-p",
      f"{spec.local_port}:{spec.local_port}",
      "--name",
      spec.container_name,
      CLOUDFLARED_IMAGE,
      "access",
      "tcp",
      "--hostname",
      public_host,
      "--url",
      f"0.0.0.0:{spec.local_port}",
      "--loglevel",
      "info",
    ]
  )
  container_id = result.stdout.strip()
  wait_for_local_listener(spec.local_port)

  return {
    "service_key": spec.service_key,
    "container_name": spec.container_name,
    "container_id": container_id,
    "public_host": public_host,
    "local_host": LOCALHOST,
    "local_port": spec.local_port,
    "purpose": spec.purpose,
    "startup_logs": docker_logs(spec.container_name),
  }


def stop_selected_forwards(specs: list[ForwardSpec]) -> list[str]:
  """Stop the selected forward containers.

  Parameters
  ----------
  specs:
    Forward descriptions to stop.

  Returns
  -------
  list[str]
    Container names that were targeted for removal.
  """
  stopped: list[str] = []
  for spec in specs:
    remove_forward_container(spec.container_name)
    stopped.append(spec.container_name)
  return stopped


def verify_postgres_forward(local_port: int, env: dict[str, str]) -> dict[str, Any]:
  """Verify PostgreSQL connectivity through the local `cloudflared` forward.

  Parameters
  ----------
  local_port:
    Real-machine local port exposed by `cloudflared`.
  env:
    Parsed runtime environment from `.runtime/tunnels.env`.

  Returns
  -------
  dict[str, Any]
    Structured verification result.
  """
  psycopg = get_psycopg_module()
  with psycopg.connect(
    host=LOCALHOST,
    port=local_port,
    dbname=env["POSTGRES_DB"],
    user=env["POSTGRES_USER"],
    password=env["POSTGRES_PASSWORD"],
    connect_timeout=10,
    sslmode="disable",
  ) as connection:
    with connection.cursor() as cursor:
      # `SELECT 1` proves the forward reaches a real PostgreSQL protocol
      # endpoint without relying on any demo-specific table names.
      cursor.execute("SELECT 1")
      value = cursor.fetchone()[0]

  return {
    "ok": value == 1,
    "host": LOCALHOST,
    "port": local_port,
    "query_result": value,
  }


def verify_neo4j_forward(local_port: int, env: dict[str, str]) -> dict[str, Any]:
  """Verify Neo4j Bolt connectivity through the local `cloudflared` forward.

  Parameters
  ----------
  local_port:
    Real-machine local port exposed by `cloudflared`.
  env:
    Parsed runtime environment from `.runtime/tunnels.env`.

  Returns
  -------
  dict[str, Any]
    Structured verification result.
  """
  graph_database = get_graph_database_class()

  # The localhost listener is a plain TCP socket. `cloudflared` handles the
  # TLS/WebSocket leg to Cloudflare on behalf of the Bolt driver.
  driver = graph_database.driver(
    f"bolt://{LOCALHOST}:{local_port}",
    auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
    connection_timeout=10,
  )
  try:
    with driver.session() as session:
      value = session.run("RETURN 1 AS ready").single()["ready"]
  finally:
    driver.close()

  return {
    "ok": value == 1,
    "host": LOCALHOST,
    "port": local_port,
    "query_result": value,
  }


def write_forward_state(payload: dict[str, Any]) -> None:
  """Persist forward state under `.runtime/`.

  Parameters
  ----------
  payload:
    JSON payload describing current local forward state.
  """
  write_json_file(state_file_path(), payload)


def build_state_payload(
  specs: list[ForwardSpec],
  started_forwards: list[dict[str, Any]],
  verification: dict[str, Any],
) -> dict[str, Any]:
  """Build the `.runtime` state payload for active forwards.

  Parameters
  ----------
  specs:
    Selected forward specifications.
  started_forwards:
    Structured state returned from `start_forward`.
  verification:
    Structured verification results keyed by service key.

  Returns
  -------
  dict[str, Any]
    JSON-ready payload for `.runtime/cloudflared_client_forwards.json`.
  """
  return {
    "specs": [asdict(spec) for spec in specs],
    "forwards": started_forwards,
    "verification": verification,
  }
