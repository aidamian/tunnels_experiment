#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
server_root="${repo_root}/servers"
app_root="${repo_root}/apps"
server_raw_logs_dir="${server_root}/_logs/raw"
app_raw_logs_dir="${app_root}/_logs/raw"
persistent_service_volume_name="tunnels-experiment-persistent-service-data"
keep_up="false"
exit_after_verify="false"
cleanup_started="false"
run_ts="unknown"
server_services="pgsql"
server_stack_started="false"
app_stack_started="false"
server_compose_cmd=(docker compose --project-directory "${server_root}" -f "${server_root}/docker-compose.yml")
app_compose_cmd=(docker compose --project-directory "${app_root}" -f "${app_root}/docker-compose.yml")

mkdir -p "${server_raw_logs_dir}" "${app_raw_logs_dir}"

usage() {
  cat <<'EOF'
Usage: ./start_apps.sh [--server-services csv] [--exit-after-verify] [--keep-up]

This command starts:
1. dind-host-server with only the requested origin services
2. dind-host-app with an internal Python bridge and pgAdmin UI
3. the public HTTPS tunnel that exposes the pgAdmin UI

By default the script keeps both stacks running until Ctrl-C, then tears them
down. Use --exit-after-verify for a one-shot verification run.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-up)
      keep_up="true"
      shift
      ;;
    --exit-after-verify)
      exit_after_verify="true"
      shift
      ;;
    --server-services)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --server-services" >&2
        usage >&2
        exit 1
      fi
      server_services="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log() {
  local message="$1"
  local color="${2:-cyan}"
  local color_code=""
  case "${color}" in
    blue) color_code='\033[34m' ;;
    cyan) color_code='\033[36m' ;;
    green) color_code='\033[32m' ;;
    red) color_code='\033[31m' ;;
    yellow) color_code='\033[33m' ;;
  esac
  printf '%b[%s] [start_apps.sh] %s\033[0m\n' "${color_code}" "$(date -Iseconds)" "${message}"
}

quoted_command() {
  printf '%q ' "$@"
}

csv_has_service() {
  local csv="$1"
  local expected="$2"
  local item=""

  IFS=',' read -r -a _service_items <<<"${csv}"
  for item in "${_service_items[@]}"; do
    item="${item//[[:space:]]/}"
    if [[ "${item}" == "${expected}" ]]; then
      return 0
    fi
  done
  return 1
}

run_step() {
  local label="$1"
  local logfile="$2"
  shift 2

  log "step: ${label}" blue
  log "logfile: ${logfile}" cyan
  log "command: $(quoted_command "$@")" yellow
  "$@" 2>&1 | tee "${logfile}"
}

ensure_persistent_service_volume() {
  if docker volume inspect "${persistent_service_volume_name}" >/dev/null 2>&1; then
    log "persistent service data volume ${persistent_service_volume_name} already exists"
    return
  fi

  log "creating persistent service data volume ${persistent_service_volume_name}"
  docker volume create "${persistent_service_volume_name}" >/dev/null
}

extract_env_value() {
  local env_file="$1"
  local key="$2"
  awk -F= -v key="${key}" '$1 == key {print substr($0, index($0, "=") + 1)}' "${env_file}"
}

validate_required_server_services() {
  if ! csv_has_service "${server_services}" "pgsql"; then
    echo "start_apps.sh requires server service 'pgsql' because the app bridge targets PostgreSQL" >&2
    exit 1
  fi
}

hold_until_interrupt() {
  log "app flow ${run_ts} is verified and running" green
  log "public pgAdmin UI: https://${app_ui_public_host}" green
  log "press Ctrl-C to stop both stacks" yellow
  while true; do
    sleep 3600
  done
}

cleanup() {
  local exit_code=$?
  if [[ "${cleanup_started}" == "true" ]]; then
    return
  fi
  cleanup_started="true"

  if [[ "${app_stack_started}" == "true" && "${keep_up}" != "true" ]]; then
    log "stopping the app Compose stack" yellow
    "${app_compose_cmd[@]}" down --remove-orphans --volumes \
      >"${app_raw_logs_dir}/${run_ts}_compose_down.log" 2>&1 || true
  fi
  if [[ "${server_stack_started}" == "true" && "${keep_up}" != "true" ]]; then
    log "stopping the server Compose stack" yellow
    "${server_compose_cmd[@]}" down --remove-orphans --volumes \
      >"${server_raw_logs_dir}/${run_ts}_compose_down.log" 2>&1 || true
  fi
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

cd "${repo_root}"

validate_required_server_services

run_step "preparing server runtime" "${server_raw_logs_dir}/prepare_runtime.log" python3 "${server_root}/src/utils/prepare_runtime.py" --enabled-services "${server_services}"
run_ts="$(extract_env_value "${server_root}/.runtime/dind.env" "RUN_TS")"
if [[ -z "${run_ts}" ]]; then
  echo "failed to extract RUN_TS from servers/.runtime/dind.env" >&2
  exit 1
fi

postgres_public_host="$(extract_env_value "${server_root}/.runtime/dind.env" "POSTGRES_PUBLIC_HOST")"
app_ui_public_host="$(extract_env_value "${server_root}/.runtime/dind.env" "APP_UI_PUBLIC_HOST")"
app_ui_tunnel_token="$(extract_env_value "${server_root}/.runtime/dind.env" "APP_UI_TUNNEL_TOKEN")"
postgres_user="$(extract_env_value "${server_root}/.runtime/dind.env" "POSTGRES_USER")"
postgres_password="$(extract_env_value "${server_root}/.runtime/dind.env" "POSTGRES_PASSWORD")"
postgres_db="$(extract_env_value "${server_root}/.runtime/dind.env" "POSTGRES_DB")"

run_step \
  "preparing app runtime" \
  "${app_raw_logs_dir}/prepare_runtime.log" \
  python3 "${app_root}/src/utils/prepare_runtime.py" \
    --run-ts "${run_ts}" \
    --remote-postgres-public-host "${postgres_public_host}" \
    --app-ui-public-host "${app_ui_public_host}" \
    --app-ui-tunnel-token "${app_ui_tunnel_token}" \
    --postgres-user "${postgres_user}" \
    --postgres-password "${postgres_password}" \
    --postgres-db "${postgres_db}"

ensure_persistent_service_volume

run_step "validating server compose configuration" "${server_raw_logs_dir}/${run_ts}_compose_config.log" "${server_compose_cmd[@]}" config -q
run_step "validating app compose configuration" "${app_raw_logs_dir}/${run_ts}_compose_config.log" "${app_compose_cmd[@]}" config -q

run_step "building and starting the server stack" "${server_raw_logs_dir}/${run_ts}_compose_up.log" "${server_compose_cmd[@]}" up --build --quiet-build --quiet-pull -d
server_stack_started="true"
run_step "waiting for the server topology" "${server_raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 "${server_root}/src/utils/wait_for_stack.py" --run-ts "${run_ts}"

run_step "building and starting the app stack" "${app_raw_logs_dir}/${run_ts}_compose_up.log" "${app_compose_cmd[@]}" up --build --quiet-build --quiet-pull -d
app_stack_started="true"
run_step "waiting for the app topology" "${app_raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 "${app_root}/src/utils/wait_for_stack.py" --run-ts "${run_ts}"
run_step "verifying the public app UI" "${app_raw_logs_dir}/${run_ts}_verify_public_ui.log" python3 "${app_root}/src/utils/verify_public_ui.py" --run-ts "${run_ts}" --timeout-seconds 60

run_step "capturing server compose status" "${server_raw_logs_dir}/${run_ts}_compose_ps.log" "${server_compose_cmd[@]}" ps
run_step "capturing app compose status" "${app_raw_logs_dir}/${run_ts}_compose_ps.log" "${app_compose_cmd[@]}" ps
run_step "capturing server container logs" "${server_raw_logs_dir}/${run_ts}_compose_logs.log" "${server_compose_cmd[@]}" logs --no-color dind-host-server
run_step "capturing app container logs" "${app_raw_logs_dir}/${run_ts}_compose_logs.log" "${app_compose_cmd[@]}" logs --no-color dind-host-app

if [[ "${exit_after_verify}" == "true" ]]; then
  log "app flow ${run_ts} completed successfully" green
  exit 0
fi

hold_until_interrupt
