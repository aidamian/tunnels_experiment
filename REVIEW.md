# REVIEW.md

## Critic Checklist
Run this checklist after every milestone and before declaring the demo complete.

### Secrets
- No tunnel token appears in tracked files, command output summaries, or markdown.
- `.runtime/` remains ignored.

### Topology
- Exactly three top-level DinD roles exist: `master`, `embedded-neo4j`, `embedded-postgres`.
- Neo4j and PostgreSQL run as child containers, not as direct top-level services.
- The consumer app runs as a child container inside `master`.

### Tunnel mapping
- tunnel 1 -> Neo4j HTTPS
- tunnel 2 -> Neo4j Bolt/TCP
- tunnel 3 -> PostgreSQL TCP
- tunnel 4 -> optional diagnostic use only

### Functional proof
- Neo4j HTTPS path is verified by a real query over the public hostname.
- Neo4j Bolt path is verified by the Python consumer over `99c7e7089d1b.ratio1.link` plus a real driver query.
- PostgreSQL path is verified by the Python consumer over `60bf15690490.ratio1.link` plus a real SQL query.
- The consumer image contains no `cloudflared` binary or equivalent external tunnel helper.
- The latest generated consumer report shows all checks healthy.

### Operational quality
- Compose config validates.
- Container health checks are meaningful.
- Logs exist under `_logs/` with the required timestamp prefix.
- `DOCUMENTATION.md` matches the actual verified runtime.
