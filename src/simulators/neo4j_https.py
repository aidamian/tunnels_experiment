"""Neo4j HTTPS proof workload for the host-side experiment."""

from __future__ import annotations

import json
from typing import Any

from utils.dependencies import get_requests_module


def run_neo4j_https_read(env: dict[str, str], run_id: str) -> dict[str, Any]:
  """Read the run's Neo4j graph proof through the public HTTPS endpoint.

  Parameters
  ----------
  env:
    Parsed runtime environment.
  run_id:
    Current run identifier used to select experiment data.

  Returns
  -------
  dict[str, Any]
    Structured result containing the endpoint and the events returned.
  """
  requests = get_requests_module()

  # This path does not need a local bridge because Neo4j's HTTP API is exposed
  # as a normal HTTPS application at the Cloudflare edge.
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
        },
      ],
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
      },
    )

  return {
    "ok": True,
    "endpoint": endpoint,
    "events_for_run": rows,
  }
