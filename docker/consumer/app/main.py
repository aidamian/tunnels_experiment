from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import requests
import websocket
from neo4j import GraphDatabase


LOCALHOST = "127.0.0.1"
BUFFER_SIZE = 64 * 1024

RUN_ID = os.environ.get("RUN_TS", "")
REPORT_PATH = Path(
    os.environ.get(
        "CONSUMER_REPORT_PATH",
        f"/logs/{RUN_ID}_consumer_report.json" if RUN_ID else "/logs/consumer_report.json",
    )
)
CONSUMER_INTERVAL_SECONDS = float(os.environ.get("CONSUMER_INTERVAL_SECONDS", "20"))
CONSUMER_USER_AGENT = os.environ.get("CONSUMER_USER_AGENT", "tunnels-experiment-consumer/1.0")

NEO4J_HTTP_PUBLIC_HOST = os.environ["NEO4J_HTTP_PUBLIC_HOST"]
NEO4J_BOLT_PUBLIC_HOST = os.environ["NEO4J_BOLT_PUBLIC_HOST"]
POSTGRES_PUBLIC_HOST = os.environ["POSTGRES_PUBLIC_HOST"]

NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
POSTGRES_DB = os.environ["POSTGRES_DB"]

SERVICE_TOKEN_ID = os.environ.get("CF_ACCESS_SERVICE_TOKEN_ID", "")
SERVICE_TOKEN_SECRET = os.environ.get("CF_ACCESS_SERVICE_TOKEN_SECRET", "")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def retry(description: str, attempts: int, delay_seconds: float, fn):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - integration-focused retry path
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay_seconds)
    raise RuntimeError(f"{description} failed: {last_error}") from last_error


def build_access_headers() -> dict[str, str]:
    headers = {"User-Agent": CONSUMER_USER_AGENT}
    if SERVICE_TOKEN_ID and SERVICE_TOKEN_SECRET:
        headers["Cf-Access-Client-Id"] = SERVICE_TOKEN_ID
        headers["Cf-Access-Client-Secret"] = SERVICE_TOKEN_SECRET
    return headers


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


class WebSocketTCPBridge:
    def __init__(self, hostname: str, headers: dict[str, str], connect_timeout: float = 20) -> None:
        self.hostname = hostname
        self.headers = headers
        self.connect_timeout = connect_timeout
        self.listener: socket.socket | None = None
        self.client_socket: socket.socket | None = None
        self.ws: websocket.WebSocket | None = None
        self.local_port = 0
        self.stop_event = threading.Event()
        self.server_thread: threading.Thread | None = None
        self.error: Exception | None = None
        self.error_lock = threading.Lock()

    def __enter__(self) -> "WebSocketTCPBridge":
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((LOCALHOST, 0))
        listener.listen(1)
        listener.settimeout(1)
        self.listener = listener
        self.local_port = listener.getsockname()[1]
        self.server_thread = threading.Thread(target=self._serve, name=f"ws-bridge-{self.hostname}", daemon=True)
        self.server_thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop_event.set()
        self._close_listener()
        self._close_client()
        self._close_websocket()
        if self.server_thread is not None:
            self.server_thread.join(timeout=5)

    def raise_if_failed(self) -> None:
        if self.error is not None:
            raise RuntimeError(f"{self.hostname} bridge failed: {self.error}") from self.error

    def _set_error(self, exc: Exception) -> None:
        with self.error_lock:
            if self.error is None:
                self.error = exc

    def _close_listener(self) -> None:
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
            self.listener = None

    def _close_client(self) -> None:
        if self.client_socket is not None:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.client_socket.close()
            except OSError:
                pass
            self.client_socket = None

    def _close_websocket(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def _serve(self) -> None:
        try:
            client_socket = self._accept_client()
            if client_socket is None:
                return
            self.client_socket = client_socket
            headers = [f"{key}: {value}" for key, value in self.headers.items()]
            self.ws = websocket.create_connection(
                f"wss://{self.hostname}",
                header=headers,
                timeout=self.connect_timeout,
                enable_multithread=True,
            )

            upstream = threading.Thread(
                target=self._socket_to_websocket,
                name=f"sock-to-ws-{self.hostname}",
                daemon=True,
            )
            downstream = threading.Thread(
                target=self._websocket_to_socket,
                name=f"ws-to-sock-{self.hostname}",
                daemon=True,
            )
            upstream.start()
            downstream.start()
            upstream.join()
            downstream.join()
        except Exception as exc:  # pragma: no cover - integration-oriented transport path
            if not self.stop_event.is_set():
                self._set_error(exc)
        finally:
            self.stop_event.set()
            self._close_websocket()
            self._close_client()
            self._close_listener()

    def _accept_client(self) -> socket.socket | None:
        assert self.listener is not None
        while not self.stop_event.is_set():
            try:
                client_socket, _ = self.listener.accept()
                client_socket.settimeout(1)
                return client_socket
            except TimeoutError:
                continue
            except OSError as exc:
                if self.stop_event.is_set():
                    return None
                raise exc
        return None

    def _socket_to_websocket(self) -> None:
        assert self.client_socket is not None
        assert self.ws is not None
        try:
            while not self.stop_event.is_set():
                try:
                    data = self.client_socket.recv(BUFFER_SIZE)
                except TimeoutError:
                    continue
                if not data:
                    return
                self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
        except Exception as exc:  # pragma: no cover - integration-oriented transport path
            if not self.stop_event.is_set():
                self._set_error(exc)
        finally:
            self.stop_event.set()
            self._close_websocket()

    def _websocket_to_socket(self) -> None:
        assert self.client_socket is not None
        assert self.ws is not None
        try:
            while not self.stop_event.is_set():
                message = self.ws.recv()
                if message is None:
                    return
                if isinstance(message, str):
                    payload = message.encode("utf-8")
                else:
                    payload = message
                if payload:
                    self.client_socket.sendall(payload)
        except websocket.WebSocketConnectionClosedException:
            if not self.stop_event.is_set():
                self._set_error(RuntimeError("websocket closed unexpectedly"))
        except Exception as exc:  # pragma: no cover - integration-oriented transport path
            if not self.stop_event.is_set():
                self._set_error(exc)
        finally:
            self.stop_event.set()
            self._close_client()


def probe_neo4j_https() -> dict[str, Any]:
    endpoint = f"https://{NEO4J_HTTP_PUBLIC_HOST}/db/neo4j/tx/commit"

    def _query() -> dict[str, Any]:
        response = requests.post(
            endpoint,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            headers={"User-Agent": CONSUMER_USER_AGENT},
            json={
                "statements": [
                    {
                        "statement": (
                            "MATCH (n:TunnelDemo) "
                            "RETURN n.name AS name, n.protocol AS protocol "
                            "ORDER BY name"
                        )
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
            name, protocol = entry["row"]
            rows.append({"name": name, "protocol": protocol})

        return {
            "ok": True,
            "transport": "https",
            "endpoint": endpoint,
            "records": rows,
        }

    return retry("neo4j https probe", 5, 3, _query)


def probe_neo4j_bolt() -> dict[str, Any]:
    def _query() -> dict[str, Any]:
        with WebSocketTCPBridge(NEO4J_BOLT_PUBLIC_HOST, build_access_headers()) as bridge:
            driver = GraphDatabase.driver(
                f"bolt://{LOCALHOST}:{bridge.local_port}",
                auth=(NEO4J_USER, NEO4J_PASSWORD),
            )
            try:
                with driver.session() as session:
                    result = session.run(
                        "MATCH (n:TunnelDemo) RETURN n.name AS name, n.protocol AS protocol ORDER BY name"
                    )
                    rows = [record.data() for record in result]
            finally:
                driver.close()
            bridge.raise_if_failed()

        return {
            "ok": True,
            "transport": "bolt-via-public-websocket-hostname",
            "public_host": NEO4J_BOLT_PUBLIC_HOST,
            "records": rows,
        }

    return retry("neo4j bolt probe", 3, 2, _query)


def probe_postgres() -> dict[str, Any]:
    def _query() -> dict[str, Any]:
        with WebSocketTCPBridge(POSTGRES_PUBLIC_HOST, build_access_headers()) as bridge:
            with psycopg.connect(
                host=LOCALHOST,
                port=bridge.local_port,
                dbname=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                connect_timeout=10,
                sslmode="disable",
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, label, observed_at::text FROM tunnel_demo_items ORDER BY id"
                    )
                    rows = [
                        {"id": row[0], "label": row[1], "observed_at": row[2]}
                        for row in cursor.fetchall()
                    ]
            bridge.raise_if_failed()

        return {
            "ok": True,
            "transport": "postgres-via-public-websocket-hostname",
            "public_host": POSTGRES_PUBLIC_HOST,
            "rows": rows,
        }

    return retry("postgres probe", 3, 2, _query)


def safe_probe(name: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - integration-oriented error path
        return {"ok": False, "error": str(exc), "component": name}


def run_report() -> dict[str, Any]:
    results = {
        "neo4j_https": safe_probe("neo4j_https", probe_neo4j_https),
        "neo4j_bolt": safe_probe("neo4j_bolt", probe_neo4j_bolt),
        "postgres_tcp": safe_probe("postgres_tcp", probe_postgres),
    }
    return {
        "run_id": RUN_ID,
        "timestamp_utc": now_utc(),
        "report_path": str(REPORT_PATH),
        "targets": {
            "neo4j_https": f"https://{NEO4J_HTTP_PUBLIC_HOST}",
            "neo4j_bolt": NEO4J_BOLT_PUBLIC_HOST,
            "postgres_tcp": POSTGRES_PUBLIC_HOST,
        },
        "all_ok": all(result.get("ok") for result in results.values()),
        "results": results,
    }


def run_once() -> dict[str, Any]:
    report = run_report()
    write_json_file(REPORT_PATH, report)
    print(json.dumps(report, indent=2), flush=True)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the public tunnel hostnames and write a report.")
    parser.add_argument("--once", action="store_true", help="run one probe cycle and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.once:
        report = run_once()
        return 0 if report["all_ok"] else 1

    while True:
        run_once()
        time.sleep(CONSUMER_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
