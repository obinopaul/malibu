#!/usr/bin/env bash
# Run both agent and client in a single process (duet mode).
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m malibu duet "$@"
