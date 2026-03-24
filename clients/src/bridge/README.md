# `clients/src/bridge`

Client-side bridge code for Cloudflare-published TCP services.

- `universal.py`
  - reusable TCP-to-WebSocket bridge
- `local_bridges.py`
  - bridge specifications derived from `clients/services.json`
- `start_local_bridges.py`
  - manual bridge CLI

This directory is fully client-owned and must not read server runtime files.
