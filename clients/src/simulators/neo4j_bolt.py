"""Neo4j Bolt proof workload for the host-side experiment."""

from __future__ import annotations

from typing import Any

from utils.demo_config import NEO4J_PASSWORD, NEO4J_USER
from utils.dependencies import get_graph_database_class
from utils.services import LOCALHOST


def run_neo4j_bolt_cycle(run_id: str, cycle: int, proof: str, local_port: int) -> dict[str, Any]:
  """Run one Neo4j Bolt write/read proof cycle.

  The function simulates a real external Bolt client by connecting to the
  host-side local Bolt bridge, writing graph proof data, and then reading the
  run's events back over the same Bolt path.

  Parameters
  ----------
  run_id:
    Current run identifier.
  cycle:
    Current proof cycle number.
  proof:
    Unique proof string for this cycle.
  local_port:
    Localhost TCP port exposed by the host-side Neo4j Bolt bridge.

  Returns
  -------
  dict[str, Any]
    Structured result containing the write result and all events for the run.

  Examples
  --------
  After the Neo4j Bolt bridge is listening on ``127.0.0.1:17687``:

  >>> result = run_neo4j_bolt_cycle("demo_run", 1, "demo-proof", 17687)
  >>> result["ok"]
  True
  """
  GraphDatabase = get_graph_database_class()

  # Simulate an external Bolt-capable application by connecting to the local
  # bridge port on the real machine and running normal Neo4j driver operations.
  event_id = f"{run_id}-cycle-{cycle}"

  driver = GraphDatabase.driver(
    f"bolt://{LOCALHOST}:{local_port}",
    auth=(NEO4J_USER, NEO4J_PASSWORD),
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


def verify_neo4j_bolt_bridge(local_port: int) -> dict[str, Any]:
  """Verify basic Neo4j Bolt connectivity through the host-side bridge.

  This lighter-weight check is used by the manual bridge CLI. It proves that a
  Bolt client can complete a minimal query round trip through the local bridge
  without mutating the experiment graph.

  Parameters
  ----------
  local_port:
    Localhost TCP port exposed by the host-side Neo4j Bolt bridge.

  Returns
  -------
  dict[str, Any]
    Verification payload containing success state and query result.

  Examples
  --------
  After the manual Neo4j Bolt bridge is listening on ``127.0.0.1:57687``:

  >>> result = verify_neo4j_bolt_bridge(57687)
  >>> result["query_result"]
  1
  """
  GraphDatabase = get_graph_database_class()

  driver = GraphDatabase.driver(
    f"bolt://{LOCALHOST}:{local_port}",
    auth=(NEO4J_USER, NEO4J_PASSWORD),
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
