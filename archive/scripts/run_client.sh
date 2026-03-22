#!/usr/bin/env bash
# Run the Malibu client, spawning the server as a subprocess.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m malibu client uv run python -m malibu server "$@"
