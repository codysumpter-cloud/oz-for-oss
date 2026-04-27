#!/bin/sh
# Minimal entrypoint for the review agent container.

set -e

AGENT_BIN_DIR="/opt/warpdotdev/oz-stable"
AGENT_BINARY="$AGENT_BIN_DIR/oz"

export PATH="$PATH:$AGENT_BIN_DIR"

if [ -z "$WARP_API_KEY" ]; then
    echo "WARP_API_KEY is not set" >&2
    exit 1
fi

exec "$AGENT_BINARY" "$@"
