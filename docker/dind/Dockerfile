FROM docker:29-dind

COPY --from=cloudflare/cloudflared:latest /usr/local/bin/cloudflared /usr/local/bin/cloudflared

RUN apk add --no-cache bash curl jq

WORKDIR /workspace
