#!/bin/bash

# Shared helpers used by the DinD host entrypoint, the top-level orchestrator,
# and the per-service startup scripts. Centralizing these helpers keeps the
# service scripts focused on service-specific work instead of duplicated shell
# plumbing.

# RUN_TS ties all artifacts to a single experiment execution. LOGS_DIR is
# provided by docker compose and points at the host-mounted log directory.
: "${RUN_TS:?RUN_TS is required}"
: "${LOGS_DIR:=/logs}"

# Keep all raw runtime artifacts under /logs/raw for predictable collection.
RAW_LOGS_DIR="${LOGS_DIR}/raw"
mkdir -p "${RAW_LOGS_DIR}"

timestamp_utc() {
  date -Iseconds
}

log_with_scope() {
  local scope="$1"
  local message="$2"
  local logfile="${RAW_LOGS_DIR}/${RUN_TS}_${scope}.log"

  # Mirror each log message to stderr and to a scoped file so both interactive
  # debugging and post-run inspection are straightforward.
  printf '[%s] [%s] %s\n' "$(timestamp_utc)" "${scope}" "${message}" | tee -a "${logfile}" >&2
}

service_key_from_path() {
  local script_path="$1"
  basename "${script_path}" .sh
}

ready_file_for_service() {
  local service_key="$1"
  printf '%s/%s_%s_service_ready.json\n' "${RAW_LOGS_DIR}" "${RUN_TS}" "${service_key}"
}

service_console_log_for_service() {
  local service_key="$1"
  printf '%s/%s_%s_service_console.log\n' "${RAW_LOGS_DIR}" "${RUN_TS}" "${service_key}"
}

wait_until() {
  local scope="$1"
  local description="$2"
  local attempts="$3"
  local delay_seconds="$4"
  shift 4

  # Callers pass a plain command so this helper can be reused for Docker
  # readiness probes, file checks, and TCP reachability tests.
  local try
  for ((try = 1; try <= attempts; try += 1)); do
    if "$@" >/dev/null 2>&1; then
      log_with_scope "${scope}" "${description} is ready"
      return 0
    fi

    log_with_scope "${scope}" "${description} not ready yet (attempt ${try}/${attempts})"
    sleep "${delay_seconds}"
  done

  log_with_scope "${scope}" "${description} failed readiness checks"
  return 1
}

start_tunnel_process() {
  local scope="$1"
  local tunnel_name="$2"
  local tunnel_token="$3"
  local target_url="$4"
  local logfile="${RAW_LOGS_DIR}/${RUN_TS}_${tunnel_name}.log"

  # The target URL can be HTTP(S) or TCP. Either way, the connector process
  # itself always lives in the top-level DinD host container.
  log_with_scope "${scope}" "starting tunnel ${tunnel_name} -> ${target_url}"
  cloudflared tunnel \
    --metrics 127.0.0.1:0 \
    --no-autoupdate \
    --loglevel info \
    run \
    --token "${tunnel_token}" \
    --url "${target_url}" \
    >"${logfile}" 2>&1 &

  local pid=$!
  sleep 3

  # If cloudflared dies immediately, surface the recent log lines right away so
  # the parent script fails with actionable information.
  if ! kill -0 "${pid}" 2>/dev/null; then
    log_with_scope "${scope}" "tunnel ${tunnel_name} exited immediately"
    tail -n 50 "${logfile}" >&2 || true
    return 1
  fi

  echo "${pid}"
}
