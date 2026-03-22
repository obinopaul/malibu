# Malibu Performance Recommendations

Date: 2026-03-15

## Goal

Make Malibu feel fast in local interactive use without rewriting the product from scratch and without abandoning Deep Agents.

The recommendations below are ordered by expected impact on local perceived latency.

## Recommended Strategy

Do not start with a Rust rewrite.

Start by removing work from Malibu's first-turn bootstrap path. That is where the investigation found the biggest performance penalty:

- `build_default_tools(...)` about `7.7s`
- `Settings.create_llm()` about `4.8s`
- first prompt time to first update about `10.7s`
- second prompt time to first update about `0.007s`

That profile says:

- The problem is mostly first-turn bootstrap.
- The fastest wins come from deferring or skipping work before the first visible update.

## P0: High Impact, Low to Moderate Risk

### 1. Stop building the full 47-tool bundle for every session

Recommendation:

- Replace the current always-on tool registry with tool packs.
- Default local interactive sessions should boot only a "core coding" pack:
  - `write_todos`
  - `read_file`
  - `write_file`
  - `edit_file`
  - `ls`
  - `grep`
  - `execute`
  - `apply_patch`
  - `ast_grep`
  - `str_replace`
  - `lsp`
- Move these into lazy or opt-in packs:
  - browser
  - web
  - media
  - git
  - shell session management
  - MCP-derived tools

Why:

- `build_default_tools(...)` is Malibu's largest measured bootstrap cost.
- Malibu currently pays for browser/media/git/web subsystems even when the user is only asking for normal coding work.

Implementation direction:

- Split `malibu/agent/tools/registry.py` into pack-specific factories.
- Add a small `build_core_tools(...)` fast path.
- Load optional packs only when:
  - user enables them in config
  - the mode requires them
  - an explicit command turns them on for the session

Success target:

- Reduce tool build time from about `7.7s` to under `1.5s` for default coding sessions.

### 2. Cache or defer `Settings.create_llm()`

Recommendation:

- Avoid constructing the provider model object during every first local session build when a reusable model instance or cached factory can be used.

Why:

- `Settings.create_llm()` measured about `4.8s`.
- `create_deep_agent(...)` itself was cheap once the model and tools were already prepared.

Implementation direction:

- Memoize model instances by `(provider, model_name, api_key, base_url)`.
- Keep the cache process-local and invalidate when model settings change.
- If possible, prefer passing the model string through the fast path when no custom base URL or per-session override requires a concrete object.

Success target:

- Reduce model construction from about `4.8s` to near-zero on repeated local sessions in the same process.

### 3. Emit the first visible UI update before agent creation

Recommendation:

- In `MalibuAgent.prompt()`, emit the `UserMessageChunk` and initial status update before calling `get_or_create_agent()`.

Why:

- Right now `get_or_create_agent()` happens before the user echo.
- That makes Malibu look frozen even before the actual agent work begins.

Implementation direction:

- Reorder `malibu/server/agent.py` so the prompt text is echoed immediately.
- Show a status such as "Preparing agent" while the session agent is being created.
- Only after the user can see feedback should the code enter the expensive build path.

Success target:

- Immediate visible response on the first prompt, even if backend bootstrap still takes time.

### 4. Replace per-update full JSON rewrites with buffered or async persistence

Recommendation:

- Stop calling full-record `_save_record()` on every session update and TUI event.

Why:

- `500` persisted updates cost about `1.68s`.
- Malibu's stream path produces many events.

Implementation direction:

- Append updates to an in-memory queue.
- Flush on a short timer such as every `250ms` to `500ms`.
- Force a flush on:
  - run completion
  - interrupt
  - cancel
  - app shutdown
- Use compact JSON in the hot path instead of pretty-printed `indent=2`.

Success target:

- Reduce `500` persisted updates from about `1.68s` to under `0.25s`.

### 5. Skip plugin scan, skill registry load, and hook bootstrap unless actually needed

Recommendation:

- Make optional subsystems truly optional at startup.

Why:

- The current SessionManager path loads skills, scans plugins, and prepares hook machinery even when the user may never use those features in the session.

Implementation direction:

- Do not build the skill registry unless skills are enabled and the session actually requests skill use.
- Do not scan plugins unless plugins are enabled and a plugin-backed feature is requested.
- Do not create hook managers unless hook config files exist and hook execution is enabled.
- Do not create cost callbacks until the first actual model request starts.

Success target:

- Remove non-essential session bootstrap work from the default first-turn path.

### 6. Add a fast direct-local mode and stop using ACP as the default local path

Recommendation:

- Keep ACP for `malibu server` and compatibility scenarios, but make the default local Textual path talk to the Deep Agents graph directly.

Why:

- The investigation suggests ACP is not the main bottleneck, but it is still an extra local architectural layer.
- DeepAgentCLI's default local path is simpler because it streams directly into the UI.

Implementation direction:

- Keep current ACP server mode intact.
- Add a direct local adapter path for `malibu` TUI.
- Preserve ACP only for:
  - `malibu server`
  - remote or external clients
  - compatibility and protocol testing

Success target:

- Use a direct local path as the default fast mode without breaking ACP-based workflows.

## P1: Important, Moderate Risk

### 7. Adopt strict lazy-import discipline in Malibu

Recommendation:

- Follow the DeepAgentCLI pattern where heavy agent modules are imported only inside the code path that actually needs them.

Why:

- Malibu's current startup path eagerly imports command infrastructure and large agent/tool modules.

Implementation direction:

- Move heavy imports out of module scope where possible.
- Delay browser/media/web/tool-server imports until their tool pack is activated.
- Delay command registry construction until the chat screen is live.

Success target:

- Lower cold import time for the TUI path and reduce memory churn on startup.

### 8. Formalize tool packs as a product feature

Recommendation:

- Make tool packs user-visible and configurable.

Suggested pack structure:

- `core`
- `shell`
- `git`
- `browser`
- `web`
- `media`
- `mcp`

Why:

- Performance becomes controllable.
- The default session can stay fast while power users still opt into richer capability.

Implementation direction:

- Add config and per-session toggles for packs.
- Surface active packs in the TUI status or config command.

### 9. Make hook execution less synchronous where safe

Recommendation:

- Keep blocking hook behavior only for hooks that must gate the actual tool call.
- Move non-blocking or observational hooks off the critical path.

Why:

- Hooks are valuable, but they should not slow down every session or every tool call unnecessarily.

Implementation direction:

- Split hooks into:
  - blocking validation hooks
  - non-blocking telemetry hooks
- Cache parsed hook config.
- Avoid creating hook infrastructure unless hooks are configured.

### 10. Remove or justify fixed sleeps

Recommendation:

- Audit all `sleep()` sites and replace fixed waits with condition-based waits where possible.

Why:

- Malibu currently has far more explicit sleep sites than DeepAgentCLI.
- Many browser sleeps may be necessary today, but fixed sleeps are the slowest possible correctness strategy.

Implementation direction:

- Keep correctness-critical waits only where there is no reliable event-based alternative.
- Replace browser sleeps with page-state or element-state waits when possible.
- Replace TUI idle polling with event-driven shutdown or worker signaling where possible.

Note:

- The `1.5s` chat watchdog is not the primary latency problem.
- The bigger problem is the first-turn bootstrap that happens before the first user-visible update.

## P2: Strategic Follow-Up

### 11. Build a repeatable benchmark harness

Recommendation:

- Add a small internal benchmark suite so performance work is measured, not guessed.

Suggested benchmarks:

- import time for:
  - `malibu.tui.app`
  - `malibu.server.agent`
  - `malibu.agent.tools.registry`
- tool bundle build time
- model construction time
- first prompt time to first visible update
- second prompt time to first visible update
- `100`, `500`, and `1000` session update persistence costs

Suggested success gates:

- first prompt time to first visible update under `2s`
- second prompt time to first visible update under `0.05s`
- default tool bootstrap under `1.5s`
- `500` persisted updates under `0.25s`

### 12. Re-evaluate ACP's role after P0 and P1 land

Recommendation:

- Do not remove ACP immediately.
- Re-evaluate ACP after the main first-turn bottlenecks are fixed.

Decision rule:

- If direct local mode materially outperforms local ACP mode and preserves required features, make direct local mode the default.
- Keep ACP as the compatibility and external-client protocol layer.

## Proposed Implementation Order

1. Reorder first visible updates ahead of `get_or_create_agent()`.
2. Introduce `core` tool pack and stop building optional packs by default.
3. Cache or defer model construction.
4. Buffer session persistence.
5. Make skills/plugins/hooks lazy.
6. Add direct local mode.
7. Clean up imports and sleep sites.
8. Add benchmark harness.

## Expected Outcome

If Malibu follows this sequence, the most likely outcome is:

- dramatic improvement in first-turn responsiveness
- visibly faster startup in the local TUI
- lower steady-state overhead during long streaming runs
- preserved product breadth without paying full breadth cost on every session

## Non-Goals

- No rewrite in Rust.
- No immediate removal of ACP server mode.
- No abandonment of Deep Agents.

The investigation strongly suggests Malibu can get much faster within the current Python architecture by reducing eager bootstrap work and simplifying the default local path.
