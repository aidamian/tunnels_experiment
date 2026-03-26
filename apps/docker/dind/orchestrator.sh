#!/bin/bash
set -Eeuo pipefail

base_dir="/opt/tunnel-app"
source "${base_dir}/lib/common.sh"

service_pids=()
service_keys=()
service_scripts=()

cleanup() {
  local exit_code=$?
  set +e
  log_with_scope "orchestrator" "cleanup started with exit code ${exit_code}"

  for pid in "${service_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

discover_service_scripts() {
  local script_path
  local discovered_keys=()

  shopt -s nullglob
  for script_path in "${base_dir}"/servers/*.sh; do
    local service_key
    service_key="$(service_key_from_path "${script_path}")"
    if ! service_is_enabled "${service_key}"; then
      continue
    fi
    service_scripts+=("${script_path}")
    service_keys+=("${service_key}")
    discovered_keys+=("${service_key}")
  done
  shopt -u nullglob

  if [[ "${#service_scripts[@]}" -eq 0 ]]; then
    log_with_scope "orchestrator" "no enabled app service scripts were found under ${base_dir}/servers"
    return 1
  fi

  log_with_scope "orchestrator" "discovered app service scripts: ${discovered_keys[*]}"
}

start_service_scripts() {
  local index
  local service_key
  local script_path
  local logfile

  for ((index = 0; index < ${#service_scripts[@]}; index += 1)); do
    service_key="${service_keys[${index}]}"
    script_path="${service_scripts[${index}]}"
    logfile="$(service_console_log_for_service "${service_key}")"

    log_with_scope "orchestrator" "starting app service script ${script_path} for service key ${service_key}"
    "${script_path}" > >(tee -a "${logfile}") 2>&1 &
    service_pids+=("$!")
  done
}

wait_for_service_markers() {
  local service_key
  local ready_file

  for service_key in "${service_keys[@]}"; do
    ready_file="$(ready_file_for_service "${service_key}")"
    wait_until "orchestrator" "service marker for ${service_key}" 90 2 jq -e '.ready == true' "${ready_file}"
  done
}

wait_for_local_origins() {
  local service_key
  local ready_file
  local bind_target
  local bind_host
  local bind_port

  for service_key in "${service_keys[@]}"; do
    ready_file="$(ready_file_for_service "${service_key}")"
    while IFS= read -r bind_target; do
      [[ -z "${bind_target}" ]] && continue
      bind_host="${bind_target%:*}"
      bind_port="${bind_target##*:}"
      wait_until "orchestrator" "local origin ${bind_target} for ${service_key}" 60 2 nc -z "${bind_host}" "${bind_port}"
    done < <(jq -r '.local_origins[]?.bind' "${ready_file}")
  done
}

write_topology_ready_file() {
  local ready_files=()
  local service_key

  for service_key in "${service_keys[@]}"; do
    ready_files+=("$(ready_file_for_service "${service_key}")")
  done

  jq -s \
    --arg run_id "${RUN_TS}" \
    '{
      run_id: $run_id,
      all_ready: true,
      published_ports_on_top_level_container: [],
      topology: {
        top_level_service: "dind-host-app",
        managed_service_containers: [.[].container_name],
        local_origins_inside_dind_host: (reduce .[] as $service ({}; . + ($service.local_origin_map // {}))),
        public_hosts: (reduce .[] as $service ({}; . + ($service.public_host_map // {}))),
        services: [
          .[] | {
            service_key,
            service_name,
            container_name,
            local_origins,
            public_endpoints,
            dependencies
          }
        ]
      }
    }' "${ready_files[@]}" >"${RAW_LOGS_DIR}/${RUN_TS}_topology_ready.json"
}

supervise() {
  while true; do
    local pid
    for pid in "${service_pids[@]}"; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        log_with_scope "orchestrator" "service supervisor process ${pid} exited unexpectedly"
        return 1
      fi
    done

    sleep 5
  done
}

main() {
  discover_service_scripts
  start_service_scripts
  wait_for_service_markers
  wait_for_local_origins
  write_topology_ready_file
  log_with_scope "orchestrator" "app topology startup complete"
  supervise
}

main "$@"
