FROM docker:29-dind

# The top-level DinD host owns the Docker daemon, both database containers,
# and all outbound Cloudflare Tunnel processes.
COPY --from=cloudflare/cloudflared:latest /usr/local/bin/cloudflared /usr/local/bin/cloudflared

RUN apk add --no-cache bash curl jq netcat-openbsd

WORKDIR /opt/tunnel-demo

# Keep the DinD host self-contained: the entrypoint, orchestrator, shared
# helpers, and the entire service-script directory all live inside the image.
COPY docker/dind/entrypoint.sh /usr/local/bin/tunnel-demo-entrypoint.sh
COPY docker/dind/orchestrator.sh /usr/local/bin/tunnel-demo-orchestrator.sh
COPY docker/dind/lib/common.sh /opt/tunnel-demo/lib/common.sh
COPY docker/dind/servers/ /opt/tunnel-demo/servers/

RUN chmod +x \
    /usr/local/bin/tunnel-demo-entrypoint.sh \
    /usr/local/bin/tunnel-demo-orchestrator.sh \
    /opt/tunnel-demo/servers/*.sh

ENTRYPOINT ["/usr/local/bin/tunnel-demo-entrypoint.sh"]
