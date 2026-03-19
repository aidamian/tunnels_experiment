#!/bin/bash

# Shared helpers used by the DinD host entrypoint, the top-level orchestrator,
# and the per-service startup scripts.

: "${RUN_TS:?RUN_TS is required}"
: "${LOGS_DIR:=/logs}"

RAW_LOGS_DIR="${LOGS_DIR}/raw"
mkdir -p "${RAW_LOGS_DIR}"

timestamp_utc() {
  date -Iseconds
}

log_with_scope() {
  local scope="$1"
  local message="$2"
  local logfile="${RAW_LOGS_DIR}/${RUN_TS}_${scope}.log"
  printf '[%s] [%s] %s\n' "$(timestamp_utc)" "${scope}" "${message}" | tee -a "${logfile}" >&2
}

wait_until() {
  local scope="$1"
  local description="$2"
  local attempts="$3"
  local delay_seconds="$4"
  shift 4

  local try
  for ((try = 1; try <= attempts; try += 1)); do
    if "$@" >/dev/null 2>&1; then
      log_with_scope "${scope}" "${description} is ready"
      return 0
    fi
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

  if ! kill -0 "${pid}" 2>/dev/null; then
    log_with_scope "${scope}" "tunnel ${tunnel_name} exited immediately"
    tail -n 50 "${logfile}" >&2 || true
    return 1
  fi

  echo "${pid}"
}
