# Agent Loop Diagnostic
Generated: 2026-03-25T12:13:47.540Z

Tests the SAME 5-step prompt through different agent setups to isolate
where the premature stopping happens.

- **Test 1**: Raw createAgent (pure LangChain) — baseline
- **Test 2**: createMalibuAgent (Malibu wrapper) — does middleware break it?
- **Test 3**: Old harness simulation — the 'continue if tools > 0' bug
- **Test 4**: New harness (always stop) — the fix

---

================================================================================
## Test 1: Raw createAgent (pure LangChain)
================================================================================

Prompt: Do ALL of these steps in order:...

Using: ChatAnthropic (claude-sonnet-4-20250514)

================================================================================
## Test 2: createMalibuAgent (Malibu wrapper + middleware)
================================================================================

Prompt: Do ALL of these steps in order:...

Using: ChatAnthropic (claude-sonnet-4-20250514)

================================================================================
## Test 3: Old Harness Simulation (continue if toolCalls > 0)
================================================================================

Simulates the OLD bug: outer loop keeps re-invoking if any tools were called.

Using: ChatAnthropic (claude-sonnet-4-20250514)
--- Outer loop iteration #1 ---

================================================================================
## Test 4: New Harness (always stop after stream)
================================================================================

This is what the FIX does: one stream() call, always return 'stop'.

Using: ChatAnthropic (claude-sonnet-4-20250514)