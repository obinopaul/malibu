.PHONY: install check test lint format types migrate run-server run-client run-duet run-api clean

# ── Bootstrap ──────────────────────────────────────────────────────
install:
	uv sync --all-extras --dev
	@echo "✓ Environment ready. Copy .env.example → .env and fill in your values."

# ── Quality ────────────────────────────────────────────────────────
check: format lint types

format:
	uv run ruff format malibu/ tests/

lint:
	uv run ruff check malibu/ tests/ --fix

types:
	uv run ty check malibu/

# ── Testing ────────────────────────────────────────────────────────
test:
	uv run python -m pytest tests/ -v --timeout=60

test-cov:
	uv run python -m pytest tests/ -v --cov=malibu --cov-report=term-missing --timeout=60

# ── Database ───────────────────────────────────────────────────────
migrate:
	uv run alembic upgrade head

migrate-create:
	@read -p "Migration message: " msg; uv run alembic revision --autogenerate -m "$$msg"

# ── Run ────────────────────────────────────────────────────────────
run-server:
	uv run python -m malibu server

run-client:
	uv run python -m malibu client

run-duet:
	uv run python -m malibu duet

run-api:
	uv run python -m malibu api

# ── Docker ─────────────────────────────────────────────────────────
docker-up:
	docker compose up -d

docker-down:
	docker compose down

# ── Cleanup ────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .ruff_cache .mypy_cache dist build *.egg-info
