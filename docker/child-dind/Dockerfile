FROM docker:29-dind

# The child DinD images only need shell tooling. They do not run cloudflared.
RUN apk add --no-cache bash curl jq

WORKDIR /workspace
