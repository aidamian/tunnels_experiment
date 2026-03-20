"""Neo4j Bolt proof workload for the host-side experiment."""

from __future__ import annotations

from typing import Any

from bridge.universal import LOCALHOST
from utils.demo_config import NEO4J_PASSWORD, NEO4J_USER
from utils.dependencies import get_graph_database_class


def run_neo4j_bolt_cycle(run_id: str, cycle: int, proof: str, local_port: int) -> dict[str, Any]:
  """Run one Neo4j Bolt write/read proof cycle.

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
