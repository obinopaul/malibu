#!/usr/bin/env bash
# Run the Malibu ACP agent on stdio.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m malibu server "$@"
