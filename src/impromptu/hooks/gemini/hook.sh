#!/bin/bash
# Gemini CLI Hook for Impromptu - Socket-based IPC
# Sends all hook events to Impromptu via Unix domain socket

SOCKET_DIR="/tmp/impromptu_sockets"
AGENT_ID="${IMPROMPTU_AGENT_ID:-}"

if [ -n "$AGENT_ID" ]; then
    SOCKET_PATH="$SOCKET_DIR/${AGENT_ID}.sock"
    if [ -S "$SOCKET_PATH" ]; then
        cat | timeout 0.5 nc -U "$SOCKET_PATH" 2>/dev/null
    fi
fi

exit 0
