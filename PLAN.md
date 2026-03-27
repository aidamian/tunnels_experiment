# PLAN.md

## Goal

Extend the repository from a two-world split (`servers/` and `clients/`) into a three-world split:

- `servers/`
  - origin DinD host and origin tunnels
- `apps/`
  - consumer DinD host, local bridge, and app HTTPS UI tunnel
- `clients/`
  - real-machine Python proof client

## Current Target Layout

```text
.
|-- start_e2e.sh
|-- start_host.sh
|-- start_apps.sh
|-- clients/
|-- servers/
|-- apps/
|-- shared/
`-- _logs/
```

## Active Design Rules

1. `servers/`, `apps/`, and `clients/` each own their own runtime env and raw logs.
2. Root scripts may pass derived values between worlds, but worlds do not read one another’s runtime folders directly.
3. Neutral reusable code belongs under `shared/`, not as duplicated implementations under world-owned paths.
4. Server service startup is selective through `ENABLED_SERVICES`.
5. Tunnel role assignments stay fixed:
   - tunnel 1: Neo4j HTTPS
   - tunnel 2: Neo4j Bolt/TCP
   - tunnel 3: PostgreSQL TCP
   - tunnel 4: app HTTPS UI
6. The app host must reach PostgreSQL through its local Python bridge, not through direct host-port publishing or shared Docker networking between the two top-level DinD hosts.

## Validation Targets

- `bash -n start_e2e.sh start_host.sh start_apps.sh`
- `python3 -m compileall shared/src clients/src servers/src apps/src`
- `./start_e2e.sh --duration-seconds 1`
- `./start_apps.sh --keep-up`
- `python3 apps/src/utils/verify_public_ui.py --run-ts <RUN_TS> --timeout-seconds 10`
