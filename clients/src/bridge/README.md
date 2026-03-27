# `clients/src/bridge`

Client-side bridge code for Cloudflare-published TCP services.

- `local_bridges.py`
  - bridge specifications derived from `clients/services.json`
- `start_local_bridges.py`
  - manual bridge CLI
- `shared/src/tunnel_common/universal.py`
  - shared reusable TCP-to-WebSocket bridge used by both `clients/` and `apps/`, and directly runnable for one bridge per process

This directory is fully client-owned and must not read server runtime files.
