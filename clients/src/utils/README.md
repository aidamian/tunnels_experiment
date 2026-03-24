# `clients/src/utils`

Client-side support modules for:

- service-catalog loading from `clients/services.json`
- ANSI-aware console helpers
- dependency loading
- Docker runtime inspection
- atomic JSON writing
- smoke testing
- tracked markdown summary generation

These utilities are client-owned. They must not read `servers/.runtime/` or `servers/_logs/raw/`.
