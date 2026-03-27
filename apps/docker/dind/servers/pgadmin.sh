#!/bin/bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/../lib/common.sh"

scope="pgadmin-service"
service_key="pgadmin"
container_name="pgadmin-demo"
bridge_name="app_postgres_bridge"
bridge_log_color="green"
image_name="tunnel-demo-pgadmin-ui:latest"
image_build_dir="/opt/tunnel-app/assets/pgadmin"
ready_file="$(ready_file_for_service "${service_key}")"
runtime_dir="/runtime/${service_key}"
managed_pids=()

cleanup() {
  local exit_code=$?
  set +e
  log_with_scope "${scope}" "cleanup started with exit code ${exit_code}"

  local pid
  for pid in "${managed_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker volume rm -f "${container_name}-data" >/dev/null 2>&1 || true
  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

build_image() {
  log_with_scope "${scope}" "building custom pgAdmin child image ${image_name}"
  docker build -t "${image_name}" "${image_build_dir}" >/dev/null
}

start_bridge() {
  local bridge_pid

  mkdir -p "${runtime_dir}"
  python3 /opt/tunnel-app/shared/src/tunnel_common/universal.py \
    --name "${bridge_name}" \
    --hostname "${REMOTE_POSTGRES_PUBLIC_HOST}" \
    --local-port "${APP_BRIDGE_LOCAL_PORT}" \
    --run-ts "${RUN_TS}" \
    --raw-logs-dir "${RAW_LOGS_DIR}" \
    --log-color "${bridge_log_color}" &
  bridge_pid="$!"
  managed_pids+=("${bridge_pid}")
  wait_until "${scope}" "local PostgreSQL bridge ${APP_BRIDGE_LOCAL_HOST}:${APP_BRIDGE_LOCAL_PORT}" 60 1 nc -z "${APP_BRIDGE_LOCAL_HOST}" "${APP_BRIDGE_LOCAL_PORT}"
}

verify_bridge_from_app_host() {
  wait_until "${scope}" "PostgreSQL verification from dind-host-app" 30 2 \
    python3 /opt/tunnel-app/src/utils/verify_postgres_bridge.py \
      --host "${APP_BRIDGE_LOCAL_HOST}" \
      --port "${APP_BRIDGE_LOCAL_PORT}" \
      --database "${POSTGRES_DB}" \
      --user "${POSTGRES_USER}" \
      --password "${POSTGRES_PASSWORD}"
}

write_pgadmin_server_config() {
  cat >"${runtime_dir}/servers.json" <<EOF
{
  "Servers": {
    "1": {
      "Name": "PostgreSQL via dind-host-app bridge",
      "Group": "Demo",
      "Host": "${APP_BRIDGE_LOCAL_HOST}",
      "Port": ${APP_BRIDGE_LOCAL_PORT},
      "MaintenanceDB": "${POSTGRES_DB}",
      "Username": "${POSTGRES_USER}",
      "SSLMode": "disable"
    }
  }
}
EOF
}

start_pgadmin_container() {
  log_with_scope "${scope}" "starting pgAdmin child container on host-network loopback"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker volume rm -f "${container_name}-data" >/dev/null 2>&1 || true

  docker run -d \
    --name "${container_name}" \
    --network host \
    -e "PGADMIN_DEFAULT_EMAIL=${PGADMIN_DEFAULT_EMAIL}" \
    -e "PGADMIN_DEFAULT_PASSWORD=${PGADMIN_DEFAULT_PASSWORD}" \
    -e "PGADMIN_CONFIG_ALLOWED_HOSTS=['${APP_UI_PUBLIC_HOST}','127.0.0.1','localhost']" \
    -e "PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED=False" \
    -e "PGADMIN_CONFIG_PROXY_X_HOST_COUNT=1" \
    -e "PGADMIN_CONFIG_PROXY_X_PORT_COUNT=1" \
    -e "PGADMIN_CONFIG_PROXY_X_PROTO_COUNT=1" \
    -e "PGADMIN_CONFIG_SERVER_MODE=False" \
    -e "PGADMIN_LISTEN_ADDRESS=${APP_UI_LOCAL_HOST}" \
    -e "PGADMIN_LISTEN_PORT=${APP_UI_LOCAL_PORT}" \
    -v "${runtime_dir}/servers.json:/pgadmin4/servers.json:ro" \
    -v "${container_name}-data:/var/lib/pgadmin" \
    "${image_name}" >/dev/null
}

wait_for_pgadmin() {
  wait_until "${scope}" "pgAdmin HTTP listener ${APP_UI_LOCAL_HOST}:${APP_UI_LOCAL_PORT}" 60 2 nc -z "${APP_UI_LOCAL_HOST}" "${APP_UI_LOCAL_PORT}"
  wait_until "${scope}" "pgAdmin container bridge verification" 30 2 \
    docker exec \
      -e "PGTARGET_HOST=${APP_BRIDGE_LOCAL_HOST}" \
      -e "PGTARGET_PORT=${APP_BRIDGE_LOCAL_PORT}" \
      -e "POSTGRES_DB=${POSTGRES_DB}" \
      -e "POSTGRES_USER=${POSTGRES_USER}" \
      -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
      "${container_name}" \
      python3 -c "import os, psycopg; connection = psycopg.connect(host=os.environ['PGTARGET_HOST'], port=int(os.environ['PGTARGET_PORT']), dbname=os.environ['POSTGRES_DB'], user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'], connect_timeout=10, sslmode='disable'); cursor = connection.cursor(); cursor.execute('SELECT 1'); value = cursor.fetchone()[0]; cursor.close(); connection.close(); raise SystemExit(0 if value == 1 else 1)"
}

start_ui_tunnel() {
  local tunnel_pid
  tunnel_pid="$(start_tunnel_process "${scope}" "pgadmin_https_tunnel" "${APP_UI_TUNNEL_TOKEN}" "http://${APP_UI_LOCAL_HOST}:${APP_UI_LOCAL_PORT}")"
  managed_pids+=("${tunnel_pid}")
}

write_ready_file() {
  jq -n \
    --arg run_id "${RUN_TS}" \
    --arg service_key "${service_key}" \
    --arg service_name "pgAdmin over PostgreSQL bridge" \
    --arg container_name "${container_name}" \
    --arg bridge_bind "${APP_BRIDGE_LOCAL_HOST}:${APP_BRIDGE_LOCAL_PORT}" \
    --arg ui_bind "${APP_UI_LOCAL_HOST}:${APP_UI_LOCAL_PORT}" \
    --arg remote_postgres_host "${REMOTE_POSTGRES_PUBLIC_HOST}" \
    --arg public_ui_host "${APP_UI_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      service_key: $service_key,
      service_name: $service_name,
      container_name: $container_name,
      local_origins: [
        {
          name: "postgres_bridge",
          bind: $bridge_bind,
          origin_scheme: "tcp",
          purpose: "Local TCP bridge inside dind-host-app that relays to the remote PostgreSQL tunnel"
        },
        {
          name: "pgadmin_http",
          bind: $ui_bind,
          origin_scheme: "http",
          purpose: "pgAdmin HTTP UI inside dind-host-app"
        }
      ],
      local_origin_map: {
        postgres_bridge: $bridge_bind,
        pgadmin_http: $ui_bind
      },
      public_endpoints: [
        {
          name: "app_ui_https",
          hostname: $public_ui_host,
          client_transport: "https",
          origin_scheme: "http",
          purpose: "Public HTTPS hostname that proxies to the pgAdmin HTTP UI"
        }
      ],
      public_host_map: {
        app_ui_https: $public_ui_host
      },
      dependencies: {
        remote_postgres_public_host: $remote_postgres_host
      },
      ready: true
    }' >"${ready_file}"
}

supervise() {
  while true; do
    if ! docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null | grep -q true; then
      log_with_scope "${scope}" "web UI container ${container_name} is no longer running"
      docker logs "${container_name}" | tail -n 200 >&2 || true
      return 1
    fi

    local pid
    for pid in "${managed_pids[@]}"; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        log_with_scope "${scope}" "managed process ${pid} exited unexpectedly"
        return 1
      fi
    done

    sleep 5
  done
}

main() {
  build_image
  start_bridge
  verify_bridge_from_app_host
  write_pgadmin_server_config
  start_pgadmin_container
  wait_for_pgadmin
  start_ui_tunnel
  write_ready_file
  log_with_scope "${scope}" "pgAdmin app startup complete and ready marker written to ${ready_file}"
  supervise
}

main "$@"
