"""Shared non-secret demo constants used by host-side code and runtime generation."""

from __future__ import annotations


NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "tunnel-demo-neo4j"

POSTGRES_USER = "tunnel_demo"
POSTGRES_PASSWORD = "tunnel-demo-postgres"
POSTGRES_DB = "tunnel_demo"

HOST_NEO4J_BOLT_FORWARD_PORT = 17687
HOST_POSTGRES_FORWARD_PORT = 15432

MANUAL_NEO4J_BOLT_FORWARD_PORT = 57687
MANUAL_POSTGRES_FORWARD_PORT = 55432

DEFAULT_EXPERIMENT_DURATION_SECONDS = 30
DEFAULT_EXPERIMENT_CYCLE_INTERVAL_SECONDS = 10
