"""Structured host-side tooling for the tunnel experiment.

This package contains the real implementation for the host-side runtime
preparation, readiness checks, tunnel-bridge helpers, and experiment workload.
Thin entrypoint wrappers under `scripts/` and `scripts/sre/` import these
modules so operator-facing commands stay simple while the internal code remains
separated by concern.
"""
