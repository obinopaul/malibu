#!/usr/bin/env bash
# Initialize and migrate the PostgreSQL database.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Running Alembic migrations..."
uv run alembic upgrade head
echo "Database ready."
