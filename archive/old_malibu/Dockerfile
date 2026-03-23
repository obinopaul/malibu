# ═══════════════════════════════════════════════════════════════════
# Malibu — Multi-stage Docker build
# ═══════════════════════════════════════════════════════════════════
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev --no-editable

COPY . .
RUN uv pip install --no-cache-dir .

# ── Runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN groupadd --gid 1000 malibu && \
    useradd --uid 1000 --gid malibu --create-home malibu

WORKDIR /app
COPY --from=builder /app /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

USER malibu

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "malibu"]
CMD ["api"]
