# Malibu Performance Investigation

Date: 2026-03-15

## Scope and Method

This document investigates why Malibu feels slow in local interactive use.

Method:

- Static source analysis of Malibu's local TUI, ACP, session, agent, tool, and persistence layers.
- Local micro-benchmarks run inside this workspace on 2026-03-15.
- Import-time tracing for hot modules to identify eager heavy imports.

This is intentionally focused on local Malibu performance, not remote model latency.

## Executive Summary

The main Malibu slowdown is not the Deep Agents framework itself.

The dominant issue is Malibu's first-turn bootstrap path:

1. Malibu eagerly imports and initializes a large local runtime before the first prompt can visibly respond.
2. Malibu builds a 47-tool bundle for each session, even when most of those tools are never used.
3. Malibu constructs the chat model object during agent build, and that model construction is expensive in this environment.
4. Malibu persists every streamed session update by rewriting the full session JSON file.
5. The first visible session update is emitted only after `get_or_create_agent()` completes, so the UI appears frozen during agent bootstrap.

ACP exists in the path, but the measured ACP method overhead is small compared with Malibu's first-turn agent build cost.

## Hot Path

The local interactive path is:

`malibu.__main__` -> `malibu.tui.app.MalibuApp` -> `connect_local_agent()` -> ACP client/server bridge -> `SessionManager.get_or_create_agent()` -> `build_agent()` -> `create_deep_agent()` -> ACP stream updates -> `UpdateProcessor` / `ChatScreen`

Key code references:

- TUI bootstrap and local agent connection:
  - `malibu/tui/app.py:108`
  - `malibu/tui/app.py:125`
  - `malibu/tui/app.py:128`
  - `malibu/local_agent_connection.py:44`
- Agent prompt path:
  - `malibu/server/agent.py:221`
  - `malibu/server/agent.py:226`
  - `malibu/server/agent.py:311`
  - `malibu/server/agent.py:438`
- Session and agent build:
  - `malibu/server/sessions.py:339`
  - `malibu/agent/graph.py:34`
  - `malibu/agent/graph.py:125`
  - `malibu/agent/graph.py:173`
- UI update handling:
  - `malibu/tui/services/update_processor.py`
  - `malibu/tui/screens/chat.py`

## Measured Baseline

All timings below were measured locally in this workspace on 2026-03-15.

| Measurement | Result | Notes |
| --- | ---: | --- |
| `create_deep_agent(...)` minimal | about `0.35s` | Deep Agents itself is not the main bottleneck |
| `create_deep_agent(...)` with Malibu middleware | about `0.38s` | Middleware setup alone is still cheap |
| `create_deep_agent(...)` with 47 prebuilt Malibu tools | about `0.35s` | Once tools already exist, agent creation remains cheap |
| `Settings.create_llm()` | about `4.8s` | Model object construction is expensive |
| `build_default_tools(...)` | about `7.7s` | Largest single measured bootstrap cost |
| `build_agent(...)` | about `10.8s` | Dominated by tool and model construction |
| `SessionManager()` | about `0.037s` | Small by itself |
| `register_session(...)` | about `0.011s` | Small by itself |
| `MalibuAgent()` | about `0.029s` | Constructor itself is cheap |
| `MalibuClient()` | about `0.0004s` | Negligible |
| `discover_mcp_servers('.')` | about `0.0000015s` | Negligible with no MCP servers configured |
| ACP local connect context | about `0.956s` total | Includes local agent setup and imports |
| ACP `initialize()` | about `0.0028s` | Minor |
| ACP `new_session()` | about `0.0055s` | Minor |
| First prompt time to first update | about `10.7s` | UI appears blocked until bootstrap completes |
| Second prompt time to first update | about `0.007s` | Reused session is fast |
| `500` persisted session updates | about `1.68s` total | About `3.4ms` per update on average |

Interpretation:

- Malibu's first-turn latency is almost entirely bootstrap.
- Malibu's steady-state same-session latency is much better.
- ACP is not the main first-turn bottleneck.

## Latency Layer 1: Import and Startup

### What happens

Malibu performs substantial eager importing before the first useful token can appear.

Evidence:

- `malibu/tui/app.py:22` eagerly imports `malibu.tui.commands`.
- `malibu/tui/app.py:70` eagerly constructs the default slash-command registry at app init.
- `malibu/agent/tools/registry.py:257` builds the default tool bundle through eager tool factories.
- `malibu/agent/graph.py:71` constructs a model object whenever `llm_api_key` or `llm_base_url` is present.

Measured import observations:

- Importing `malibu.tui.commands` took about `2.55s`.
- Import tracing showed `malibu.agent.tools.registry` at about `12.0s` cumulative import time.
- Import tracing showed `malibu.server.agent` at about `13.9s` cumulative import time.

Import-time trace also showed heavy dependency pull-in through Malibu's startup path, including:

- `transformers`
- `langchain_core.language_models.base`
- `pymupdf`
- shell, browser, file-system, and media tool modules

### Why it matters

Malibu is paying large startup cost for code paths that are not needed for every session:

- browser automation
- image/video generation
- web search and visit tooling
- git worktree operations
- LSP helpers
- shell session helpers

The tool registry is not just "available later". It is part of session bootstrap.

## Latency Layer 2: First-Turn Bootstrap

### What happens

The first prompt is slow because agent creation happens inside the first prompt path.

Critical sequence in `malibu/server/agent.py`:

1. `prompt()` calls `self._session_mgr.get_or_create_agent(session_id, cwd=cwd)` at `malibu/server/agent.py:221`.
2. Only after that does Malibu emit the `UserMessageChunk` at `malibu/server/agent.py:226`.

This ordering means the UI does not even get the initial user echo until after agent creation has finished.

### What `get_or_create_agent()` leads to

`SessionManager.get_or_create_agent()` at `malibu/server/sessions.py:339` creates the session agent on demand. That path eventually calls:

- `build_agent(...)` at `malibu/agent/graph.py:34`
- `build_default_tools(...)` at `malibu/agent/tools/registry.py:257`
- `settings.create_llm()` via `malibu/agent/graph.py:71`
- `create_deep_agent(...)` at `malibu/agent/graph.py:173`

### Measured impact

- First prompt time to first update: about `10.7s`
- Second prompt time to first update: about `0.007s`

This is the clearest proof in the investigation:

- Malibu is not uniformly slow on every turn.
- Malibu is specifically paying a large one-time session bootstrap penalty.

## Latency Layer 3: Per-Stream Update Overhead

### What happens

Malibu records every streamed session update and TUI event into session history, then rewrites the whole session JSON file.

Relevant code:

- `malibu/server/agent.py:438`
- `malibu/server/agent.py:451`
- `malibu/server/sessions.py:162`
- `malibu/server/sessions.py:172`
- `malibu/server/sessions.py:135`

At `malibu/server/sessions.py:135`, `_save_record()` writes the entire session record using:

```python
file_path.write_text(json.dumps(record, indent=2, ensure_ascii=True), encoding="utf-8")
```

That means every new event causes:

- append to in-memory history
- full JSON serialization of the whole record
- full file rewrite

### Measured impact

- `500` `record_session_update()` calls took about `1.68s` total.

This does not explain the `10.7s` first-turn stall, but it is meaningful steady-state overhead when an agent streams lots of chunks, tool starts, tool progress events, plan updates, and TUI events.

### Why it matters

Malibu's streaming model is chatty by design. The persistence layer amplifies that cost by doing synchronous whole-record writes on every event.

## Latency Layer 4: Tool-Specific Latency

### Large always-on tool surface

Malibu's default session tool bundle contains about `47` tools. Categories observed in the built bundle:

- core coding and file tools
- shell session tools
- browser tools
- web search and web visit tools
- image and video generation tools
- git tools

Representative sources:

- `malibu/agent/tools/registry.py`
- `malibu/agent/tool_server/tools/browser/*`
- `malibu/agent/tool_server/tools/file_system/*`
- `malibu/agent/tool_server/tools/shell/*`
- `malibu/agent/tool_server/tools/web/*`
- `malibu/git/operations.py`
- `malibu/git/worktree.py`

Even if a user only wants basic coding, Malibu still pays the construction/import cost of the broader platform.

### Sleep sites

The repos differ materially in explicit sleep usage:

- Malibu sleep sites: about `39`
- DeepAgentCLI sleep sites: about `6`

Malibu sleep examples on the interactive path:

- `malibu/tui/app.py:147` -> `await asyncio.sleep(0.25)`
- `malibu/tui/screens/chat.py:719` -> `await asyncio.sleep(1.5)`

Malibu browser and tool-server examples:

- `malibu/agent/tool_server/browser/browser.py`
- `malibu/agent/tool_server/tools/browser/click.py`
- `malibu/agent/tool_server/tools/browser/enter_text.py`
- `malibu/agent/tool_server/tools/browser/navigate.py`
- `malibu/agent/tool_server/tools/browser/wait.py`

Some of those sleeps are probably correctness waits for browser automation, but the key problem is that Malibu imports and exposes those subsystems by default even for sessions that never use them.

## SessionManager Overhead

`SessionManager` adds more than agent memoization.

Observed responsibilities:

- skill loading and registration on init
- plugin scan on init
- hook manager creation
- session-start hook execution
- cost tracker and callback setup
- session bootstrap payload/history management

Relevant code:

- `malibu/server/sessions.py:48`
- `malibu/server/sessions.py:56`
- `malibu/server/sessions.py:66`
- `malibu/server/sessions.py:262`
- `malibu/server/sessions.py:297`
- `malibu/server/sessions.py:323`

Measured note:

- `SessionManager()` itself was cheap, about `0.037s`, but it still adds optional subsystem work that Malibu pays even before the first useful completion.

One observed local warning during measurement was plugin scanning touching a temp plugin path and logging an access-denied warning. That warning was not the dominant bottleneck, but it confirms that plugin discovery is part of the default startup path.

## Major vs Minor Contributors

### Major contributors

1. Eager import/bootstrap cost in Malibu's startup path.
2. `build_default_tools(...)` constructing the full 47-tool bundle.
3. `Settings.create_llm()` constructing the provider model object.
4. First-turn on-demand agent creation in `get_or_create_agent()`.
5. Synchronous per-event session persistence.
6. Optional subsystems loaded by default: skills, plugins, hooks, cost tracking.

### Minor contributors

1. ACP `initialize()` and `new_session()` method calls.
2. `MalibuClient()` construction.
3. MCP discovery when no MCP servers are configured.

ACP is present, but the measured ACP method overhead is orders of magnitude smaller than Malibu's first-turn agent bootstrap.

## Conclusion

Malibu is slower than a simpler Deep Agents CLI primarily because Malibu is doing much more work before the first prompt can visibly respond.

The most important conclusion from this investigation is:

- The Deep Agents framework is not the main problem.
- Malibu's first-turn bootstrap path is the problem.

If Malibu becomes faster, it will happen by reducing or deferring bootstrap work, not by replacing Deep Agents first.

## Evidence Index

- Local TUI startup path: `malibu/tui/app.py:22`, `malibu/tui/app.py:70`, `malibu/tui/app.py:108`, `malibu/tui/app.py:125`, `malibu/tui/app.py:128`
- Local ACP bridge: `malibu/local_agent_connection.py:44`
- First prompt ordering: `malibu/server/agent.py:221`, `malibu/server/agent.py:226`
- Session update persistence: `malibu/server/agent.py:438`, `malibu/server/agent.py:451`, `malibu/server/sessions.py:135`, `malibu/server/sessions.py:162`, `malibu/server/sessions.py:172`
- Agent build path: `malibu/server/sessions.py:339`, `malibu/agent/graph.py:34`, `malibu/agent/graph.py:125`, `malibu/agent/graph.py:173`
- Model construction condition: `malibu/agent/graph.py:71`
- Tool registry: `malibu/agent/tools/registry.py:257`
- Middleware stack: `malibu/agent/graph.py:85`, `malibu/agent/graph.py:103`, `malibu/agent/graph.py:108`, `malibu/agent/graph.py:111`
- TUI sleep sites: `malibu/tui/app.py:147`, `malibu/tui/screens/chat.py:719`
