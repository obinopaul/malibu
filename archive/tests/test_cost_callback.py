"""Tests for malibu.runtime.cost_callback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from malibu.runtime.cost_callback import CostTrackingCallback, _normalize_anthropic_usage
from malibu.runtime.cost_tracker import CostTracker, ModelPricing, DEFAULT_PRICING


# ═══════════════════════════════════════════════════════════════════
# Helper: Build a mock LLMResult
# ═══════════════════════════════════════════════════════════════════

def _make_llm_result(llm_output: dict | None = None) -> MagicMock:
    """Build a mock LLMResult with configurable llm_output."""
    result = MagicMock()
    result.llm_output = llm_output
    result.generations = [[]]
    return result


def _make_llm_result_with_generation_meta(meta: dict) -> MagicMock:
    """Build a mock LLMResult where usage is in generation_info."""
    result = MagicMock()
    result.llm_output = {}

    gen = MagicMock()
    gen.generation_info = meta
    gen.message = None
    result.generations = [[gen]]
    return result


def _make_llm_result_with_response_metadata(token_usage: dict) -> MagicMock:
    """Build a mock LLMResult where usage is in message.response_metadata."""
    result = MagicMock()
    result.llm_output = {}

    msg = MagicMock()
    msg.response_metadata = {"token_usage": token_usage}
    gen = MagicMock()
    gen.generation_info = {}
    gen.message = msg
    result.generations = [[gen]]
    return result


# ═══════════════════════════════════════════════════════════════════
# CostTrackingCallback tests
# ═══════════════════════════════════════════════════════════════════

class TestCostTrackingCallback:
    def test_records_openai_usage(self) -> None:
        tracker = CostTracker()
        pricing = ModelPricing(input_price_per_million=2.50, output_price_per_million=10.00)
        cb = CostTrackingCallback(tracker, pricing=pricing)

        result = _make_llm_result({
            "token_usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        })
        cb.on_llm_end(result)

        assert tracker.total_input_tokens == 1000
        assert tracker.total_output_tokens == 500
        assert tracker.call_count == 1
        assert tracker.total_cost > 0

    def test_records_anthropic_usage(self) -> None:
        tracker = CostTracker()
        pricing = ModelPricing(input_price_per_million=3.00, output_price_per_million=15.00)
        cb = CostTrackingCallback(tracker, pricing=pricing)

        result = _make_llm_result({
            "usage": {"input_tokens": 2000, "output_tokens": 800},
        })
        cb.on_llm_end(result)

        assert tracker.total_input_tokens == 2000
        assert tracker.total_output_tokens == 800
        assert tracker.call_count == 1

    def test_no_usage_data_does_not_crash(self) -> None:
        tracker = CostTracker()
        cb = CostTrackingCallback(tracker)

        result = _make_llm_result({})
        cb.on_llm_end(result)

        assert tracker.call_count == 0
        assert tracker.total_cost == 0.0

    def test_none_llm_output_does_not_crash(self) -> None:
        tracker = CostTracker()
        cb = CostTrackingCallback(tracker)

        result = _make_llm_result(None)
        cb.on_llm_end(result)

        assert tracker.call_count == 0

    def test_without_pricing_tracks_tokens(self) -> None:
        tracker = CostTracker()
        cb = CostTrackingCallback(tracker)

        result = _make_llm_result({
            "token_usage": {"prompt_tokens": 500, "completion_tokens": 200},
        })
        cb.on_llm_end(result)

        assert tracker.total_input_tokens == 500
        assert tracker.total_output_tokens == 200
        assert tracker.total_cost == 0.0

    def test_accumulates_across_calls(self) -> None:
        tracker = CostTracker()
        pricing = ModelPricing(input_price_per_million=2.50, output_price_per_million=10.00)
        cb = CostTrackingCallback(tracker, pricing=pricing)

        for _ in range(3):
            result = _make_llm_result({
                "token_usage": {"prompt_tokens": 100, "completion_tokens": 50},
            })
            cb.on_llm_end(result)

        assert tracker.call_count == 3
        assert tracker.total_input_tokens == 300
        assert tracker.total_output_tokens == 150

    def test_generation_info_fallback(self) -> None:
        tracker = CostTracker()
        pricing = ModelPricing(input_price_per_million=2.50, output_price_per_million=10.00)
        cb = CostTrackingCallback(tracker, pricing=pricing)

        result = _make_llm_result_with_generation_meta({
            "prompt_tokens": 800, "completion_tokens": 300,
        })
        cb.on_llm_end(result)

        assert tracker.total_input_tokens == 800
        assert tracker.total_output_tokens == 300

    def test_response_metadata_fallback(self) -> None:
        tracker = CostTracker()
        pricing = ModelPricing(input_price_per_million=2.50, output_price_per_million=10.00)
        cb = CostTrackingCallback(tracker, pricing=pricing)

        result = _make_llm_result_with_response_metadata({
            "prompt_tokens": 600, "completion_tokens": 250,
        })
        cb.on_llm_end(result)

        assert tracker.total_input_tokens == 600
        assert tracker.total_output_tokens == 250


# ═══════════════════════════════════════════════════════════════════
# Pricing resolution tests
# ═══════════════════════════════════════════════════════════════════

class TestPricingResolution:
    def test_resolve_by_model_name(self) -> None:
        cb = CostTrackingCallback(CostTracker(), model_name="gpt-4o")
        assert cb.pricing is not None
        assert cb.pricing.input_price_per_million > 0

    def test_resolve_by_provider_prefix(self) -> None:
        cb = CostTrackingCallback(CostTracker(), model_name="openai:gpt-4o")
        assert cb.pricing is not None

    def test_resolve_by_substring_match(self) -> None:
        cb = CostTrackingCallback(CostTracker(), model_name="gpt-4o-2024-08-06")
        assert cb.pricing is not None

    def test_unknown_model_no_pricing(self) -> None:
        cb = CostTrackingCallback(CostTracker(), model_name="totally-unknown-model-xyz")
        assert cb.pricing is None

    def test_explicit_pricing_overrides_model_name(self) -> None:
        custom = ModelPricing(input_price_per_million=99.0, output_price_per_million=199.0)
        cb = CostTrackingCallback(CostTracker(), pricing=custom, model_name="gpt-4o")
        assert cb.pricing.input_price_per_million == 99.0


# ═══════════════════════════════════════════════════════════════════
# Anthropic usage normalization
# ═══════════════════════════════════════════════════════════════════

class TestNormalizeAnthropicUsage:
    def test_maps_input_output_tokens(self) -> None:
        result = _normalize_anthropic_usage({"input_tokens": 100, "output_tokens": 50})
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50

    def test_preserves_cache_tokens(self) -> None:
        result = _normalize_anthropic_usage({
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 200,
        })
        assert result["cache_read_input_tokens"] == 200

    def test_handles_missing_keys(self) -> None:
        result = _normalize_anthropic_usage({})
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert result["cache_read_input_tokens"] == 0
