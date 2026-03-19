FROM docker:29-dind

# The top-level DinD host owns all outbound Cloudflare Tunnel processes.
COPY --from=cloudflare/cloudflared:latest /usr/local/bin/cloudflared /usr/local/bin/cloudflared

RUN apk add --no-cache bash curl jq netcat-openbsd

WORKDIR /workspace
