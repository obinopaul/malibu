"""Session-level cost tracking for LLM API usage."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """Pricing per million tokens for a model."""

    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0


DEFAULT_PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4-turbo": ModelPricing(10.00, 30.00),
    "claude-sonnet-4-5": ModelPricing(3.00, 15.00),
    "claude-opus-4": ModelPricing(15.00, 75.00),
    "claude-haiku-3.5": ModelPricing(0.80, 4.00),
}

# Anthropic tiered pricing threshold
_OVER_200K_THRESHOLD = 200_000
_OVER_200K_MULTIPLIER = 1.5


class CostTracker:
    """Tracks cumulative token usage and estimated cost for a session."""

    def __init__(self) -> None:
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost: float = 0.0
        self.call_count: int = 0

    def record_usage(
        self,
        usage: dict[str, Any],
        pricing: ModelPricing | None = None,
    ) -> float:
        """Record token usage from a single LLM call.

        Args:
            usage: Dict with prompt_tokens, completion_tokens keys.
                May include cache_read_input_tokens for prompt caching.
            pricing: Model pricing info. If None, tokens tracked but cost not computed.

        Returns:
            Incremental cost for this call in USD.
        """
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)

        self.total_input_tokens += prompt_tokens
        self.total_output_tokens += completion_tokens
        self.call_count += 1

        incremental_cost = 0.0
        if pricing and (pricing.input_price_per_million or pricing.output_price_per_million):
            input_price = pricing.input_price_per_million
            if prompt_tokens > _OVER_200K_THRESHOLD:
                base_cost = (_OVER_200K_THRESHOLD / 1_000_000) * input_price
                over_cost = (
                    (prompt_tokens - _OVER_200K_THRESHOLD) / 1_000_000
                ) * (input_price * _OVER_200K_MULTIPLIER)
                input_cost = base_cost + over_cost
            else:
                input_cost = (prompt_tokens / 1_000_000) * input_price

            cache_cost = 0.0
            if cache_read_tokens > 0:
                cache_cost = (cache_read_tokens / 1_000_000) * (input_price * 0.1)

            output_cost = (completion_tokens / 1_000_000) * pricing.output_price_per_million
            incremental_cost = input_cost + output_cost + cache_cost
            self.total_cost += incremental_cost

        logger.debug(
            "cost_tracker: call=%d in=%d out=%d cost=+$%.6f total=$%.6f",
            self.call_count, prompt_tokens, completion_tokens,
            incremental_cost, self.total_cost,
        )
        return incremental_cost

    def format_cost(self) -> str:
        """Format the total cost for display."""
        if self.total_cost < 0.01:
            return f"${self.total_cost:.4f}"
        return f"${self.total_cost:.2f}"

    def to_dict(self) -> dict[str, Any]:
        """Export cost data for serialization."""
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "api_call_count": self.call_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CostTracker":
        """Restore a CostTracker from serialized data."""
        tracker = cls()
        tracker.total_cost = data.get("total_cost_usd", 0.0)
        tracker.total_input_tokens = data.get("total_input_tokens", 0)
        tracker.total_output_tokens = data.get("total_output_tokens", 0)
        tracker.call_count = data.get("api_call_count", 0)
        return tracker
