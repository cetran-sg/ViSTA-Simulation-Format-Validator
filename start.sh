#!/bin/bash
# Start the ViSTA Simulation Format Validator server.
# Works on macOS and Linux: uses `python3 -m uvicorn` instead of a
# hardcoded path so it finds uvicorn however it was installed
# (pip install --user, system package, virtualenv, etc.).
set -e
cd "$(dirname "$0")"

if ! python3 -m uvicorn --version >/dev/null 2>&1; then
  echo "Error: uvicorn not found. Install dependencies with:" >&2
  echo "  pip3 install -r requirements.txt" >&2
  exit 1
fi

exec python3 -m uvicorn main:app --reload --port 8000
