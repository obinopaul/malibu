# DeepAgentCLI Performance Investigation

Date: 2026-03-15

## Scope and Limitation

This document investigates why `external/deepagents_cli` is likely faster than Malibu in normal interactive use.

Method:

- Static source analysis of `external/deepagents_cli`.
- Comparison against Malibu's measured local behavior.

Important limitation:

- Direct runtime benchmarking of `external/deepagents_cli` is blocked in this workspace.
- Local execution attempts failed because this repo's installed `deepagents` package does not expose `LocalShellBackend`, which `external/deepagents_cli/agent.py` imports.
- Importing the full app path also hit a missing optional dependency: `tomli_w`.

Therefore:

- Any DeepAgentCLI performance conclusion here is source-backed inference, not a local end-to-end benchmark result.

## Executive Summary

DeepAgentCLI is not just "smaller". Its default interactive architecture is materially leaner in the critical path:

1. Its CLI entry path avoids importing the heavy agent module until needed.
2. Its normal Textual path renders directly from the agent stream instead of wrapping the local session in ACP client/server messaging.
3. Its CLI entry path starts with a much smaller explicit extra tool set.
4. Hook dispatch is cached and offloaded to threads.
5. Its default local path appears closer to stock Deep Agents usage, with less Malibu-specific bootstrap work in front of the first visible UI response.

## Repo Shape Contrast

Measured source counts:

- Malibu Python files: about `274`
- `external/deepagents_cli` Python files: about `59`

Measured sleep-site counts:

- Malibu sleep sites: about `39`
- DeepAgentCLI sleep sites: about `6`

File count alone does not prove runtime speed, but it is a useful architectural signal: Malibu is a much broader product surface.

## Hot Path

Normal DeepAgentCLI interactive flow:

`deepagents_cli.main` -> lazy import of `create_cli_agent()` -> agent creation -> `deepagents_cli.app` -> `execute_task_textual()` -> direct Textual rendering

Important source references:

- Lazy import note in CLI entry:
  - `external/deepagents_cli/main.py:38`
- Lazy import of `create_cli_agent` in run path:
  - `external/deepagents_cli/main.py:548`
  - `external/deepagents_cli/main.py:727`
  - `external/deepagents_cli/app.py:3209`
- Direct Textual execution path:
  - `external/deepagents_cli/app.py:2188`
  - `external/deepagents_cli/textual_adapter.py:482`

## Speed Enabler 1: Lazy Import Discipline

DeepAgentCLI explicitly avoids importing its heavy agent module at startup.

The code says so directly:

- `external/deepagents_cli/main.py:38`

That comment exists because the authors intentionally kept the heavy agent module out of the CLI startup path until necessary.

This is different from Malibu, where the TUI module eagerly imports command infrastructure at module import time:

- `malibu/tui/app.py:22`
- `malibu/tui/app.py:70`

Why it matters:

- CLI startup stays lighter.
- Help, argument parsing, and top-level boot do not automatically pay full agent import cost.

## Speed Enabler 2: Normal UI Path Does Not Use ACP

DeepAgentCLI's default path is the Textual app, not an ACP loop.

Evidence:

- `external/deepagents_cli/main.py:480` describes `--acp` as an opt-in mode.
- `external/deepagents_cli/app.py:2188` calls `execute_task_textual(...)`.
- `external/deepagents_cli/textual_adapter.py:482` streams directly from `agent.astream(...)` into UI rendering.

Implication:

- The normal local path does not need a local ACP client/server bridge to render agent output.
- There is less message wrapping and less protocol plumbing on the hot path to the user interface.

This does not prove ACP is expensive by itself, but it removes one architectural layer that Malibu currently keeps in the local path.

## Speed Enabler 3: Smaller Explicit Extra Tool List in the CLI Entry Path

DeepAgentCLI's interactive entry path starts with a much smaller explicit extra tool list:

- `http_request`
- `fetch_url`
- optional `web_search`
- optional MCP tools

Relevant source:

- `external/deepagents_cli/main.py:553`
- `external/deepagents_cli/main.py:588`
- `external/deepagents_cli/main.py:589`
- `external/deepagents_cli/main.py:592`
- `external/deepagents_cli/main.py:609`
- `external/deepagents_cli/main.py:730`
- `external/deepagents_cli/main.py:747`
- `external/deepagents_cli/main.py:749`
- `external/deepagents_cli/main.py:765`
- `external/deepagents_cli/tools.py:35`
- `external/deepagents_cli/tools.py:183`

This does not mean DeepAgentCLI has no other tool capability. Its `create_cli_agent()` still wires substantial Deep Agents features such as:

- `MemoryMiddleware`
- `SkillsMiddleware`
- `LocalContextMiddleware`
- summarization middleware
- composite backend routing

Relevant source:

- `external/deepagents_cli/agent.py:14`
- `external/deepagents_cli/agent.py:16`
- `external/deepagents_cli/agent.py:45`
- `external/deepagents_cli/agent.py:658`
- `external/deepagents_cli/agent.py:677`
- `external/deepagents_cli/agent.py:715`
- `external/deepagents_cli/agent.py:748`
- `external/deepagents_cli/agent.py:766`

So the important distinction is not "DeepAgentCLI has no features". It is:

- DeepAgentCLI's normal entry path adds a smaller explicit tool surface before the agent runs.
- Malibu always constructs a much larger default local tool platform.

## Speed Enabler 4: Hook Dispatch Offloaded to Threads

DeepAgentCLI's hooks system is lightweight and explicitly offloads blocking work.

Relevant source:

- `external/deepagents_cli/hooks.py:158`
- `external/deepagents_cli/hooks.py:178`
- `external/deepagents_cli/hooks.py:39`

Observed design traits:

- Hook config is cached after first load.
- Blocking subprocess hook dispatch is moved to `asyncio.to_thread(...)`.
- Fire-and-forget hooks keep strong task references to avoid task loss.

Compared with Malibu:

- Malibu's hook manager is richer and more integrated into session/bootstrap flow.
- DeepAgentCLI's hooks appear designed to minimize event-loop blocking in the common path.

## Speed Enabler 5: More Direct UI Streaming

DeepAgentCLI's Textual adapter is built around direct stream consumption:

- `external/deepagents_cli/textual_adapter.py:482`
- `external/deepagents_cli/textual_adapter.py:605`

The app uses a background worker to keep the UI responsive:

- `external/deepagents_cli/app.py:2166`
- `external/deepagents_cli/app.py:2188`

This is still a sophisticated Textual UI, but it is a direct UI-to-agent arrangement rather than a local ACP client talking to a local ACP server that then re-emits UI updates.

## Sleep Behavior

DeepAgentCLI has far fewer sleep sites than Malibu in the source snapshot examined.

Examples on the UI side:

- `external/deepagents_cli/app.py:1086`
- `external/deepagents_cli/app.py:1184`

These are short `0.1s` UI sleeps, not the large collection of browser and tool-server sleeps seen in Malibu.

Important caveat:

- Sleep count is not the whole story.
- The stronger performance signal is that Malibu both contains more fixed waits and eagerly exposes more subsystems where those waits live.

## What Cannot Be Proven Yet

The local environment currently prevents direct DeepAgentCLI runtime benchmarking.

Observed blockers:

1. `external/deepagents_cli/agent.py` imports `LocalShellBackend`, but the installed `deepagents` package in this workspace does not provide it.
2. Importing the app path also failed because `tomli_w` is missing locally.

Because of that, these statements remain source-backed inference:

- DeepAgentCLI's first-turn bootstrap is likely lower than Malibu's.
- DeepAgentCLI's default local path likely feels faster because it uses fewer layers and smaller entry-path tool wiring.

Those inferences are strong, but they are still inferences until the environment is aligned.

## Conclusion

DeepAgentCLI appears faster for structural reasons, not magical reasons:

- lazier startup imports
- no ACP in the default local UI path
- smaller explicit extra tool list in the interactive entry flow
- lighter hook dispatch mechanics
- a runtime shape that stays closer to stock Deep Agents + Textual

The investigation does not support the claim that Malibu is slow because "Deep Agents is slow".

Instead, the comparison suggests:

- Malibu is slower because Malibu adds more local platform machinery in front of the first visible response.

## Evidence Index

- Lazy import comment: `external/deepagents_cli/main.py:38`
- Interactive entry imports: `external/deepagents_cli/main.py:548`, `external/deepagents_cli/main.py:727`
- Default ACP is opt-in: `external/deepagents_cli/main.py:480`
- Extra tool list in entry path: `external/deepagents_cli/main.py:553`, `external/deepagents_cli/main.py:588`, `external/deepagents_cli/main.py:589`, `external/deepagents_cli/main.py:592`, `external/deepagents_cli/main.py:609`, `external/deepagents_cli/main.py:747`, `external/deepagents_cli/main.py:749`, `external/deepagents_cli/main.py:765`
- Direct Textual execution: `external/deepagents_cli/app.py:2188`, `external/deepagents_cli/textual_adapter.py:482`
- Hook offloading: `external/deepagents_cli/hooks.py:158`, `external/deepagents_cli/hooks.py:178`
- Middleware/backend stack: `external/deepagents_cli/agent.py:14`, `external/deepagents_cli/agent.py:16`, `external/deepagents_cli/agent.py:45`, `external/deepagents_cli/agent.py:658`, `external/deepagents_cli/agent.py:677`, `external/deepagents_cli/agent.py:715`, `external/deepagents_cli/agent.py:748`, `external/deepagents_cli/agent.py:766`
