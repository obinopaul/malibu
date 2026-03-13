"""Context compaction — summarise and trim conversation history.

When the token usage of an agent thread approaches the model's context
window, the ``CompactionManager`` replaces older messages with a concise
LLM-generated summary while preserving recent messages for continuity.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from malibu.config import Settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Compaction threshold
# ═══════════════════════════════════════════════════════════════════
COMPACTION_THRESHOLD = 0.80  # Trigger at 80% of context window


def should_compact(usage_tokens: int, model_context_window: int) -> bool:
    """Return ``True`` when token usage exceeds the compaction threshold.

    Args:
        usage_tokens: Current total token count (prompt + completion so far).
        model_context_window: Maximum context window size for the model.

    Returns:
        Whether the conversation should be compacted.
    """
    if model_context_window <= 0:
        return False
    ratio = usage_tokens / model_context_window
    return ratio >= COMPACTION_THRESHOLD


# ═══════════════════════════════════════════════════════════════════
# Summarisation prompt
# ═══════════════════════════════════════════════════════════════════
COMPACTION_PROMPT = """\
You are a conversation summariser for a coding assistant called Malibu.

Below is a conversation between a user and the assistant.  Produce a
concise summary that preserves:
1. **Key decisions** — what was agreed, what was rejected.
2. **Artifacts created or modified** — file paths, function names.
3. **Open questions** — anything still unresolved.
4. **Current task state** — what step the assistant is on.

Be factual and terse.  Use bullet points.  Do NOT include greetings or
filler.  The summary will replace the original messages in the context
window, so completeness matters more than readability.

--- CONVERSATION START ---
{conversation}
--- CONVERSATION END ---

Summary:"""


# ═══════════════════════════════════════════════════════════════════
# CompactionManager
# ═══════════════════════════════════════════════════════════════════
class CompactionManager:
    """Handles context-window compaction for Malibu agent threads.

    Usage::

        mgr = CompactionManager()
        if should_compact(token_count, context_window):
            await mgr.compact_state(agent, thread_id, settings)
    """

    # Number of recent messages to keep verbatim after compaction.
    RECENT_MESSAGES_TO_KEEP: int = 10

    def __init__(self) -> None:
        self._checkpointer = MemorySaver()

    # ── Public API ────────────────────────────────────────────────

    async def summarize_conversation(
        self,
        messages: list[BaseMessage],
        settings: Settings,
        *,
        model_id: str | None = None,
    ) -> str:
        """Summarise a list of messages into a compact text block.

        Args:
            messages: The conversation messages to summarise.
            settings: Application configuration (for LLM resolution).
            model_id: Optional LLM model override.

        Returns:
            A summary string.
        """
        conversation_text = self._format_messages(messages)
        prompt = COMPACTION_PROMPT.format(conversation=conversation_text)

        # Build a minimal, tool-less agent for the summarisation call
        model: str | BaseChatModel = model_id or settings.llm_model
        if settings.llm_api_key or settings.llm_base_url:
            model = settings.create_llm()

        summariser = create_agent(
            model=model,
            tools=[],
            system_prompt="You are a concise conversation summariser.",
            checkpointer=self._checkpointer,
        )

        config: dict[str, Any] = {
            "configurable": {"thread_id": "compaction-summariser"}
        }
        result = await summariser.ainvoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config=config,
        )

        # Extract the summary from the response
        for msg in reversed(result.get("messages", [])):
            content = getattr(msg, "content", None) or ""
            if getattr(msg, "type", None) == "ai" and content:
                return content

        return "(compaction produced no summary)"

    async def compact_state(
        self,
        agent: CompiledStateGraph,
        thread_id: str,
        settings: Settings,
        *,
        model_id: str | None = None,
        hook_manager: Any | None = None,
    ) -> None:
        """Replace old messages in a thread with a summary + recent messages.

        This mutates the agent's checkpointed state for the given
        ``thread_id``, keeping only ``RECENT_MESSAGES_TO_KEEP`` recent
        messages and prepending an AI message with the summary.

        Args:
            agent: The compiled agent graph whose state will be updated.
            thread_id: The thread to compact.
            settings: Application configuration.
            model_id: Optional LLM model override.
            hook_manager: Optional HookManager for PRE_COMPACT hook.
        """
        # Fire PRE_COMPACT hook — skip compaction if blocked
        if hook_manager is not None:
            try:
                from malibu.hooks.models import HookEvent

                if hook_manager.has_hooks_for(HookEvent.PRE_COMPACT):
                    outcome = hook_manager.run_hooks(HookEvent.PRE_COMPACT)
                    if outcome.blocked:
                        logger.info("Compaction blocked by hook: %s", outcome.block_reason)
                        return
            except Exception:
                pass

        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        state = await agent.aget_state(config)
        messages: list[BaseMessage] = state.values.get("messages", [])

        if len(messages) <= self.RECENT_MESSAGES_TO_KEEP:
            logger.debug(
                "Skipping compaction for thread %s — only %d messages",
                thread_id,
                len(messages),
            )
            return

        # Split into old (to summarise) and recent (to keep verbatim)
        cutoff = len(messages) - self.RECENT_MESSAGES_TO_KEEP
        old_messages = messages[:cutoff]
        recent_messages = messages[cutoff:]

        logger.info(
            "Compacting thread %s: summarising %d messages, keeping %d recent",
            thread_id,
            len(old_messages),
            len(recent_messages),
        )

        summary = await self.summarize_conversation(
            old_messages, settings, model_id=model_id
        )

        # Build the replacement message list
        summary_message = AIMessage(
            content=(
                f"[Context compaction — the following is a summary of the "
                f"earlier conversation]\n\n{summary}"
            )
        )
        new_messages = [summary_message] + recent_messages

        # Update the agent's checkpointed state
        await agent.aupdate_state(config, {"messages": new_messages})

        logger.info(
            "Compaction complete for thread %s: %d -> %d messages",
            thread_id,
            len(messages),
            len(new_messages),
        )

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _format_messages(messages: list[BaseMessage]) -> str:
        """Render messages as a plain-text transcript for the summariser."""
        lines: list[str] = []
        for msg in messages:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "") or ""
            if role == "human":
                lines.append(f"USER: {content}")
            elif role == "ai":
                lines.append(f"ASSISTANT: {content}")
            elif role == "system":
                lines.append(f"SYSTEM: {content}")
            elif role == "tool":
                tool_name = getattr(msg, "name", "tool")
                # Truncate long tool outputs
                display = content[:500] + "..." if len(content) > 500 else content
                lines.append(f"TOOL ({tool_name}): {display}")
            else:
                lines.append(f"{role.upper()}: {content}")
        return "\n".join(lines)
