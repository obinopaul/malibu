# Malibu Tool Catalog Draft

<tool_catalog>

## Purpose

This document is the working source of truth for tool descriptions used by the Malibu CLI prompt rewrite.
It separates implemented tools from planned or legacy mentions, and it standardizes:

1. What each tool does.
2. When to use it.
3. When not to use it.
4. Which tool to use next.
5. What alternatives exist.

## Status labels

1. Implemented: available in current runtime.
2. Planned: intended for future capability.
3. Legacy mention: appears in old prompt language but not currently implemented.

## A) Implemented Built-in Tools

### A.1 File and edit tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| read_file | Implemented | Read file content by line range | You need regex search across many files | grep, find_symbol, find_referencing_symbols | bash with rg/cat/type |
| write_file | Implemented | Write full file content | You only need small targeted edit | read_file, apply_patch | apply_patch |
| apply_patch | Implemented | Precise patch edits, add/update/delete | You need full file generation from scratch | read_file, grep | write_file |
| search_replace | Implemented | Exact string replacement in file | You need semantic refactor across symbols | read_file, find_symbol | apply_patch, rename_symbol |
| ast_grep | Implemented | Structural search and replacement | You need one literal change | read_file, grep | search_replace |

### A.2 Symbol-aware code tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| find_symbol | Implemented | Locate symbol definition | You need all references | find_referencing_symbols | grep |
| find_referencing_symbols | Implemented | Find symbol usages | You need rename in one step | rename_symbol | grep |
| rename_symbol | Implemented | Language-aware symbol rename | Language server unsupported | grep, read_file | search_replace |
| replace_symbol_body | Implemented | Replace function/class body safely | You need surrounding edits too | read_file, apply_patch | apply_patch |
| insert_before_symbol | Implemented | Insert text before a symbol | Insertion point is not symbol-based | read_file | apply_patch |
| insert_after_symbol | Implemented | Insert text after a symbol | Insertion point is not symbol-based | read_file | apply_patch |

### A.3 Shell and terminal tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| bash | Implemented | Quick stateless one-off command | Command is long-running or interactive | grep, git, shell_init | shell_run for stateful work |
| shell_init | Implemented | Create persistent named shell session | You only need one quick command | shell_run, shell_list | bash |
| shell_list | Implemented | List shell sessions and state | You need command output details | shell_view | bash |
| shell_run | Implemented | Execute command in persistent shell | You need best-effort stateless command only | shell_view, shell_write, shell_stop | bash |
| shell_view | Implemented | Poll output from persistent shell | No running command/session | shell_run, shell_stop | bash output |
| shell_write | Implemented | Send stdin to interactive command | Process is non-interactive | shell_view, shell_stop | rerun with non-interactive flags |
| shell_stop | Implemented | Interrupt or terminate session/process | Session idle | shell_list | recreate with shell_init |

### A.4 Search and discovery tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| grep | Implemented | Fast regex content search | You need semantic symbol graph | read_file, find_symbol | shell rg |


### A.5 Git and repository tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| git | Implemented | Structured repo status, diff, log, branch, branches, commit | You need branch-isolated parallel workspace | git_worktree, grep | shell git commands |
| git_worktree | Implemented | Parallel branch workspaces and isolation | You only need simple branch inspect | git, snapshot | shell git worktree |
| snapshot | Implemented | Capture and compare workspace snapshots | You need repository history semantics | git, grep | manual state notes |

### A.6 Web and documentation tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| websearch | Implemented | Search the web for relevant sources | You already have canonical URL | webfetch | bash with curl/wget |
| webfetch | Implemented | Extract selected URL content | You need interactive browsing | websearch, read_file | bash with curl/wget |


### A.7 Workflow and orchestration tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| task | Implemented | Launch focused autonomous sub-task | Task is tiny and local | read_file, apply_patch | todo |
| todo | Implemented | Maintain task plan checkpoints | Task is single-step trivial | task | notes in prompt text |
| exit_plan_mode | Implemented | Exit planner-focused execution mode | You are not currently in plan mode | todo, task | continue current mode |

### A.8 Human interaction and session tools

| Tool | Status | Primary use | Avoid when | Follow-up tools | Alternatives |
| --- | --- | --- | --- | --- | --- |
| ask_user_question | Implemented | Ask one high-signal clarification to unblock safely | You can infer intent from context | read_file, apply_patch | concise assumption + proceed |

## B) Planned and Future Tool Categories

These are not guaranteed to be present in every runtime. Keep them explicit to prevent hallucinated capabilities.

### B.1 Planned categories and examples

| Category | Status | Examples | Intended purpose |
| --- | --- | --- | --- |
| Project bootstrap | Planned | project scaffolding orchestrators | One-command scaffolding for frameworks |
| Extension-aware symbol intelligence | Planned | richer language-server integrations | Stronger semantic refactors and code navigation |
| Cloud management adapters | Planned | provider-specific resource routers | Subscription/resource/query/deploy workflows |
| Notebook and data analysis adapters | Planned | notebook and data panel integrations | Interactive data exploration in notebook/viewer UIs |
| Marketplace and IDE integrations | Planned | extension discovery/installation flows | Discover and install IDE capabilities in-session |

## C) Legacy Mentions That Need Guardrails

These appear in older prompt text and must be treated carefully.

| Legacy mention | Current status | Correct handling |
| --- | --- | --- |
| Linux-only /workspace assumptions | Legacy | Replace with host-aware paths and examples |
| tmux-specific shell model | Legacy in some docs | Keep generic persistent shell semantics |
| Unsupported git action names in prompt docs | Legacy and conflicting | Restrict to implemented actions only |

## D) Canonical Decision Rubrics

### D.1 Bash vs shell tools

Use bash when:

1. One short command.
2. No persistent state needed.
3. No interactive stdin expected.

Use shell tools when:

1. You need persistent cwd/environment.
2. Command runs long and must be polled.
3. Process needs interactive input.
4. You need to stop/interrupt gracefully.

### D.2 Grep vs shell text search

Use grep when:

1. You need fast regex search across files.
2. You want standardized ignores and controlled output.

Use shell rg via bash only when:

1. You need a very custom one-off flag combo not exposed by grep.
2. You immediately verify the output quality and scope.

### D.3 Git vs git_worktree

Use git when:

1. Inspecting status/diff/log/branches.
2. Performing guarded commit in current worktree.

Use git_worktree when:

1. You need isolated parallel branch work.
2. You need safe create/remove/reset lifecycle around alternate worktrees.

## E) Validation Checklist for Prompt Authors

1. Every listed tool must be marked Implemented, Planned, or Legacy.
2. Every implemented tool description must match current code behavior.
3. Every conflict-prone pair must include a decision rubric.
4. Every shell/path example must include cross-platform logic.
5. Every action list for structured tools must map to real enum/actions.

</tool_catalog>
