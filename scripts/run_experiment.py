#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import requests
import websocket
from neo4j import GraphDatabase


LOCALHOST = "127.0.0.1"
BUFFER_SIZE = 64 * 1024


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def wait_for_local_port(port: int, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((LOCALHOST, port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"local port {port} did not become reachable in time")


def top_level_published_ports() -> list[str]:
    result = subprocess.run(
        ["docker", "inspect", "dind-host-container", "--format", "{{json .NetworkSettings.Ports}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    payload = json.loads(result.stdout)
    published_ports: list[str] = []
    for container_port, bindings in payload.items():
        if not bindings:
            continue
        for binding in bindings:
            published_ports.append(f"{binding['HostIp']}:{binding['HostPort']}->{container_port}")
    return published_ports


def build_access_headers() -> dict[str, str]:
    headers = {"User-Agent": "tunnels-experiment-host-client/2.0"}
    service_token_id = os.environ.get("CF_ACCESS_SERVICE_TOKEN_ID", "")
    service_token_secret = os.environ.get("CF_ACCESS_SERVICE_TOKEN_SECRET", "")
    if service_token_id and service_token_secret:
        headers["Cf-Access-Client-Id"] = service_token_id
        headers["Cf-Access-Client-Secret"] = service_token_secret
    return headers


def close_socket_quietly(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def close_websocket_quietly(ws: websocket.WebSocket | None) -> None:
    if ws is None:
        return
    try:
        ws.close()
    except Exception:
        pass


def ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((LOCALHOST, port))
        except OSError as exc:
            raise RuntimeError(f"local port {port} is already in use") from exc


@dataclass
class PublishedTcpBridgeServer:
    name: str
    hostname: str
    local_port: int
    run_ts: str
    raw_logs_dir: Path

    def __post_init__(self) -> None:
        self.listener: socket.socket | None = None
        self.server_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.error: Exception | None = None
        self.error_lock = threading.Lock()
        self.log_path = self.raw_logs_dir / f"{self.run_ts}_{self.name}.log"
        self.handler_threads: list[threading.Thread] = []

    def log(self, message: str) -> None:
        self.raw_logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")

    def __enter__(self) -> "PublishedTcpBridgeServer":
        ensure_port_available(self.local_port)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((LOCALHOST, self.local_port))
        listener.listen(5)
        listener.settimeout(1)
        self.listener = listener
        self.server_thread = threading.Thread(target=self._serve, name=f"bridge-{self.name}", daemon=True)
        self.server_thread.start()
        self.log(f"listening on {LOCALHOST}:{self.local_port} for hostname {self.hostname}")
        wait_for_local_port(self.local_port, timeout_seconds=5)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop_event.set()
        close_socket_quietly(self.listener)
        if self.server_thread is not None:
            self.server_thread.join(timeout=5)
        for thread in self.handler_threads:
            thread.join(timeout=5)

    def raise_if_failed(self) -> None:
        if self.error is not None:
            raise RuntimeError(f"{self.name} failed: {self.error}") from self.error

    def _set_error(self, exc: Exception) -> None:
        with self.error_lock:
            if self.error is None:
                self.error = exc
                self.log(f"bridge error: {exc}")

    def _serve(self) -> None:
        assert self.listener is not None
        while not self.stop_event.is_set():
            try:
                client_socket, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stop_event.is_set():
                    return
                raise

            handler = threading.Thread(
                target=self._handle_client,
                args=(client_socket, address),
                name=f"bridge-client-{self.name}",
                daemon=True,
            )
            self.handler_threads.append(handler)
            handler.start()

    def _handle_client(self, client_socket: socket.socket, address: tuple[str, int]) -> None:
        ws: websocket.WebSocket | None = None
        local_stop = threading.Event()
        try:
            self.log(f"accepted client {address[0]}:{address[1]}")
            client_socket.settimeout(1)
            headers = [f"{key}: {value}" for key, value in build_access_headers().items()]
            ws = websocket.create_connection(
                f"wss://{self.hostname}",
                header=headers,
                timeout=20,
                enable_multithread=True,
            )

            upstream = threading.Thread(
                target=self._socket_to_websocket,
                args=(client_socket, ws, local_stop),
                name=f"sock-to-ws-{self.name}",
                daemon=True,
            )
            downstream = threading.Thread(
                target=self._websocket_to_socket,
                args=(client_socket, ws, local_stop),
                name=f"ws-to-sock-{self.name}",
                daemon=True,
            )
            upstream.start()
            downstream.start()
            upstream.join()
            downstream.join()
        except Exception as exc:
            if not self.stop_event.is_set() and not local_stop.is_set():
                self._set_error(exc)
        finally:
            local_stop.set()
            close_websocket_quietly(ws)
            close_socket_quietly(client_socket)

    def _socket_to_websocket(
        self,
        client_socket: socket.socket,
        ws: websocket.WebSocket,
        stop_event: threading.Event,
    ) -> None:
        try:
            while not stop_event.is_set() and not self.stop_event.is_set():
                try:
                    data = client_socket.recv(BUFFER_SIZE)
                except socket.timeout:
                    continue
                if not data:
                    return
                ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
        except Exception as exc:
            if not self.stop_event.is_set() and not stop_event.is_set():
                self._set_error(exc)
        finally:
            stop_event.set()

    def _websocket_to_socket(
        self,
        client_socket: socket.socket,
        ws: websocket.WebSocket,
        stop_event: threading.Event,
    ) -> None:
        try:
            while not stop_event.is_set() and not self.stop_event.is_set():
                message = ws.recv()
                if message is None:
                    return
                payload = message.encode("utf-8") if isinstance(message, str) else message
                if payload:
                    client_socket.sendall(payload)
        except websocket.WebSocketConnectionClosedException:
            if not self.stop_event.is_set() and not stop_event.is_set():
                self._set_error(RuntimeError("websocket closed unexpectedly"))
        except Exception as exc:
            if not self.stop_event.is_set() and not stop_event.is_set():
                self._set_error(exc)
        finally:
            stop_event.set()


def postgres_cycle(env: dict[str, str], run_id: str, cycle: int, proof: str) -> dict[str, Any]:
    port = int(env["HOST_POSTGRES_FORWARD_PORT"])
    with psycopg.connect(
        host=LOCALHOST,
        port=port,
        dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        connect_timeout=10,
        sslmode="disable",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tunnel_run_events (run_id, cycle, client_type, proof)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (run_id, cycle, client_type)
                DO UPDATE SET proof = EXCLUDED.proof, observed_at = now()
                RETURNING id, observed_at::text
                """,
                (run_id, cycle, "dbeaver-sim", proof),
            )
            inserted_id, observed_at = cursor.fetchone()
            cursor.execute(
                """
                SELECT id, cycle, client_type, proof, observed_at::text
                FROM tunnel_run_events
                WHERE run_id = %s
                ORDER BY cycle, id
                """,
                (run_id,),
            )
            rows = [
                {
                    "id": row[0],
                    "cycle": row[1],
                    "client_type": row[2],
                    "proof": row[3],
                    "observed_at": row[4],
                }
                for row in cursor.fetchall()
            ]
        connection.commit()

    return {
        "ok": True,
        "inserted_id": inserted_id,
        "inserted_at": observed_at,
        "rows_for_run": rows,
    }


def neo4j_bolt_cycle(env: dict[str, str], run_id: str, cycle: int, proof: str) -> dict[str, Any]:
    port = int(env["HOST_NEO4J_BOLT_FORWARD_PORT"])
    event_id = f"{run_id}-cycle-{cycle}"

    driver = GraphDatabase.driver(
        f"bolt://{LOCALHOST}:{port}",
        auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
    )
    try:
        with driver.session() as session:
            write_result = session.run(
                """
                MERGE (run:ExperimentRun {runId: $run_id})
                ON CREATE SET run.createdAt = datetime()
                MERGE (client:BoltClient {name: 'external-bolt-app'})
                MERGE (event:ExperimentEvent {eventId: $event_id})
                SET event.cycle = $cycle,
                    event.proof = $proof,
                    event.updatedAt = datetime()
                MERGE (run)-[:CONTAINS]->(event)
                MERGE (client)-[:WROTE_EVENT]->(event)
                RETURN run.runId AS run_id, event.eventId AS event_id, event.cycle AS cycle, event.proof AS proof
                """,
                run_id=run_id,
                event_id=event_id,
                cycle=cycle,
                proof=proof,
            ).single()

            read_result = session.run(
                """
                MATCH (:BoltClient {name: 'external-bolt-app'})-[:WROTE_EVENT]->(event:ExperimentEvent)
                MATCH (:ExperimentRun {runId: $run_id})-[:CONTAINS]->(event)
                RETURN event.eventId AS event_id, event.cycle AS cycle, event.proof AS proof, toString(event.updatedAt) AS updated_at
                ORDER BY event.cycle
                """,
                run_id=run_id,
            )
            rows = [record.data() for record in read_result]
    finally:
        driver.close()

    return {
        "ok": True,
        "write_result": dict(write_result),
        "events_for_run": rows,
    }


def neo4j_https_read(env: dict[str, str], run_id: str) -> dict[str, Any]:
    endpoint = f"https://{env['NEO4J_HTTP_PUBLIC_HOST']}/db/neo4j/tx/commit"
    response = requests.post(
        endpoint,
        auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
        headers={"User-Agent": "tunnels-experiment-host-client/2.0"},
        json={
            "statements": [
                {
                    "statement": """
                        MATCH (:ExperimentRun {runId: $run_id})-[:CONTAINS]->(event:ExperimentEvent)
                        RETURN event.eventId AS event_id, event.cycle AS cycle, event.proof AS proof, toString(event.updatedAt) AS updated_at
                        ORDER BY event.cycle
                    """,
                    "parameters": {"run_id": run_id},
                }
            ]
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"]))

    rows = []
    for entry in payload["results"][0]["data"]:
        event_id, cycle, proof, updated_at = entry["row"]
        rows.append(
            {
                "event_id": event_id,
                "cycle": cycle,
                "proof": proof,
                "updated_at": updated_at,
            }
        )

    return {
        "ok": True,
        "endpoint": endpoint,
        "events_for_run": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the host-side tunnel experiment.")
    parser.add_argument("--run-ts", help="specific run identifier to use")
    parser.add_argument("--duration-seconds", type=int, help="total experiment duration")
    parser.add_argument("--cycle-interval-seconds", type=int, help="delay between cycles")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    env = load_env_file(repo_root / ".runtime" / "tunnels.env")
    run_id = args.run_ts or env["RUN_TS"]
    duration_seconds = args.duration_seconds or int(env["EXPERIMENT_DURATION_SECONDS"])
    cycle_interval_seconds = args.cycle_interval_seconds or int(env["EXPERIMENT_CYCLE_INTERVAL_SECONDS"])
    raw_logs_dir = repo_root / "_logs" / "raw"
    report_path = raw_logs_dir / f"{run_id}_experiment_report.json"
    topology = {
        "top_level_container": "dind-host-container",
        "managed_service_containers": ["neo4j-demo", "postgres-demo"],
        "local_origins_inside_dind_host": {
            "neo4j_https": "127.0.0.1:17474",
            "neo4j_bolt": "127.0.0.1:17687",
            "postgres_tcp": "127.0.0.1:15432",
        },
        "top_level_published_ports": top_level_published_ports(),
        "public_hosts": {
            "neo4j_https": env["NEO4J_HTTP_PUBLIC_HOST"],
            "neo4j_bolt": env["NEO4J_BOLT_PUBLIC_HOST"],
            "postgres_tcp": env["POSTGRES_PUBLIC_HOST"],
        },
    }

    results: dict[str, Any] = {
        "neo4j_https": {"ok": False},
        "neo4j_bolt_tunnel": {"ok": False},
        "postgres_tunnel": {"ok": False},
    }
    cycle_results: list[dict[str, Any]] = []
    experiment_error: str | None = None

    try:
        with PublishedTcpBridgeServer(
            name="postgres_client_bridge",
            hostname=env["POSTGRES_PUBLIC_HOST"],
            local_port=int(env["HOST_POSTGRES_FORWARD_PORT"]),
            run_ts=run_id,
            raw_logs_dir=raw_logs_dir,
        ) as postgres_bridge, PublishedTcpBridgeServer(
            name="neo4j_bolt_client_bridge",
            hostname=env["NEO4J_BOLT_PUBLIC_HOST"],
            local_port=int(env["HOST_NEO4J_BOLT_FORWARD_PORT"]),
            run_ts=run_id,
            raw_logs_dir=raw_logs_dir,
        ) as neo4j_bridge:
            print(f"run_id={run_id}")
            print(f"postgres local bridge: {LOCALHOST}:{env['HOST_POSTGRES_FORWARD_PORT']}")
            print(f"neo4j bolt local bridge: {LOCALHOST}:{env['HOST_NEO4J_BOLT_FORWARD_PORT']}")
            print(f"neo4j https public endpoint: https://{env['NEO4J_HTTP_PUBLIC_HOST']}")

            start_time = time.monotonic()
            cycle = 0
            while True:
                cycle += 1
                postgres_bridge.raise_if_failed()
                neo4j_bridge.raise_if_failed()

                proof = f"{run_id}-cycle-{cycle}-{datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')}"
                print(f"cycle {cycle}: writing proof {proof}")

                postgres_result = postgres_cycle(env, run_id, cycle, proof)
                neo4j_bolt_result = neo4j_bolt_cycle(env, run_id, cycle, proof)
                neo4j_https_result = neo4j_https_read(env, run_id)

                results["postgres_tunnel"] = postgres_result
                results["neo4j_bolt_tunnel"] = neo4j_bolt_result
                results["neo4j_https"] = neo4j_https_result
                cycle_results.append(
                    {
                        "cycle": cycle,
                        "proof": proof,
                        "postgres_rows_seen": len(postgres_result["rows_for_run"]),
                        "neo4j_bolt_events_seen": len(neo4j_bolt_result["events_for_run"]),
                        "neo4j_https_events_seen": len(neo4j_https_result["events_for_run"]),
                    }
                )

                print(json.dumps(cycle_results[-1], indent=2), flush=True)

                elapsed = time.monotonic() - start_time
                if cycle >= 3 and elapsed >= duration_seconds:
                    break

                sleep_seconds = min(cycle_interval_seconds, max(0.0, duration_seconds - elapsed))
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    except Exception as exc:
        experiment_error = str(exc)

    report = {
        "run_id": run_id,
        "timestamp_utc": now_utc(),
        "duration_seconds": duration_seconds,
        "cycle_interval_seconds": cycle_interval_seconds,
        "cycles_completed": len(cycle_results),
        "topology": topology,
        "local_client_forwards": {
            "postgres": f"{LOCALHOST}:{env['HOST_POSTGRES_FORWARD_PORT']}",
            "neo4j_bolt": f"{LOCALHOST}:{env['HOST_NEO4J_BOLT_FORWARD_PORT']}",
        },
        "log_files": {
            "postgres_bridge": str(raw_logs_dir / f"{run_id}_postgres_client_bridge.log"),
            "neo4j_bolt_bridge": str(raw_logs_dir / f"{run_id}_neo4j_bolt_client_bridge.log"),
        },
        "cycle_results": cycle_results,
        "results": results,
        "error": experiment_error,
        "all_ok": (
            experiment_error is None
            and topology["top_level_published_ports"] == []
            and len(cycle_results) >= 3
            and results["postgres_tunnel"].get("ok") is True
            and results["neo4j_bolt_tunnel"].get("ok") is True
            and results["neo4j_https"].get("ok") is True
        ),
    }
    write_json_file(report_path, report)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
