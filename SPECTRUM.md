# SPECTRUM.md

## Purpose
This document is the actionable Plan B for replacing the client-side Python
bridge with a Cloudflare-native direct TCP design:

```text
Native client
-> Spectrum hostname and port
-> Cloudflare Spectrum
-> Cloudflare Load Balancer
-> Tunnel/VNet private-network off-ramp
-> PostgreSQL or Neo4j Bolt origin
```

The goal is strict no-helper access:

- native PostgreSQL to `pg.<domain>:5432`
- native Bolt to `neo4j-bolt.<domain>:7687`
- no local bridge
- no client-side `cloudflared`
- no WARP requirement

## Why This Is The Right Plan

Published Cloudflare Tunnel TCP applications do not expose a native public TCP
socket. Spectrum does.

For this repository, the useful Cloudflare-native target is not:

- Spectrum -> current published Tunnel TCP hostname

but:

- Spectrum -> Load Balancer -> private endpoint reached through Tunnel/VNet

This preserves the current "private origin" intent while removing the client
bridge.

## Initial Prerequisites

This section is intentionally strict. If these items are not available, the
agent should not start implementation work.

### User-owned prerequisites

1. Confirm the account and zone have all required products enabled:
   - Spectrum
   - Load Balancing
   - Cloudflare Tunnel
   - Zero Trust private networking / Virtual Networks
2. Confirm with Cloudflare support or the account team that the intended shape
   is supported for the target account:
   - Spectrum as the public TCP on-ramp
   - Load Balancer between Spectrum and origin
   - Tunnel/VNet as the private off-ramp
   - target protocols:
     - PostgreSQL on `5432`
     - Neo4j Bolt on `7687`
3. Provide a Cloudflare API token with the required scopes.
4. Provide the Cloudflare account and zone identifiers.
5. Approve the final public hostnames and TLS policy.

### User step-by-step instructions

Follow these steps in order. Do not skip ahead.

1. Log in to the Cloudflare dashboard using an account with admin-level access
   to the target account and zone.
2. Open the target zone that will host the final public names.
   - Example:
     - `example.com`
3. Verify the zone is actually managed by Cloudflare.
   - The zone must already exist in Cloudflare and be active.
   - If it is not active, stop here.
4. Check that the required products are visible and enabled.
   - In the target zone, confirm you can find:
     - Spectrum
     - Load Balancing
   - In the Cloudflare dashboard and Zero Trust dashboard, confirm you can
     find the Tunnel and private-network areas mentioned in the current docs:
     - main dashboard:
       - `Networking -> Tunnels`
     - Zero Trust dashboard:
       - `Networks -> Connectors -> Cloudflare Tunnels`
       - `Settings -> WARP Client -> Virtual networks`
   - If any of those are missing, stop here and ask the account owner or
     Cloudflare account team to enable them.
5. If Zero Trust private networking has never been initialized on this account,
   complete that one-time setup first.
   - Do not continue until the Tunnels and Virtual networks areas are visible.
6. Send the support/account-team confirmation request before implementation.
   - Use the exact text from `Exact Support Question To Send` later in this
     document.
   - Wait for a clear confirmation that this product shape is supported for
     PostgreSQL on `5432` and Neo4j Bolt on `7687`.
   - Explicitly ask support to confirm that the Spectrum options needed by this
     design are available on your current plan. Cloudflare's current
     `Settings by plan` docs mark several Spectrum fields as Enterprise-only.
   - If support does not confirm, stop here.
7. Copy the Cloudflare account ID.
   - Follow the current Cloudflare doc path:
     - go to `Account home`
     - locate your account
     - open the menu button at the end of the account row
     - select `Copy account ID`
   - Save it somewhere local and private.
8. Copy the zone ID for the target zone.
   - Follow the current Cloudflare doc path:
     - go to `Account home`
     - open the target account overview
     - scroll to the `API` section near the bottom
     - under `Zone ID`, select `Click to copy`
   - Save it somewhere local and private.
9. Decide the final public hostnames.
   - Recommended:
     - PostgreSQL: `pg.<zone>`
     - Neo4j Bolt: `neo4j-bolt.<zone>`
   - Example:
     - `pg.example.com`
     - `neo4j-bolt.example.com`
10. Decide the initial TLS mode.
    - Recommended for the first proof:
      - `off`
    - That keeps the first implementation focused on raw TCP reachability.
11. Create a dedicated API token for this project.
    - First decide which token type to create:
      - preferred if available:
        - account-owned token
      - fallback:
        - user token
    - Use an account-owned token if:
      - you are a `Super Administrator`
      - and your organization allows account-owned tokens
      - and you want a durable service token not tied to one user
    - Otherwise create a normal user token.
    - Current Cloudflare doc paths:
      - account-owned token:
        - `Manage Account -> Account API Tokens`
      - user token:
        - `My Profile -> API Tokens`
    - Select:
      - `Create Token`
      - then create a custom token
    - Give it a clear name, for example:
      - `tunnels-experiment-spectrum-plan-b`
    - Add the permissions listed in `Recommended token scopes` below.
    - Restrict the token to:
      - the correct account
      - the correct zone
    - Leave optional IP filtering and TTL restrictions empty for the first
      setup unless you have a specific security requirement. Over-restricting
      the token early is a common source of avoidable failures.
12. Copy the API token immediately and save it locally.
    - Do not put it in tracked files.
    - Do not paste it into `README.md`, `IMPLEMENTATION.md`, `_logs/`, or any
      committed file.
13. Verify the token works before handing anything to the agent.
    - For a user token, use Cloudflare's documented token verification
      endpoint:

```bash
curl "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  --header "Authorization: Bearer $CF_API_TOKEN"
```

   - For an account-owned token:
     - there is not a single user-facing verification step documented in the
       same way
     - if you are using an account-owned token, it is acceptable to skip
       manual verification here and let the agent validate it against the real
       account and zone APIs in Phase 1
   - If you ran the user-token verification command, continue only if the
     response says the token is active.
14. Export the required values in your local shell, or place them in a local
    untracked shell file.
    - Minimum required values:

```bash
export CF_API_TOKEN=...
export CF_ACCOUNT_ID=...
export CF_ZONE_ID=...
export CF_ZONE_NAME=example.com
export CF_PG_HOST=pg.example.com
export CF_NEO4J_BOLT_HOST=neo4j-bolt.example.com
export CF_SPECTRUM_TLS_MODE=off
```

15. Double-check the values before handing off to the agent.
    - `CF_ACCOUNT_ID` must match the Cloudflare account that owns the zone.
    - `CF_ZONE_ID` must match the zone where the public hostnames will live.
    - `CF_PG_HOST` and `CF_NEO4J_BOLT_HOST` must belong to that zone.
16. Once all of the above is done, the user handoff is complete.
    - At that point the agent should be able to do nearly all remaining work.

### Required user-provided values

The agent can do almost everything else if these are provided as environment
variables or in a local untracked file:

```bash
export CF_API_TOKEN=...
export CF_ACCOUNT_ID=...
export CF_ZONE_ID=...
export CF_ZONE_NAME=example.com
export CF_PG_HOST=pg.example.com
export CF_NEO4J_BOLT_HOST=neo4j-bolt.example.com
export CF_SPECTRUM_TLS_MODE=off
```

Recommended default:

- `CF_SPECTRUM_TLS_MODE=off`

That keeps the first proof focused on native TCP reachability instead of TLS
policy complexity.

### Recommended token scopes

Create one API token that can do the entire control-plane setup.

Use the Cloudflare dashboard labels below. In API docs, the same permissions
may appear as `Write` instead of `Edit`.

Minimum expected scopes:

- Account:
  - `Cloudflare Tunnel -> Edit`
    - API name: `Cloudflare Tunnel Write`
  - `Cloudflare One Connectors -> Edit`
    - API name: `Cloudflare One Connectors Write`
  - `Cloudflare One Networks -> Edit`
    - API name: `Cloudflare One Networks Write`
  - `Load Balancing: Monitors and Pools -> Edit`
    - API name: `Load Balancing: Monitors and Pools Write`
- Zone:
  - `Load Balancers -> Edit`
    - API name: `Load Balancers Write`
  - `Zone Settings -> Edit`
    - API name: `Zone Settings Write`

Optional but useful zone scope:

- Zone:
  - `DNS -> Edit`
    - API name: `DNS Write`
    - only needed if we end up creating or modifying standalone DNS records
      outside the load balancer / Spectrum resource flows

If the account uses finer-grained or renamed permissions, the safe rule is:

- tunnel creation and token retrieval must work
- private-network VNet and route creation must work
- pool/monitor creation must work
- zone load balancer creation must work
- Spectrum app creation must work

### Optional but useful user-owned setup

If the account has never used Zero Trust private networking before, a one-time
initial org setup in the Cloudflare account may still require a human account
owner. Once that exists, the rest can be automated.

## What The Agent Can Own After Prerequisites

Once the prerequisites are met, the agent can do almost all remaining work:

1. patch this repo to use stable private IPs inside the DinD environment;
2. create or reuse a Cloudflare Tunnel for private routing;
3. create the private VNet;
4. create the routed CIDR for the DinD internal service network;
5. create TCP health monitors;
6. create LB pools and load balancers;
7. create Spectrum applications for PostgreSQL and Neo4j Bolt;
8. change the experiment runner to connect directly to the Spectrum FQDNs and
   native ports;
9. remove the bridge from the primary success path;
10. run end-to-end validation from the host.

That is the desired execution model for this plan.

## Architecture Decisions

### Fixed private subnet

Plan B is much easier to automate if the DinD child-service network uses a
fixed RFC1918 subnet.

Recommended network:

- subnet: `172.29.0.0/24`
- PostgreSQL: `172.29.0.10`
- Neo4j Bolt/HTTP: `172.29.0.20`

Why:

- the tunnel route becomes deterministic;
- the load balancer pool origins become deterministic;
- the repo can recreate the same topology repeatedly.

### Public hostnames

Recommended:

- PostgreSQL: `pg.<zone>`
- Neo4j Bolt: `neo4j-bolt.<zone>`

### Edge ports

Recommended:

- PostgreSQL: `5432`
- Neo4j Bolt: `7687`

### Neo4j HTTPS

Keep Neo4j HTTPS on the existing HTTP Tunnel path unless there is a separate
reason to move it. It is already direct-FQDN and does not need Spectrum.

## Control-Plane Plan

This is the part the agent should implement via API, not by asking the user to
click through the UI repeatedly.

### Phase 1: Validate entitlements and identity

Agent-owned checks:

1. verify the API token can read the account and zone;
2. verify the zone is active in Cloudflare;
3. verify Spectrum, Load Balancing, and Tunnel endpoints are callable;
4. fail immediately if permissions or product entitlements block the plan.

Stop condition:

- if the token cannot create the required objects, or support has not
  confirmed the product shape, stop before any repo refactor.

### Phase 2: Provision private-network objects

Agent-owned API objects:

1. Create or reuse a Cloudflare Tunnel dedicated to private-network routing.
2. Create or reuse a VNet, for example:
   - `tunnels-experiment-vnet`
3. Create or reuse a route for:
   - `172.29.0.0/24`
4. Store the resulting IDs as local runtime state, never in tracked files.

Expected API families:

- Tunnel
- Virtual networks
- Teamnet routes

### Phase 3: Provision load-balancing objects

Agent-owned API objects:

1. Create a PostgreSQL TCP monitor.
2. Create a Neo4j Bolt TCP monitor.
3. Create a PostgreSQL pool:
   - origin: `172.29.0.10:5432`
   - `virtual_network_id`: the created VNet
4. Create a Neo4j Bolt pool:
   - origin: `172.29.0.20:7687`
   - `virtual_network_id`: the created VNet
5. Create zone load balancers for internal forwarding targets.

Important:

- use dedicated internal LB hostnames, not the final public app hostnames;
- keep public Spectrum hostnames separate from LB hostnames to avoid control
  plane confusion.

Suggested internal LB hostnames:

- `pg-int.<zone>`
- `neo4j-bolt-int.<zone>`

### Phase 4: Provision Spectrum applications

Agent-owned API objects:

1. Create PostgreSQL Spectrum app:
   - hostname: `pg.<zone>`
   - protocol: TCP
   - edge port: `5432`
   - origin: `pg-int.<zone>`
2. Create Neo4j Bolt Spectrum app:
   - hostname: `neo4j-bolt.<zone>`
   - protocol: TCP
   - edge port: `7687`
   - origin: `neo4j-bolt-int.<zone>`

Recommended first-pass config:

- TLS mode: `off`
- Proxy Protocol: disabled
- no advanced optimization until raw connectivity works

## Repo Refactor Plan

The repo should change only after the control plane is real.

### Agent-owned code changes

1. Replace loopback-only published TCP assumptions with a fixed internal
   service network.
2. Give PostgreSQL and Neo4j stable private addresses inside the DinD daemon.
3. Keep the Cloudflare connector running inside `dind-host-container`, but use
   it for private-network routing instead of published TCP apps.
4. Remove the local bridge from the default host workflow.
5. Make `src/experiment_runner.py` connect directly to:
   - `pg.<zone>:5432`
   - `neo4j-bolt.<zone>:7687`
6. Keep Neo4j HTTPS verification as-is unless we intentionally redesign it.

### Recommended implementation order

1. add deterministic internal Docker subnet and IPs;
2. add local runtime config for Spectrum hostnames;
3. add direct-FQDN direct-port connection mode to the experiment runner;
4. keep the old bridge path behind a fallback switch until Spectrum is proven;
5. delete the bridge from the primary path only after repeated successful runs.

## Validation Plan

All of this is agent-executable after prerequisites are satisfied.

### Phase 1 validation

- API creation succeeds for tunnel, VNet, route, pools, LB, and Spectrum apps

### Phase 2 validation

- the DinD internal network comes up with the expected stable addresses
- the Cloudflare private route points to that subnet

### Phase 3 validation

- `psql` connects directly to `pg.<zone>:5432`
- DBeaver connects directly to `pg.<zone>:5432`
- Neo4j Bolt driver connects directly to `neo4j-bolt.<zone>:7687`
- no local Python bridge is running

### Phase 4 validation

- `start_e2e.sh` or its Spectrum successor completes without bridge startup
- the host-side proof writes and reads PostgreSQL data directly over Spectrum
- the host-side proof writes and reads Neo4j Bolt data directly over Spectrum
- Neo4j HTTPS still passes

## Minimal User Actions Checklist

If we want the agent to do almost everything, the user only needs to do this:

1. ensure the Cloudflare account actually has the required products enabled;
2. get explicit confirmation from Cloudflare support/account team that the
   intended product combination is allowed for the account;
3. create one API token with the required scopes;
4. provide:
   - `CF_API_TOKEN`
   - `CF_ACCOUNT_ID`
   - `CF_ZONE_ID`
   - `CF_ZONE_NAME`
   - approved public hostnames
   - approved TLS mode

Everything else should be treated as agent-owned.

## Exact Support Question To Send

Use this verbatim if needed:

> We want to expose PostgreSQL on port 5432 and Neo4j Bolt on port 7687 as
> native public TCP services using Cloudflare Spectrum. The origins should
> remain private and be reached through a Cloudflare Tunnel / VNet private
> network off-ramp, with Cloudflare Load Balancing between Spectrum and the
> private origins. Please confirm this product shape is supported on our
> account and zone for generic TCP applications, and confirm any required
> plan/feature flags.

## Stop Conditions

Do not proceed with repo implementation if any of these are true:

- Spectrum is not enabled for the zone/account
- Load Balancing or private-network routing is not enabled
- the API token cannot create the required objects
- Cloudflare support/account team says this exact product combination is not
  supported for the target protocols

## Sources

- Cloudflare Tunnel published-app protocols:
  - https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/
- Cloudflare Tunnel integrations:
  - https://developers.cloudflare.com/tunnel/integrations/
- Cloudflare Private Network Load Balancing overview:
  - https://developers.cloudflare.com/load-balancing/private-network/
- Cloudflare Private Network Load Balancing for public traffic to Tunnel:
  - https://developers.cloudflare.com/load-balancing/private-network/public-to-tunnel/
- Cloudflare Spectrum get started:
  - https://developers.cloudflare.com/spectrum/get-started/
- Cloudflare Spectrum configuration options:
  - https://developers.cloudflare.com/spectrum/reference/configuration-options/
- Cloudflare Spectrum limitations:
  - https://developers.cloudflare.com/spectrum/reference/limitations/
- Cloudflare Spectrum settings by plan:
  - https://developers.cloudflare.com/spectrum/reference/settings-by-plan/
