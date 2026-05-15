#!/bin/bash
# Start the ViSTA Simulation Format Validator server (macOS & Linux).
# Uses python3 -m uvicorn so the correct uvicorn is found regardless of install method.
set -e
cd "$(dirname "$0")"

if ! python3 -m uvicorn --version >/dev/null 2>&1; then
  echo "Error: uvicorn not found. Install dependencies with:" >&2
  echo "  pip3 install -r requirements.txt" >&2
  exit 1
fi

exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --limit-concurrency 20 \
  --timeout-keep-alive 30
