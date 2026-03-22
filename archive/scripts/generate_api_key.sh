#!/usr/bin/env bash
# Generate a new API key for Malibu.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m malibu generate-key
