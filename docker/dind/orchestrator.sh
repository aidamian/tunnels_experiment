#!/bin/bash
set -Eeuo pipefail

# The orchestrator owns the overall startup order for the DinD host.
#
# The key rule for this file is that it must stay agnostic to which services
# exist. It discovers every `*.sh` file under /opt/tunnel-demo/servers, starts
# each one, waits for its ready marker, and then writes a single aggregated
# topology snapshot for the host-side tooling.

base_dir="/opt/tunnel-demo"
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

  # nullglob keeps an empty services directory from expanding to a literal
  # "*.sh", which lets us fail clearly when no services are packaged.
  shopt -s nullglob
  for script_path in "${base_dir}"/servers/*.sh; do
    service_scripts+=("${script_path}")
    service_keys+=("$(service_key_from_path "${script_path}")")
    discovered_keys+=("$(service_key_from_path "${script_path}")")
  done
  shopt -u nullglob

  if [[ "${#service_scripts[@]}" -eq 0 ]]; then
    log_with_scope "orchestrator" "no service scripts were found under ${base_dir}/servers"
    return 1
  fi

  log_with_scope "orchestrator" "discovered service scripts: ${discovered_keys[*]}"
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

    log_with_scope "orchestrator" "starting service script ${script_path} for service key ${service_key}"
    "${script_path}" > >(tee -a "${logfile}") 2>&1 &
    service_pids+=("$!")
  done
}

wait_for_service_markers() {
  local service_key
  local ready_file

  # Every service script writes ${RUN_TS}_${service_key}_service_ready.json.
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

  # Read the loopback binds back from the ready marker instead of hard-coding
  # them here. That keeps the orchestrator generic.
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

  # The aggregated topology keeps a generic list of services, plus merged maps
  # that preserve compatibility with the current reporting scripts.
  jq -s \
    --arg run_id "${RUN_TS}" \
    '{
      run_id: $run_id,
      all_ready: true,
      published_ports_on_top_level_container: [],
      topology: {
        top_level_service: "dind-host-container",
        managed_service_containers: [.[].container_name],
        local_origins_inside_dind_host: (reduce .[] as $service ({}; . + ($service.local_origin_map // {}))),
        public_hosts: (reduce .[] as $service ({}; . + ($service.public_host_map // {}))),
        services: [
          .[] | {
            service_key,
            service_name,
            container_name,
            local_origins,
            public_endpoints
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
  log_with_scope "orchestrator" "tunnel 4 remains reserved and intentionally unused"
  write_topology_ready_file
  log_with_scope "orchestrator" "topology startup complete"
  supervise
}

main "$@"
