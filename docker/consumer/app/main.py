from __future__ import annotations

import html
import json
import os
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase


LOCALHOST = "127.0.0.1"
NEO4J_HTTP_PUBLIC_HOST = os.environ["NEO4J_HTTP_PUBLIC_HOST"]
NEO4J_BOLT_PUBLIC_HOST = os.environ["NEO4J_BOLT_PUBLIC_HOST"]
POSTGRES_PUBLIC_HOST = os.environ["POSTGRES_PUBLIC_HOST"]
CONSUMER_HTTP_PUBLIC_HOST = os.environ.get("CONSUMER_HTTP_PUBLIC_HOST", "")

NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
POSTGRES_DB = os.environ["POSTGRES_DB"]

NEO4J_BOLT_PROXY_PORT = int(os.environ.get("NEO4J_BOLT_PROXY_PORT", "17687"))
POSTGRES_PROXY_PORT = int(os.environ.get("POSTGRES_PROXY_PORT", "15432"))

SERVICE_TOKEN_ID = os.environ.get("CF_ACCESS_SERVICE_TOKEN_ID", "")
SERVICE_TOKEN_SECRET = os.environ.get("CF_ACCESS_SERVICE_TOKEN_SECRET", "")

app = FastAPI(title="Tunnel Consumer Demo")


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


@contextmanager
def cloudflared_tcp_proxy(hostname: str, local_port: int):
    log_path = Path(tempfile.mkdtemp(prefix="cloudflared-proxy-")) / f"{local_port}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    command = [
        "cloudflared",
        "access",
        "tcp",
        "--hostname",
        hostname,
        "--url",
        f"{LOCALHOST}:{local_port}",
        "--log-level",
        "info",
    ]
    if SERVICE_TOKEN_ID and SERVICE_TOKEN_SECRET:
        command.extend(
            [
                "--service-token-id",
                SERVICE_TOKEN_ID,
                "--service-token-secret",
                SERVICE_TOKEN_SECRET,
            ]
        )

    process = subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if process.poll() is not None:
                break
            try:
                with socket.create_connection((LOCALHOST, local_port), timeout=0.5):
                    yield
                    return
            except OSError:
                time.sleep(0.25)

        details = log_path.read_text(encoding="utf-8").strip()
        raise RuntimeError(f"failed to start cloudflared tcp proxy for {hostname}: {details or 'no log output'}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
                process.kill()
                process.wait(timeout=5)
        log_handle.close()


def probe_neo4j_https() -> dict[str, Any]:
    endpoint = f"https://{NEO4J_HTTP_PUBLIC_HOST}/db/neo4j/tx/commit"

    def _query() -> dict[str, Any]:
        response = requests.post(
            endpoint,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
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
        with cloudflared_tcp_proxy(NEO4J_BOLT_PUBLIC_HOST, NEO4J_BOLT_PROXY_PORT):
            driver = GraphDatabase.driver(
                f"bolt://{LOCALHOST}:{NEO4J_BOLT_PROXY_PORT}",
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

        return {
            "ok": True,
            "transport": "bolt-via-cloudflared-access-tcp",
            "public_host": NEO4J_BOLT_PUBLIC_HOST,
            "records": rows,
        }

    return retry("neo4j bolt probe", 3, 2, _query)


def probe_postgres() -> dict[str, Any]:
    def _query() -> dict[str, Any]:
        with cloudflared_tcp_proxy(POSTGRES_PUBLIC_HOST, POSTGRES_PROXY_PORT):
            with psycopg.connect(
                host=LOCALHOST,
                port=POSTGRES_PROXY_PORT,
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

        return {
            "ok": True,
            "transport": "postgres-via-cloudflared-access-tcp",
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
        "timestamp_utc": now_utc(),
        "consumer_public_url": f"https://{CONSUMER_HTTP_PUBLIC_HOST}" if CONSUMER_HTTP_PUBLIC_HOST else "",
        "targets": {
            "neo4j_https": f"https://{NEO4J_HTTP_PUBLIC_HOST}",
            "neo4j_bolt": NEO4J_BOLT_PUBLIC_HOST,
            "postgres_tcp": POSTGRES_PUBLIC_HOST,
        },
        "all_ok": all(result.get("ok") for result in results.values()),
        "results": results,
    }


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "timestamp_utc": now_utc(),
        "consumer_public_url": f"https://{CONSUMER_HTTP_PUBLIC_HOST}" if CONSUMER_HTTP_PUBLIC_HOST else "",
    }


@app.get("/report")
def report() -> dict[str, Any]:
    return run_report()


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    report_payload = run_report()
    rows = []
    for component, details in report_payload["results"].items():
        status = "OK" if details.get("ok") else "FAILED"
        summary = html.escape(json.dumps(details, indent=2))
        rows.append(
            "<tr>"
            f"<td>{html.escape(component)}</td>"
            f"<td>{status}</td>"
            f"<td><pre>{summary}</pre></td>"
            "</tr>"
        )

    body = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <title>Tunnel Consumer Demo</title>
        <style>
          body {{
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            margin: 2rem;
            background: #f4f1ea;
            color: #1d1d1d;
          }}
          table {{
            border-collapse: collapse;
            width: 100%;
          }}
          th, td {{
            border: 1px solid #222;
            vertical-align: top;
            padding: 0.75rem;
          }}
          th {{
            background: #ddd4c7;
          }}
          pre {{
            white-space: pre-wrap;
            margin: 0;
          }}
        </style>
      </head>
      <body>
        <h1>Tunnel Consumer Demo</h1>
        <p>Timestamp (UTC): {html.escape(report_payload["timestamp_utc"])}</p>
        <p>Public consumer URL: {html.escape(report_payload["consumer_public_url"])}</p>
        <p>All checks healthy: {report_payload["all_ok"]}</p>
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Status</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
      </body>
    </html>
    """
    return HTMLResponse(body)
