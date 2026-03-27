FROM docker:29-dind

COPY --from=cloudflare/cloudflared:latest /usr/local/bin/cloudflared /usr/local/bin/cloudflared

RUN apk add --no-cache bash curl jq netcat-openbsd python3 py3-pip
RUN python3 -m pip install --break-system-packages --no-cache-dir "websocket-client>=1.8,<2.0" "psycopg[binary]>=3.2,<4.0"

WORKDIR /opt/tunnel-app

COPY docker/dind/entrypoint.sh /usr/local/bin/tunnel-app-entrypoint.sh
COPY docker/dind/orchestrator.sh /usr/local/bin/tunnel-app-orchestrator.sh
COPY docker/dind/lib/common.sh /opt/tunnel-app/lib/common.sh
COPY docker/dind/servers/ /opt/tunnel-app/servers/
COPY docker/dind/assets/ /opt/tunnel-app/assets/
COPY src/ /opt/tunnel-app/src/
COPY --from=shared_src . /opt/tunnel-app/shared/src/

RUN chmod +x \
    /usr/local/bin/tunnel-app-entrypoint.sh \
    /usr/local/bin/tunnel-app-orchestrator.sh \
    /opt/tunnel-app/servers/*.sh

ENTRYPOINT ["/usr/local/bin/tunnel-app-entrypoint.sh"]
