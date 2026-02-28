#!/bin/bash
# Stop any process(es) listening on port 8000.
# Works on macOS and Linux.
cd "$(dirname "$0")"

PORT=8000

if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti :"$PORT" 2>/dev/null)
elif command -v fuser >/dev/null 2>&1; then
  # fuser is the fallback on minimal Linux installs without lsof
  PIDS=$(fuser "$PORT"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$')
else
  echo "Error: neither lsof nor fuser found. Kill the server manually." >&2
  exit 1
fi

if [ -z "$PIDS" ]; then
  echo "No process found on port $PORT."
else
  echo "$PIDS" | xargs kill
  echo "Stopped process(es) on port $PORT (PID(s): $(echo "$PIDS" | tr '\n' ' '))."
fi
