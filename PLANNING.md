# PLANNING.md

## Objective
Build a reproducible demo showing that services running inside nested container environments can be exposed to outside consumers through Cloudflare Tunnel, then consumed by a Python application through the provided public hostnames.

## Inputs And Constraints
- Runtime tunnel secrets live in `tunnels.json` and must stay untracked.
- The project must use at least three top-level containers: one master and two embedded DinD nodes.
- The master node must run the Python consumer app as a child container.
- The two embedded nodes must run Neo4j and PostgreSQL as child containers.
- Logging must go to `_logs/` with `YYMMDD_HHMMSS_` prefixes.
- `_logs/*.log` files are runtime artifacts and must remain untracked.
- `_logs/*.md` files are tracked summaries.

## Primary-Source Findings
### Codex workflow
- OpenAI’s Codex long-horizon guidance emphasizes durable project memory in markdown files, a milestone plan, an implementation runbook, continuous verification, and status documentation.
- Codex’s documented loop is plan -> edit -> run tools -> observe -> repair -> update docs -> repeat.
- `AGENTS.md` files are read before work starts, merged from global scope down to the working directory, and should stay concise because combined project instructions are capped.
- Subagents are useful when explicitly requested, but noisy parallel work should be summarized back into the main thread instead of copied raw.

### Cloudflare Tunnel
- Cloudflare Tunnel uses outbound-only connections from `cloudflared` to the Cloudflare edge.
- Public hostnames can route HTTPS, TCP, and other protocols to private origins behind `cloudflared`.
- Non-HTTP published applications require client-side `cloudflared` for end-user connections. For raw TCP, the documented client flow is `cloudflared access tcp --hostname ... --url localhost:PORT`.
- The local `cloudflared` CLI confirms that a named tunnel can be started from a token with `cloudflared tunnel run --token ... --url ...`, which fits the provided `tunnels.json` inputs.

### Database containers
- Neo4j’s standard public interfaces for this demo are HTTP on `7474` and Bolt on `7687`.
- The official PostgreSQL image requires `POSTGRES_PASSWORD`; `POSTGRES_USER` and `POSTGRES_DB` are optional but useful for deterministic setup.
- PostgreSQL is not an HTTPS service. For this project it should be demonstrated over a Cloudflare TCP tunnel, not by pretending it is HTTP.

## Architecture
### Top-level services
1. `master`
   - Docker-in-Docker container.
   - Runs its own Docker daemon.
   - Builds and starts the Python consumer app as a child container.
   - Exposes the consumer app over tunnel 4.
   - Periodically snapshots the two embedded DinD daemons to prove the master role is observability/control, not just a placeholder.

2. `embedded-neo4j`
   - Docker-in-Docker container.
   - Runs Neo4j as a child container.
   - Publishes Neo4j’s internal ports to the DinD host loopback.
   - Starts two `cloudflared tunnel run --token --url ...` processes:
     - tunnel 1 -> `http://127.0.0.1:17474`
     - tunnel 2 -> `tcp://127.0.0.1:17687`

3. `embedded-postgres`
   - Docker-in-Docker container.
   - Runs PostgreSQL as a child container.
   - Publishes PostgreSQL to the DinD host loopback on `127.0.0.1:15432`.
   - Starts one `cloudflared tunnel run --token --url tcp://127.0.0.1:15432` process using tunnel 3.

### Child containers
- `neo4j-demo` inside `embedded-neo4j`
- `postgres-demo` inside `embedded-postgres`
- `consumer-demo` inside `master`

### Tunnel assignment
1. Tunnel 1 -> Neo4j HTTPS endpoint
2. Tunnel 2 -> Neo4j Bolt endpoint
3. Tunnel 3 -> PostgreSQL TCP endpoint
4. Tunnel 4 -> Consumer app HTTP endpoint

### Consumer behavior
The Python consumer app will prove three access paths:
1. Neo4j over public HTTPS by calling the transactional HTTP endpoint through the public hostname.
2. Neo4j over Bolt by starting a short-lived local `cloudflared access tcp` forwarder and then using the Neo4j Python driver against that local port.
3. PostgreSQL over TCP by starting a short-lived local `cloudflared access tcp` forwarder and then using `psycopg` against that local port.

The consumer app will expose:
- `/healthz`: lightweight local health endpoint.
- `/report`: live JSON probe report.
- `/`: human-readable HTML summary for outside viewers.

## Demo Flow
1. Generate `.runtime/tunnels.env` from `tunnels.json`.
2. Start the top-level DinD services with Docker Compose.
3. Each DinD service starts its child container(s) and tunnel processes.
4. The public consumer URL becomes available through tunnel 4.
5. An outside user visits the public consumer URL.
6. The consumer app performs live checks against the three service tunnels and returns a report showing success or failure for each path.

## Milestones
### Milestone 1: Repo scaffolding and durable-memory files
Acceptance criteria:
- `AGENTS.md`, `PLANNING.md`, `IMPLEMENTATION.md`, `REVIEW.md`, and `DOCUMENTATION.md` exist.
- `.dockerignore`, `.gitignore`, and helper scripts define secret-safe runtime behavior.

Validation:
- `python3 scripts/prepare_runtime.py`

### Milestone 2: Nested container orchestration
Acceptance criteria:
- `docker-compose.yml` defines the three top-level DinD services.
- `docker/dind/start-role.sh` can start Docker, launch the child service container for each role, seed the database state, and launch the tunnel processes.

Validation:
- `docker compose config`

### Milestone 3: Consumer app
Acceptance criteria:
- Consumer app can query Neo4j over HTTPS and via Bolt.
- Consumer app can query PostgreSQL over TCP.
- Consumer app returns a clear JSON and HTML report.

Validation:
- `docker compose up --build -d`
- `docker compose logs --tail=100 master`
- `curl -fsS http://127.0.0.1:18000/healthz`

### Milestone 4: Public tunnel proof
Acceptance criteria:
- The consumer public hostname responds over HTTPS.
- `/report` shows all three checks as healthy.
- The outside-consumer path uses the provided Cloudflare URLs, not local shortcuts.

Validation:
- `python3 scripts/smoke_test.py`

### Milestone 5: Documentation and demo readiness
Acceptance criteria:
- `DOCUMENTATION.md` includes current status, run commands, demo steps, and known limits.
- A timestamped `_logs/*.md` summary captures the finished iteration.

Validation:
- Review markdown files for consistency with the verified runtime.

## Success Criteria
The demo is successful when:
- all three top-level DinD containers are running;
- the Neo4j HTTPS public hostname answers transactional queries successfully;
- the Neo4j Bolt public hostname can be consumed through client-side `cloudflared access tcp`;
- the PostgreSQL public hostname can be consumed through client-side `cloudflared access tcp`;
- the public consumer URL presents a healthy report derived from those real tunnel checks.

## Risks And Mitigations
- Tunnel startup delay:
  - Mitigation: health checks and smoke-test retries.
- Cloudflare TCP client behavior may vary if Access policies are present:
  - Mitigation: the consumer app uses the documented `cloudflared access tcp` flow and surfaces any proxy startup error explicitly.
- Nested Docker can fail if privileged mode is missing:
  - Mitigation: use `privileged: true`, dedicated Docker data volumes, and DinD-specific health checks.
- Database cold start can exceed naive timeouts:
  - Mitigation: explicit readiness polling before seeding and before starting dependent roles.

## Sources
- OpenAI Codex AGENTS guidance: https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex subagents: https://developers.openai.com/codex/concepts/subagents
- OpenAI long-horizon Codex workflow: https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
- OpenAI skills, shell, and compaction: https://developers.openai.com/blog/skills-shell-tips
- Cloudflare Tunnel overview: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- Cloudflare published application protocols: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/
- Cloudflare arbitrary TCP with client-side `cloudflared`: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/
- PostgreSQL official image reference: https://hub.docker.com/_/postgres
