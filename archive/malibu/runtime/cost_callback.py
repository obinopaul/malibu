"""LangChain callback handler for automatic cost tracking.

Integrates with the ``CostTracker`` to automatically record token usage
from every LLM call.  Wire into the agent via ``create_agent(..., callbacks=[cb])``.

Example::

    tracker = CostTracker()
    pricing = DEFAULT_PRICING.get("gpt-4o")
    cb = CostTrackingCallback(tracker, pricing=pricing)
    agent = create_agent(model="openai:gpt-4o", ..., callbacks=[cb])
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from malibu.runtime.cost_tracker import CostTracker, ModelPricing, DEFAULT_PRICING

logger = logging.getLogger(__name__)


class CostTrackingCallback(BaseCallbackHandler):
    """Callback handler that records token usage from every LLM call.

    Attributes:
        tracker: The ``CostTracker`` instance accumulating session costs.
        pricing: Per-model pricing info.  If ``None``, tokens are tracked
                 but cost is not computed.
        model_name: Optional model name used for automatic pricing lookup
                    from ``DEFAULT_PRICING`` when ``pricing`` is ``None``.
    """

    def __init__(
        self,
        tracker: CostTracker,
        *,
        pricing: ModelPricing | None = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__()
        self.tracker = tracker
        self.model_name = model_name

        # Resolve pricing: explicit > lookup by model_name > None
        if pricing is not None:
            self.pricing = pricing
        elif model_name:
            self.pricing = self._resolve_pricing(model_name)
        else:
            self.pricing = None

    @staticmethod
    def _resolve_pricing(model_name: str) -> ModelPricing | None:
        """Look up pricing from ``DEFAULT_PRICING`` by model name.

        Supports both bare names (``gpt-4o``) and provider-prefixed
        names (``openai:gpt-4o``).
        """
        # Direct match
        if model_name in DEFAULT_PRICING:
            return DEFAULT_PRICING[model_name]

        # Strip provider prefix (e.g. "openai:gpt-4o" -> "gpt-4o")
        if ":" in model_name:
            bare = model_name.split(":", 1)[1]
            if bare in DEFAULT_PRICING:
                return DEFAULT_PRICING[bare]

        # Substring match for model families (e.g. "gpt-4o-2024-08-06" matches "gpt-4o")
        for key in sorted(DEFAULT_PRICING.keys(), key=len, reverse=True):
            if key in model_name:
                return DEFAULT_PRICING[key]

        return None

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Record token usage at the end of each LLM call.

        Handles both OpenAI-style and Anthropic-style usage dictionaries
        gracefully.  Silently skips if no usage data is available.
        """
        usage = self._extract_usage(response)
        if not usage:
            return

        try:
            cost = self.tracker.record_usage(usage, pricing=self.pricing)
            logger.debug(
                "cost_callback: recorded usage — in=%d out=%d cost=$%.6f",
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                cost,
            )
        except Exception:
            logger.warning("cost_callback: failed to record usage", exc_info=True)

    @staticmethod
    def _extract_usage(response: LLMResult) -> dict[str, int]:
        """Extract token usage from an LLMResult.

        Checks multiple locations where providers store usage data:
        1. ``response.llm_output["token_usage"]`` (OpenAI)
        2. ``response.llm_output["usage"]`` (Anthropic via langchain)
        3. ``response.llm_output`` directly (fallback)
        4. Individual generation metadata
        """
        # Try llm_output first (most common path)
        llm_output = response.llm_output or {}

        # OpenAI style: {"token_usage": {"prompt_tokens": ..., "completion_tokens": ...}}
        token_usage = llm_output.get("token_usage")
        if isinstance(token_usage, dict) and "prompt_tokens" in token_usage:
            return token_usage

        # Anthropic style: {"usage": {"input_tokens": ..., "output_tokens": ...}}
        usage = llm_output.get("usage")
        if isinstance(usage, dict):
            return _normalize_anthropic_usage(usage)

        # Direct keys in llm_output
        if "prompt_tokens" in llm_output:
            return llm_output

        # Last resort: check individual generation response_metadata
        for generation_list in response.generations:
            for gen in generation_list:
                meta = getattr(gen, "generation_info", {}) or {}
                if "prompt_tokens" in meta:
                    return meta
                # Check message response_metadata (ChatGeneration)
                msg = getattr(gen, "message", None)
                if msg:
                    resp_meta = getattr(msg, "response_metadata", {}) or {}
                    token_usage = resp_meta.get("token_usage") or resp_meta.get("usage")
                    if isinstance(token_usage, dict):
                        if "input_tokens" in token_usage:
                            return _normalize_anthropic_usage(token_usage)
                        if "prompt_tokens" in token_usage:
                            return token_usage

        return {}


def _normalize_anthropic_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Convert Anthropic-style usage keys to OpenAI-style keys.

    Anthropic uses ``input_tokens`` / ``output_tokens`` while OpenAI
    uses ``prompt_tokens`` / ``completion_tokens``.  Maps both,
    preserving ``cache_read_input_tokens`` if present.
    """
    return {
        "prompt_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
        "completion_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
    }
