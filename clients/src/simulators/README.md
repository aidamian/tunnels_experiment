# `clients/src/simulators`

Service-specific proof logic used by the host-side client.

- `postgres.py`
  - PostgreSQL write/read proof and manual bridge verification
- `neo4j_bolt.py`
  - Neo4j Bolt write/read proof and manual bridge verification
- `neo4j_https.py`
  - Neo4j HTTPS read proof

These modules are intentionally separate from the bridge transport layer and from server orchestration.
