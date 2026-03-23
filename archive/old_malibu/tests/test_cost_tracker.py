"""Tests for malibu.runtime.cost_tracker."""

import pytest

from malibu.runtime.cost_tracker import CostTracker, ModelPricing, DEFAULT_PRICING


def test_record_usage_tracks_tokens() -> None:
    tracker = CostTracker()
    tracker.record_usage({"prompt_tokens": 100, "completion_tokens": 50})
    assert tracker.total_input_tokens == 100
    assert tracker.total_output_tokens == 50
    assert tracker.call_count == 1


def test_record_usage_accumulates() -> None:
    tracker = CostTracker()
    tracker.record_usage({"prompt_tokens": 100, "completion_tokens": 50})
    tracker.record_usage({"prompt_tokens": 200, "completion_tokens": 100})
    assert tracker.total_input_tokens == 300
    assert tracker.total_output_tokens == 150
    assert tracker.call_count == 2


def test_record_usage_with_pricing() -> None:
    tracker = CostTracker()
    pricing = ModelPricing(input_price_per_million=2.50, output_price_per_million=10.00)
    # Use small token count to avoid tiered pricing threshold
    cost = tracker.record_usage(
        {"prompt_tokens": 100_000, "completion_tokens": 50_000},
        pricing=pricing,
    )
    # input: 100K/1M * 2.50 = 0.25, output: 50K/1M * 10 = 0.50
    assert cost == pytest.approx(0.75)
    assert tracker.total_cost == pytest.approx(0.75)


def test_record_usage_without_pricing() -> None:
    tracker = CostTracker()
    cost = tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    assert cost == 0.0
    assert tracker.total_cost == 0.0


def test_format_cost_small() -> None:
    tracker = CostTracker()
    tracker.total_cost = 0.005
    assert tracker.format_cost() == "$0.0050"


def test_format_cost_large() -> None:
    tracker = CostTracker()
    tracker.total_cost = 1.234
    assert tracker.format_cost() == "$1.23"


def test_round_trip_serialization() -> None:
    tracker = CostTracker()
    pricing = ModelPricing(input_price_per_million=3.00, output_price_per_million=15.00)
    tracker.record_usage({"prompt_tokens": 500, "completion_tokens": 200}, pricing=pricing)
    tracker.record_usage({"prompt_tokens": 300, "completion_tokens": 100}, pricing=pricing)

    data = tracker.to_dict()
    restored = CostTracker.from_dict(data)

    assert restored.total_input_tokens == tracker.total_input_tokens
    assert restored.total_output_tokens == tracker.total_output_tokens
    assert restored.total_cost == pytest.approx(tracker.total_cost)
    assert restored.call_count == tracker.call_count


def test_default_pricing_has_common_models() -> None:
    assert "gpt-4o" in DEFAULT_PRICING
    assert "claude-sonnet-4-5" in DEFAULT_PRICING
    assert DEFAULT_PRICING["gpt-4o"].input_price_per_million > 0


def test_cache_read_tokens() -> None:
    tracker = CostTracker()
    pricing = ModelPricing(input_price_per_million=10.00, output_price_per_million=30.00)
    cost = tracker.record_usage(
        {"prompt_tokens": 1000, "completion_tokens": 500, "cache_read_input_tokens": 2000},
        pricing=pricing,
    )
    # input: 1000/1M * 10 = 0.01, output: 500/1M * 30 = 0.015, cache: 2000/1M * 1.0 = 0.002
    assert cost == pytest.approx(0.01 + 0.015 + 0.002)
