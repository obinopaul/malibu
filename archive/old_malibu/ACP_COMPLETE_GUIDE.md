# ACP (Agent-Client Protocol) — Complete Reference Guide

> **Audience:** AI engineers who build agents (LangChain, LangGraph, CrewAI, custom, etc.) and want to understand every aspect of ACP — what it is, what it contains, and how it works internally.
>
> **Companion document:** See `ACP_PRACTICAL_GUIDE.md` for hands-on code examples, walkthroughs, and integration patterns.

---

## Table of Contents

1. [What Is ACP and Why Does It Exist?](#1-what-is-acp-and-why-does-it-exist)
2. [ACP vs MCP vs Other Protocols](#2-acp-vs-mcp-vs-other-protocols)
3. [Architecture Overview](#3-architecture-overview)
4. [Protocol Messages — Complete Reference](#4-protocol-messages--complete-reference)
5. [Schema & Data Types — Every Type Explained](#5-schema--data-types--every-type-explained)
6. [Python SDK Internals — Module-by-Module](#6-python-sdk-internals--module-by-module)
7. [Helpers Reference — Every Builder Function](#7-helpers-reference--every-builder-function)
8. [Contrib Utilities — Production Patterns](#8-contrib-utilities--production-patterns)
9. [Capabilities & Initialization](#9-capabilities--initialization)
10. [Unstable & Experimental Features](#10-unstable--experimental-features)
11. [Code Generation Pipeline](#11-code-generation-pipeline)
12. [Glossary](#12-glossary)

---

## 1. What Is ACP and Why Does It Exist?

### The Problem

You've built an AI agent — maybe with LangChain, LangGraph, CrewAI, or a custom runtime. Now you need to connect it to a user-facing client: a code editor (Zed, VS Code), a CLI, a web UI, a Jupyter notebook, or a mobile app. Currently, there's no standard way to do this. Every team hand-wires their own:

- **Transport layer**: FastAPI + SSE, WebSockets, Socket.io, gRPC, raw HTTP
- **Message format**: Custom JSON schemas, ad-hoc streaming protocols
- **Session management**: Stateless REST, cookie sessions, custom state stores
- **Agent capabilities**: Hard-coded feature flags, no negotiation
- **Permission models**: No standardization, every agent reinvents approvals

This means **every agent speaks a different language**, and every client has to write custom integration code for every agent it wants to support. This is the same problem HTTP solved for the web, and the same problem MCP solved for tool calling.

### The Solution: ACP

**ACP (Agent-Client Protocol)** is a **bidirectional, session-based, JSON-RPC 2.0 protocol** that standardizes communication between AI agents and their clients. It defines:

| What ACP Defines | Description |
|---|---|
| **Message format** | Structured JSON-RPC 2.0 envelope with typed Pydantic models |
| **Session lifecycle** | Create, load, fork, resume, and list sessions |
| **Streaming** | Real-time agent messages, thoughts, tool calls, and plans |
| **Content types** | Text, images, audio, resource links, embedded resources |
| **Tool call tracking** | Start → progress → complete lifecycle with content (text, diffs, terminals) |
| **Permissions** | Structured approval flows: request → options → outcome |
| **File I/O** | Agent reads/writes files on the client's machine |
| **Terminal access** | Agent creates, controls, and monitors terminal processes |
| **Capability negotiation** | Agent and client discover each other's features at init |
| **Authentication** | Pluggable auth methods negotiated at connection time |
| **Extension points** | Custom RPC methods without breaking the core protocol |
| **Plan tracking** | Agent reports execution plans with priorities and status updates |

### How ACP Works at a High Level

```
┌────────────────────┐                    ┌────────────────────┐
│      CLIENT        │   stdio (JSON-RPC) │       AGENT        │
│  (Zed, VS Code,    │ ◄────────────────► │  (LangGraph, any   │
│   CLI, Jupyter,    │   bidirectional     │   framework)       │
│   custom UI)       │                    │                    │
└────────────────────┘                    └────────────────────┘

1. Client spawns agent process (or connects to running agent)
2. Client sends `initialize` → Agent responds with capabilities
3. Client sends `session/new` → Agent creates a conversation session
4. Client sends `session/prompt` → Agent processes, streams updates back
5. During processing, agent can:
   - Stream text/thoughts (session/update notifications)
   - Request permission for operations
   - Read/write files on the client
   - Create/manage terminal processes
   - Report execution plans and tool calls
6. Agent returns final PromptResponse with stop_reason
7. Repeat 4-6 for each user interaction
```

### Key Design Principles

1. **Bidirectional**: Both agent and client can initiate requests to each other during a session
2. **Async-native**: Everything uses `asyncio` — streaming, concurrent file reads, parallel tool calls
3. **Session-based**: Conversations happen within sessions that can be persisted, forked, and resumed
4. **Capability-driven**: Features are negotiated, not assumed — agents and clients discover what each other supports
5. **Transport-agnostic**: While stdio is the primary transport, the protocol works over any bidirectional stream
6. **Schema-first**: All types are defined in a canonical JSON Schema, and Python models are auto-generated from it
7. **Streaming-native**: Agent responses are streamed as notifications, not batched — reducing latency

---

## 2. ACP vs MCP vs Other Protocols

Understanding where ACP fits in the AI protocol landscape:

### MCP (Model Context Protocol)

| Aspect | MCP | ACP |
|--------|-----|-----|
| **Purpose** | Connect LLMs to tools and data sources | Connect AI agents to end-user clients |
| **Direction** | Mostly unidirectional (LLM calls tools) | Fully bidirectional (agent ↔ client) |
| **Primary abstraction** | Tools, resources, prompts | Sessions, streaming, permissions, plans |
| **Session model** | Stateless tool invocations | Stateful sessions with lifecycle (create/fork/resume) |
| **Streaming** | Tool results returned at completion | Real-time streaming of text, thoughts, tool calls, plans |
| **Permissions** | Not built-in | First-class: structured approval workflows |
| **File I/O** | Via resource abstraction | Direct file read/write requests to client filesystem |
| **Terminal access** | Not built-in | First-class: create, control, monitor terminal processes |
| **Content types** | Text, images, resources | Text, images, audio, resource links, embedded resources |
| **Who uses it** | LLM ↔ Tool server | Agent ↔ Client (editor, CLI, UI) |

**Key insight**: MCP and ACP are **complementary**, not competing. ACP agents can use MCP servers for tools, while ACP handles the agent-to-client communication layer. In fact, ACP's initialization supports passing MCP server configurations to agents.

### Agent-to-UI Protocols

Some teams build "Agent UI protocols" for rendering agent output. ACP's `session/update` notification system with 11 update types (messages, thoughts, tool calls, plans, mode changes, config updates) effectively provides this — it defines what UI updates the client should display, without prescribing how to render them.

### Raw FastAPI / WebSocket / Socket.io

These are transport layers, not protocols. ACP sits above the transport: it defines the messages, their structure, and the interaction patterns. You could implement ACP over WebSockets if you wanted, but the reference SDK uses stdio because:

- It's universally available (every OS, every language)
- It's process-isolated (agent failure doesn't crash the client)
- It handles backpressure naturally
- It's dead simple to set up (spawn process → pipe stdin/stdout)

---

## 3. Architecture Overview

### The Two Sides: Agent and Client

ACP defines two protocol participants:

```
┌─────────────────────────────────────────────────────────┐
│                   AGENT SIDE                            │
│                                                         │
│  Your agent logic (LangGraph, CrewAI, custom...)       │
│         │                                               │
│         ▼                                               │
│  ┌─────────────────┐     ┌──────────────────────┐      │
│  │  Agent Protocol  │     │ AgentSideConnection   │      │
│  │  (22 methods)    │◄───►│ (routes incoming RPC) │      │
│  └─────────────────┘     └──────────┬───────────┘      │
│                                      │                  │
│                              ┌───────▼────────┐        │
│                              │  Connection     │        │
│                              │  (JSON-RPC 2.0) │        │
│                              └───────┬────────┘        │
└──────────────────────────────────────┼──────────────────┘
                                       │ stdio / stream
┌──────────────────────────────────────┼──────────────────┐
│                              ┌───────▼────────┐        │
│                              │  Connection     │        │
│                              │  (JSON-RPC 2.0) │        │
│                              └───────┬────────┐        │
│                                      │                  │
│  ┌─────────────────┐     ┌──────────▼───────────┐      │
│  │ Client Protocol  │     │ ClientSideConnection  │      │
│  │  (9 methods)     │◄───►│ (routes incoming RPC) │      │
│  └─────────────────┘     └──────────────────────┘      │
│         │                                               │
│         ▼                                               │
│  Your client logic (editor, CLI, UI...)                │
│                                                         │
│                   CLIENT SIDE                           │
└─────────────────────────────────────────────────────────┘
```

### Agent Protocol — 22 Methods

The Agent Protocol defines what agents must implement. Methods the **client calls on the agent**:

| Category | Method | Direction | Kind | Description |
|----------|--------|-----------|------|-------------|
| **Lifecycle** | `initialize` | Client → Agent | Request | Negotiate protocol version & capabilities |
| **Auth** | `authenticate` | Client → Agent | Request | Authenticate with a specific method |
| **Sessions** | `session/new` | Client → Agent | Request | Create a new conversation session |
| | `session/load` | Client → Agent | Request | Load/resume an existing session |
| | `session/list` | Client → Agent | Request | List existing sessions *(unstable)* |
| | `session/fork` | Client → Agent | Request | Fork a session *(unstable)* |
| | `session/resume` | Client → Agent | Request | Resume a session without history replay *(unstable)* |
| **Interaction** | `session/prompt` | Client → Agent | Request | Send user prompt for processing |
| | `session/cancel` | Client → Agent | Notification | Cancel ongoing processing |
| **Config** | `session/set_mode` | Client → Agent | Request | Change session mode (e.g., "code", "architect") |
| | `session/set_model` | Client → Agent | Request | Change AI model *(unstable)* |
| | `session/set_config_option` | Client → Agent | Request | Set a config option value |
| **Extension** | `ext_method` | Client → Agent | Request | Custom RPC method |
| | `ext_notification` | Client → Agent | Notification | Custom one-way notification |

Plus the lifecycle hook: `on_connect(conn: Client)` — called when a client connection is established, giving the agent a reference to call client methods.

### Client Protocol — 9 Methods

The Client Protocol defines what clients must implement. Methods the **agent calls on the client**:

| Category | Method | Direction | Kind | Description |
|----------|--------|-----------|------|-------------|
| **Streaming** | `session/update` | Agent → Client | Notification | Stream session updates (11 types) |
| **Permissions** | `session/request_permission` | Agent → Client | Request | Ask user for permission |
| **File I/O** | `fs/read_text_file` | Agent → Client | Request | Read a file from client filesystem |
| | `fs/write_text_file` | Agent → Client | Request | Write a file to client filesystem |
| **Terminal** | `terminal/create` | Agent → Client | Request | Create and run a terminal command |
| | `terminal/output` | Agent → Client | Request | Get terminal output |
| | `terminal/release` | Agent → Client | Request | Release terminal resources |
| | `terminal/wait_for_exit` | Agent → Client | Request | Wait for terminal to exit |
| | `terminal/kill` | Agent → Client | Request | Kill a running terminal command |
| **Extension** | `ext_method` / `ext_notification` | Agent → Client | Request/Notification | Custom methods |

### Internal Pipeline

Inside the SDK, each connection follows this pipeline:

```
Incoming bytes (stdin / stream)
    │
    ▼
StreamReader (newline-delimited JSON)
    │
    ▼
Connection._receive_loop() — parse JSON, validate
    │
    ├── Request (has `id`) ──► MessageQueue ──► Dispatcher ──► Handler
    │                                                            │
    │                                              Response ◄────┘
    │                                                 │
    │                                          MessageSender ──► StreamWriter
    │
    └── Notification (no `id`) ──► MessageQueue ──► Dispatcher ──► Handler
                                                        (no response)
```

Key components:
- **`MessageRouter`**: Maps method names to handler functions via declared routes
- **`TaskSupervisor`**: Manages background tasks, handles errors, graceful shutdown
- **`InMemoryMessageQueue`**: FIFO queue for ordered message processing
- **`DefaultMessageDispatcher`**: Consumes queue, spawns handler tasks
- **`MessageSender`**: Serializes responses to JSON, handles write backpressure
- **`InMemoryMessageStateStore`**: Tracks pending request/response correlation

---

## 4. Protocol Messages — Complete Reference

All ACP messages use the **JSON-RPC 2.0** envelope:

```json
// Request (expects response)
{"jsonrpc": "2.0", "id": 1, "method": "session/prompt", "params": {...}}

// Response (to a request)
{"jsonrpc": "2.0", "id": 1, "result": {...}}

// Error response
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}

// Notification (no response expected, no id)
{"jsonrpc": "2.0", "method": "session/update", "params": {...}}
```

### 4.1 Client → Agent Requests

#### `initialize`

Establishes the connection. Must be the first message.

```json
// Request
{
  "protocolVersion": 1,
  "clientCapabilities": {
    "fs": {"readTextFile": true, "writeTextFile": true},
    "terminal": true
  },
  "clientInfo": {"name": "my-editor", "version": "1.0.0", "title": "My Editor"}
}

// Response
{
  "protocolVersion": 1,
  "agentCapabilities": {
    "loadSession": true,
    "mcpCapabilities": {"http": true, "sse": true},
    "promptCapabilities": {"image": true, "audio": false, "embeddedContext": true},
    "sessionCapabilities": {"fork": true, "list": true, "resume": true}
  },
  "agentInfo": {"name": "my-agent", "version": "0.1.0", "title": "My Agent"},
  "authMethods": [{"id": "github", "name": "GitHub OAuth"}]
}
```

#### `authenticate`

Authenticates using a method from `authMethods` in the init response.

```json
// Request
{"methodId": "github"}

// Response
{} // or null (authentication handled externally)
```

#### `session/new`

Creates a new conversation session.

```json
// Request
{
  "cwd": "/home/user/project",
  "mcpServers": [
    {"type": "stdio", "name": "my-tools", "command": "npx", "args": ["-y", "my-mcp-server"], "env": []},
    {"type": "http", "name": "remote-tools", "url": "https://tools.example.com/mcp", "headers": []},
    {"type": "sse", "name": "sse-tools", "url": "https://sse.example.com/events", "headers": []}
  ]
}

// Response
{
  "sessionId": "abc123",
  "modes": {
    "currentModeId": "code",
    "availableModes": [
      {"id": "code", "name": "Code", "description": "Write and edit code"},
      {"id": "architect", "name": "Architect", "description": "Plan and design"}
    ]
  },
  "models": {
    "currentModelId": "gpt-4",
    "availableModels": [
      {"modelId": "gpt-4", "name": "GPT-4"},
      {"modelId": "claude-3", "name": "Claude 3 Opus"}
    ]
  },
  "configOptions": [
    {
      "type": "select",
      "configId": "temperature",
      "name": "Temperature",
      "currentValue": "0.7",
      "options": [{"value": "0.0", "name": "Precise"}, {"value": "1.0", "name": "Creative"}]
    }
  ]
}
```

#### `session/load`

Resumes an existing session. Requires `loadSession` agent capability.

```json
// Request
{"sessionId": "abc123", "cwd": "/home/user/project", "mcpServers": []}

// Response
{
  "modes": {...},
  "models": {...},
  "configOptions": [...]
}
```

#### `session/prompt`

The main interaction method — sends a user prompt for the agent to process.

```json
// Request
{
  "sessionId": "abc123",
  "prompt": [
    {"type": "text", "text": "Fix the bug in main.py"},
    {"type": "image", "mimeType": "image/png", "data": "base64-encoded-data"},
    {"type": "resource_link", "uri": "file:///home/user/main.py", "name": "main.py"},
    {"type": "resource", "resource": {"uri": "file:///context.txt", "text": "Additional context..."}}
  ]
}

// Response
{
  "stopReason": "end_turn"  // or: "max_tokens", "max_turn_requests", "refusal", "cancelled"
}
```

Between request and response, the agent streams `session/update` notifications.

#### `session/set_mode`

Changes the agent's operating mode mid-session.

```json
// Request
{"sessionId": "abc123", "modeId": "architect"}

// Response
{
  "modes": {"currentModeId": "architect", "availableModes": [...]},
  "configOptions": [...]
}
```

#### `session/set_config_option`

Sets a configuration option value.

```json
// Request
{"sessionId": "abc123", "configId": "temperature", "value": "0.0"}

// Response
{"configOptions": [...]}
```

#### `session/cancel` (Notification)

Cancels the current operation. Agent must respond to pending prompt with `stop_reason: "cancelled"`.

```json
{"sessionId": "abc123"}
```

### 4.2 Agent → Client Requests

#### `session/request_permission`

Asks the user for approval before performing sensitive operations.

```json
// Request
{
  "sessionId": "abc123",
  "toolCall": {"toolCallId": "call_42", "title": "Delete file", "kind": "delete"},
  "options": [
    {"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
    {"optionId": "allow-always", "name": "Always Allow", "kind": "allow_always"},
    {"optionId": "reject", "name": "Reject", "kind": "reject_once"}
  ]
}

// Response — user selected an option
{"outcome": "selected", "optionId": "allow-once"}

// Response — user cancelled the turn
{"outcome": "cancelled"}
```

#### `fs/read_text_file`

Reads a file from the client's filesystem.

```json
// Request
{"sessionId": "abc123", "path": "/home/user/main.py", "line": 10, "limit": 50}

// Response
{"content": "def main():\n    print('hello')\n", "path": "/home/user/main.py"}
```

#### `fs/write_text_file`

Writes content to a file on the client's filesystem.

```json
// Request
{"sessionId": "abc123", "path": "/home/user/main.py", "content": "def main():\n    print('fixed')\n"}

// Response
{} // or null
```

#### `terminal/create`

Creates a terminal and executes a command.

```json
// Request
{
  "sessionId": "abc123",
  "command": "python",
  "args": ["-m", "pytest"],
  "cwd": "/home/user/project",
  "env": [{"name": "PYTHONPATH", "value": "/custom/path"}],
  "outputByteLimit": 65536
}

// Response
{"terminalId": "term_001"}
```

#### `terminal/output`

Gets current terminal output and exit status.

```json
// Request
{"sessionId": "abc123", "terminalId": "term_001"}

// Response
{
  "output": "===== 5 passed in 1.2s =====",
  "truncated": false,
  "exitStatus": {"exitCode": 0}
}
```

#### `terminal/wait_for_exit`

Blocks until the terminal command finishes.

```json
// Request
{"sessionId": "abc123", "terminalId": "term_001"}

// Response
{"exitStatus": {"exitCode": 0}}
```

#### `terminal/release`

Frees terminal resources.

```json
// Request
{"sessionId": "abc123", "terminalId": "term_001"}
// Response: {} or null
```

#### `terminal/kill`

Kills a running terminal command without releasing.

```json
// Request
{"sessionId": "abc123", "terminalId": "term_001"}
// Response: {} or null
```

### 4.3 Session Update Notifications (Agent → Client)

The `session/update` notification carries one of **11 update types**, identified by the `sessionUpdate` discriminator field. These are how agents stream real-time information to clients.

```json
// Envelope for all session updates
{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "abc123", "update": <update>}}
```

#### `user_message_chunk` — Echo user input

```json
{"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "User's message"}}
```

#### `agent_message_chunk` — Agent response text (streamed)

```json
{"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Here's the fix..."}}
```

#### `agent_thought_chunk` — Agent thinking/reasoning

```json
{"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "I should read the file first..."}}
```

#### `tool_call` — New tool call started

```json
{
  "sessionUpdate": "tool_call",
  "toolCallId": "call_001",
  "title": "Read main.py",
  "kind": "read",
  "status": "pending",
  "locations": [{"path": "/home/user/main.py"}],
  "rawInput": {"path": "/home/user/main.py"}
}
```

#### `tool_call_update` — Tool call progress/completion

```json
{
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_001",
  "status": "completed",
  "content": [
    {"type": "content", "content": {"type": "text", "text": "File contents..."}},
    {"type": "diff", "path": "main.py", "oldText": "old code", "newText": "new code"},
    {"type": "terminal", "terminalId": "term_001"}
  ],
  "rawOutput": {"result": "success"}
}
```

#### `plan` — Agent execution plan

```json
{
  "sessionUpdate": "plan",
  "entries": [
    {"content": "Read the file", "priority": "high", "status": "completed"},
    {"content": "Apply the fix", "priority": "high", "status": "in_progress"},
    {"content": "Run tests", "priority": "medium", "status": "pending"}
  ]
}
```

#### `available_commands_update` — Commands the user can invoke

```json
{
  "sessionUpdate": "available_commands_update",
  "availableCommands": [{"id": "cancel", "name": "Cancel"}, {"id": "skip", "name": "Skip"}]
}
```

#### `current_mode_update` — Session mode changed

```json
{"sessionUpdate": "current_mode_update", "currentModeId": "architect"}
```

#### `config_option_update` — Config options changed

```json
{
  "sessionUpdate": "config_option_update",
  "configOptions": [
    {
      "type": "select",
      "configId": "temperature",
      "name": "Temperature",
      "currentValue": "0.0",
      "options": [...]
    }
  ]
}
```

#### `session_info_update` — Session metadata changed

```json
{
  "sessionUpdate": "session_info_update",
  "sessionInfo": {"sessionId": "abc123", "title": "Bug fix conversation", "updatedAt": "2025-01-01T00:00:00Z"}
}
```

#### `usage_update` — Token usage and cost *(unstable)*

```json
{
  "sessionUpdate": "usage_update",
  "usage": {
    "totalTokens": 1500,
    "inputTokens": 500,
    "outputTokens": 1000,
    "cachedReadTokens": 200,
    "thoughtTokens": 100
  },
  "cost": {"amount": 0.015, "currency": "USD"}
}
```

### 4.4 Error Codes

| Code | Name | Meaning |
|------|------|---------|
| `-32700` | Parse Error | Invalid JSON |
| `-32600` | Invalid Request | Malformed JSON-RPC envelope |
| `-32601` | Method Not Found | Unknown method name |
| `-32602` | Invalid Params | Wrong parameter types |
| `-32603` | Internal Error | Unhandled exception in handler |
| `-32800` | Request Cancelled | Request was cancelled *(unstable)* |
| `-32000` | Authentication Required | Auth needed before proceeding |
| `-32002` | Resource Not Found | Requested resource doesn't exist |

### 4.5 Extension Methods

Both agent and client support custom methods for protocol extensions:

```python
# Agent-side: handle custom client requests
async def ext_method(self, method: str, params: dict) -> dict:
    if method == "custom/get_diagnostics":
        return {"diagnostics": [...]}
    raise RequestError.method_not_found(method)

# Agent-side: handle custom client notifications
async def ext_notification(self, method: str, params: dict) -> None:
    if method == "custom/theme_changed":
        self._theme = params["theme"]
```

Extension methods allow ACP to evolve without breaking the core protocol. Unrecognized methods can be handled or rejected without affecting standard communication.

---

## 5. Schema & Data Types — Every Type Explained

All types below are auto-generated Pydantic `BaseModel` classes from the canonical ACP JSON Schema (version `refs/tags/v0.10.8`). They live in `src/acp/schema.py`.

### 5.1 Content Blocks

Content blocks are the building blocks of all messages in ACP. They use the `type` field as a discriminator.

| Type | Class | Fields | Used In |
|------|-------|--------|---------|
| `"text"` | `TextContentBlock` | `text: str`, `annotations?` | Prompts, messages, thoughts |
| `"image"` | `ImageContentBlock` | `data: str` (base64), `mime_type: str`, `uri?`, `annotations?` | Prompts, messages |
| `"audio"` | `AudioContentBlock` | `data: str` (base64), `mime_type: str`, `annotations?` | Prompts, messages |
| `"resource_link"` | `ResourceContentBlock` | `uri: str`, `name: str`, `title?`, `description?`, `mime_type?`, `size?`, `annotations?` | Prompts (file references) |
| `"resource"` | `EmbeddedResourceContentBlock` | `resource: TextResourceContents \| BlobResourceContents`, `annotations?` | Prompts (inline content) |

**Resource Contents:**

| Class | Fields | Purpose |
|-------|--------|---------|
| `TextResourceContents` | `uri: str`, `text: str`, `mime_type?` | Inline text files |
| `BlobResourceContents` | `uri: str`, `blob: str` (base64), `mime_type?` | Inline binary files |

**Annotations** (optional metadata on any content block):

```python
class Annotations:
    audience: list[Role] | None  # Who should see this: ["user"], ["assistant"], ["user", "assistant"]
    priority: float | None       # 0.0 (low) to 1.0 (high)
    last_modified: str | None    # ISO 8601 timestamp
```

### 5.2 Tool Calls

Tool calls represent actions the agent takes. They follow a lifecycle: **start → progress → complete/fail**.

**ToolCallStart** (initial notification):

```python
class ToolCallStart:
    session_update: Literal["tool_call"]
    tool_call_id: str           # Unique within session
    title: str                  # Human-readable label
    kind: ToolKind | None       # Category of action
    status: ToolCallStatus | None
    content: list[ToolCallContent] | None
    locations: list[ToolCallLocation] | None
    raw_input: Any              # Raw tool arguments
    raw_output: Any             # Raw tool result
```

**ToolCallProgress** (subsequent updates):

```python
class ToolCallProgress:
    session_update: Literal["tool_call_update"]
    tool_call_id: str           # Matches the ToolCallStart
    title: str | None           # Updated title
    kind: ToolKind | None
    status: ToolCallStatus | None
    content: list[ToolCallContent] | None
    locations: list[ToolCallLocation] | None
    raw_input: Any
    raw_output: Any
```

**ToolKind** — What kind of action:

| Value | Meaning |
|-------|---------|
| `"read"` | Reading a file or resource |
| `"edit"` | Editing/modifying content |
| `"delete"` | Deleting a resource |
| `"move"` | Moving/renaming |
| `"search"` | Searching for content |
| `"execute"` | Running a command/process |
| `"think"` | Internal reasoning |
| `"fetch"` | HTTP/network fetch |
| `"switch_mode"` | Changing agent mode |
| `"other"` | Uncategorized |

**ToolCallStatus** — Lifecycle state:

| Value | Meaning |
|-------|---------|
| `"pending"` | Tool call queued, not started |
| `"in_progress"` | Currently executing |
| `"completed"` | Finished successfully |
| `"failed"` | Execution failed |

**ToolCallContent** — Three variants of content attached to tool calls:

```python
# 1. Generic content (text, image, etc.)
class ContentToolCallContent:
    type: Literal["content"]
    content: ContentBlock  # Any content block

# 2. File diff (code changes)
class FileEditToolCallContent:
    type: Literal["diff"]
    path: str               # File path
    new_text: str           # New content
    old_text: str | None    # Original content (None = new file)

# 3. Terminal reference
class TerminalToolCallContent:
    type: Literal["terminal"]
    terminal_id: str        # Reference to a created terminal
```

**ToolCallLocation** — Where the tool operates:

```python
class ToolCallLocation:
    path: str               # File path
    line: int | None        # Specific line number
```

**ToolCallUpdate** — Lightweight reference used in permission requests:

```python
class ToolCallUpdate:
    tool_call_id: str
    title: str | None
    kind: ToolKind | None
    status: ToolCallStatus | None
    # ... (partial subset of ToolCallStart/Progress)
```

### 5.3 Sessions

```python
class NewSessionRequest:
    cwd: str
    mcp_servers: list[McpServer] | None

class NewSessionResponse:
    session_id: str
    modes: SessionModeState | None
    models: SessionModelState | None  # unstable
    config_options: list[SessionConfigOption] | None

class SessionModeState:
    current_mode_id: str
    available_modes: list[SessionMode]

class SessionMode:
    id: str
    name: str
    description: str | None

class SessionModelState:  # unstable
    current_model_id: str
    available_models: list[ModelInfo]

class ModelInfo:
    model_id: str
    name: str
    description: str | None

class SessionInfo:
    session_id: str
    cwd: str | None
    title: str | None
    updated_at: str | None  # ISO 8601
```

### 5.4 Session Configuration

```python
class SessionConfigOption:  # discriminator: "type"
    type: Literal["select"]

class SessionConfigSelect(SessionConfigOption):
    config_id: str
    name: str
    current_value: str
    options: list[SessionConfigSelectOption | SessionConfigSelectGroup]

class SessionConfigSelectOption:
    value: str
    name: str
    description: str | None

class SessionConfigSelectGroup:
    group: str
    name: str
    options: list[SessionConfigSelectOption]
```

### 5.5 Permissions

```python
class PermissionOption:
    option_id: str
    name: str
    kind: PermissionOptionKind  # "allow_once" | "allow_always" | "reject_once" | "reject_always"

class RequestPermissionResponse:
    outcome: AllowedOutcome | DeniedOutcome

class AllowedOutcome:
    outcome: Literal["selected"]
    option_id: str

class DeniedOutcome:
    outcome: Literal["cancelled"]
```

### 5.6 Plans

```python
class PlanEntry:
    content: str                    # What this step does
    priority: PlanEntryPriority     # "high" | "medium" | "low"
    status: PlanEntryStatus         # "pending" | "in_progress" | "completed"
```

### 5.7 Capabilities

```python
class AgentCapabilities:
    load_session: bool | None
    mcp_capabilities: McpCapabilities | None  # {"http": bool, "sse": bool}
    prompt_capabilities: PromptCapabilities | None  # {"image": bool, "audio": bool, "embeddedContext": bool}
    session_capabilities: SessionCapabilities | None  # {"fork": bool, "list": bool, "resume": bool}

class ClientCapabilities:
    fs: FsCapabilities | None       # {"readTextFile": bool, "writeTextFile": bool}
    terminal: bool | None           # Can create terminals
```

### 5.8 MCP Server Configuration

Three transport types for passing MCP server configs to agents:

```python
class McpServerStdio:
    type: Literal["stdio"]
    name: str
    command: str
    args: list[str]
    env: list[EnvVariable]

class HttpMcpServer:
    type: Literal["http"]
    name: str
    url: str
    headers: list[EnvVariable]

class SseMcpServer:
    type: Literal["sse"]
    name: str
    url: str
    headers: list[EnvVariable]

class EnvVariable:
    name: str
    value: str
```

### 5.9 Terminal Types

```python
class CreateTerminalRequest:
    session_id: str
    command: str
    args: list[str] | None
    cwd: str | None
    env: list[EnvVariable] | None
    output_byte_limit: int | None

class CreateTerminalResponse:
    terminal_id: str

class TerminalOutputResponse:
    output: str
    truncated: bool
    exit_status: TerminalExitStatus | None

class TerminalExitStatus:
    exit_code: int | None
    signal: str | None
```

### 5.10 Usage & Cost

```python
class Usage:  # unstable
    total_tokens: int
    input_tokens: int
    output_tokens: int
    cached_read_tokens: int | None
    cached_write_tokens: int | None
    thought_tokens: int | None

class Cost:  # unstable
    amount: float
    currency: str
```

### 5.11 Authentication & Implementation Info

```python
class AuthMethod:
    id: str
    name: str
    description: str | None

class Implementation:
    name: str
    version: str
    title: str | None
```

### 5.12 Stop Reasons

When a prompt completes, the `stop_reason` indicates why:

| Value | Meaning |
|-------|---------|
| `"end_turn"` | Agent completed naturally |
| `"max_tokens"` | Hit token limit |
| `"max_turn_requests"` | Exceeded maximum request turns |
| `"refusal"` | Agent refused the request |
| `"cancelled"` | Client cancelled the operation |

---

## 6. Python SDK Internals — Module-by-Module

The SDK source lives in `src/acp/`. Here's what each module does:

### 6.1 `__init__.py` — Public API Surface

Re-exports everything you need for building agents and clients:

```python
# Core classes
from acp import Agent, Client, RequestError, run_agent, connect_to_agent

# Constants
from acp import PROTOCOL_VERSION, AGENT_METHODS, CLIENT_METHODS

# Helpers (builders)
from acp import text_block, image_block, audio_block, resource_link_block, resource_block
from acp import start_tool_call, update_tool_call, tool_diff_content, tool_content, tool_terminal_ref
from acp import update_agent_message, update_agent_message_text, update_plan, plan_entry
from acp import session_notification

# Process management
from acp import spawn_agent_process, spawn_client_process, spawn_stdio_connection, stdio_streams
from acp import spawn_stdio_transport, default_environment

# Schema models (all request/response types)
from acp import InitializeRequest, InitializeResponse, PromptRequest, PromptResponse  # ... etc.
```

### 6.2 `schema.py` — Generated Pydantic Models (~1500 lines)

Auto-generated from `schema/schema.json` by the code generation pipeline. Contains every data type in the ACP protocol as Pydantic `BaseModel` classes.

**Key feature: Case-compatible BaseModel**

The generated code includes a custom `BaseModel` that supports both `snake_case` and `camelCase` access:

```python
# Both work:
response.protocol_version  # snake_case (canonical)
response.protocolVersion   # camelCase (legacy/JSON compatibility)
```

This is achieved via a custom `__getattr__` that converts camelCase attribute access to snake_case lookups, plus `populate_by_name=True` in Pydantic config.

**`field_meta` support**: Models can carry arbitrary metadata via a special `field_meta` attribute that serializes to `_meta` in JSON:

```python
chunk = update_agent_message(text_block("hello"))
chunk.field_meta = {"source": "echo_agent"}
# Serializes to: {"sessionUpdate": "agent_message_chunk", "content": {...}, "_meta": {"source": "echo_agent"}}
```

### 6.3 `meta.py` — Method Routing Constants

Generated from `schema/meta.json`. Maps Python method names to JSON-RPC method strings:

```python
AGENT_METHODS = {
    "initialize": "initialize",
    "session_new": "session/new",
    "session_load": "session/load",
    "session_prompt": "session/prompt",
    "session_cancel": "session/cancel",
    "session_set_mode": "session/set_mode",
    "session_set_config_option": "session/set_config_option",
    "authenticate": "authenticate",
    "session_list": "session/list",       # unstable
    "session_fork": "session/fork",       # unstable
    "session_resume": "session/resume",   # unstable
    "session_set_model": "session/set_model",  # unstable
}

CLIENT_METHODS = {
    "session_request_permission": "session/request_permission",
    "session_update": "session/update",
    "fs_read_text_file": "fs/read_text_file",
    "fs_write_text_file": "fs/write_text_file",
    "terminal_create": "terminal/create",
    "terminal_output": "terminal/output",
    "terminal_release": "terminal/release",
    "terminal_wait_for_exit": "terminal/wait_for_exit",
    "terminal_kill": "terminal/kill",
}

PROTOCOL_VERSION = 1
```

### 6.4 `interfaces.py` — Protocol Definitions

Defines the `Agent` and `Client` as Python `Protocol` classes (structural typing). These are the contracts your implementations must satisfy:

**Agent Protocol** (22 methods):

```python
class Agent(Protocol):
    async def initialize(self, protocol_version: int,
                        client_capabilities: ClientCapabilities | None = None,
                        client_info: Implementation | None = None, **kwargs) -> InitializeResponse
    async def new_session(self, cwd: str,
                         mcp_servers: list[McpServer] | None = None, **kwargs) -> NewSessionResponse
    async def load_session(self, cwd: str, session_id: str,
                          mcp_servers: list[McpServer] | None = None, **kwargs) -> LoadSessionResponse | None
    async def list_sessions(self, cursor: str | None = None,
                           cwd: str | None = None, **kwargs) -> ListSessionsResponse  # unstable
    async def set_session_mode(self, mode_id: str, session_id: str, **kwargs) -> SetSessionModeResponse | None
    async def set_session_model(self, model_id: str, session_id: str, **kwargs) -> SetSessionModelResponse | None  # unstable
    async def set_config_option(self, config_id: str, session_id: str, value: str, **kwargs) -> SetSessionConfigOptionResponse | None
    async def authenticate(self, method_id: str, **kwargs) -> AuthenticateResponse | None
    async def prompt(self, prompt: list[ContentBlock], session_id: str, **kwargs) -> PromptResponse
    async def fork_session(self, cwd: str, session_id: str, ...) -> ForkSessionResponse  # unstable
    async def resume_session(self, cwd: str, session_id: str, ...) -> ResumeSessionResponse  # unstable
    async def cancel(self, session_id: str, **kwargs) -> None  # notification
    async def ext_method(self, method: str, params: dict) -> dict
    async def ext_notification(self, method: str, params: dict) -> None
    def on_connect(self, conn: Client) -> None
```

**Client Protocol** (9 methods):

```python
class Client(Protocol):
    async def request_permission(self, options: list[PermissionOption], session_id: str,
                                tool_call: ToolCallUpdate, **kwargs) -> RequestPermissionResponse
    async def session_update(self, session_id: str, update: SessionUpdate, **kwargs) -> None
    async def write_text_file(self, content: str, path: str, session_id: str, **kwargs) -> WriteTextFileResponse | None
    async def read_text_file(self, path: str, session_id: str,
                            limit: int | None = None, line: int | None = None, **kwargs) -> ReadTextFileResponse
    async def create_terminal(self, command: str, session_id: str,
                             args: list[str] | None = None, cwd: str | None = None, ...) -> CreateTerminalResponse
    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs) -> TerminalOutputResponse
    async def release_terminal(self, session_id: str, terminal_id: str, **kwargs) -> ReleaseTerminalResponse | None
    async def wait_for_terminal_exit(self, session_id: str, terminal_id: str, **kwargs) -> WaitForTerminalExitResponse
    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs) -> KillTerminalCommandResponse | None
    async def ext_method(self, method: str, params: dict) -> dict
    async def ext_notification(self, method: str, params: dict) -> None
    def on_connect(self, conn: Agent) -> None
```

### 6.5 `core.py` — Entry Points

Two main functions:

```python
async def run_agent(agent: Agent,
                   input_stream=None, output_stream=None,
                   use_unstable_protocol=False,
                   stdio_buffer_limit_bytes=50_000_000) -> None:
    """Start an agent listening on stdio (or custom streams).
    Blocks until the connection closes."""

def connect_to_agent(client: Client,
                    input_stream, output_stream,
                    use_unstable_protocol=False) -> ClientSideConnection:
    """Create a client connection to an agent. Returns immediately;
    caller drives the interaction."""
```

### 6.6 `connection.py` — Low-Level JSON-RPC

The core `Connection` class handles the JSON-RPC 2.0 transport:

- **Framing**: Newline-delimited JSON (one JSON object per line)
- **Request/response correlation**: Uses incrementing `request_id` counter
- **Concurrent requests**: Multiple requests can be in-flight simultaneously
- **Observer pattern**: `add_observer(StreamObserver)` taps into raw message stream
- **Error handling**: Invalid JSON → parse error, bad params → error -32602, unknown method → error -32601

### 6.7 `router.py` — Message Routing

`MessageRouter` maps incoming method names to handler functions:

```python
router = MessageRouter(use_unstable_protocol=False)
router.route_request("session/new", NewSessionRequest, agent, "new_session")
router.route_notification("session/cancel", CancelNotification, agent, "cancel")
```

Features:
- **`@param_model` extraction**: Automatically unpacks Pydantic model fields into function keyword arguments
- **Optional methods**: Some methods have defaults (e.g., terminal ops return `None` if unimplemented)
- **Unstable gating**: Methods marked `unstable=True` are only available when `use_unstable_protocol=True`
- **Extension routing**: Delegates unrecognized methods to `ext_method` / `ext_notification` handlers
- **Result adaptation**: Converts Pydantic models to dicts for JSON-RPC responses

### 6.8 `agent/` — Agent-Side Implementation

**`AgentSideConnection`** wraps your `Agent` implementation and:
- Routes incoming client requests to your agent methods
- Provides methods to call the remote client:
  - `session_update()`, `request_permission()`
  - `read_text_file()`, `write_text_file()`
  - `create_terminal()`, `terminal_output()`, etc.
- `listen()` → runs the receive loop (blocking)

### 6.9 `client/` — Client-Side Implementation

**`ClientSideConnection`** wraps your `Client` implementation and:
- Routes incoming agent requests to your client methods
- Provides methods to call the remote agent:
  - `initialize()`, `new_session()`, `load_session()`
  - `prompt()`, `cancel()`
  - `set_session_mode()`, `set_config_option()`, etc.
- Caller controls the message loop (non-blocking creation)

### 6.10 `task/` — Background Task Infrastructure

| Module | Class | Purpose |
|--------|-------|---------|
| `supervisor.py` | `TaskSupervisor` | Manages background asyncio tasks, error handlers, graceful shutdown |
| `queue.py` | `InMemoryMessageQueue` | FIFO async queue for RPC task dispatch |
| `dispatcher.py` | `DefaultMessageDispatcher` | Consumes queue, spawns handler tasks |
| `sender.py` | `MessageSender` | JSON serialization + write with backpressure |
| `state.py` | `InMemoryMessageStateStore` | Tracks pending requests via `asyncio.Future` correlation |

### 6.11 `transports.py` — Transport Implementations

```python
async with spawn_stdio_transport(command, *args, env=None, cwd=None, limit=None) as (reader, writer, process):
    # reader: StreamReader, writer: StreamWriter, process: Process
    # Defensive shutdown: close stdin → terminate → kill (with timeouts)
```

Also provides `default_environment()` for safe environment variable management.

### 6.12 `stdio.py` — stdio Transport + Process Spawning

```python
# Get stdin/stdout as async streams
reader, writer = await stdio_streams(limit=50_000_000)

# Spawn agent as subprocess, get client connection
async with spawn_agent_process(client, "python", "agent.py", env=env) as (conn, process):
    await conn.initialize(protocol_version=PROTOCOL_VERSION)

# Spawn client as subprocess, get agent connection
async with spawn_client_process(agent, "python", "client.py") as (conn, process):
    await conn.listen()

# Low-level spawn
async with spawn_stdio_connection(agent_or_client, "command", *args, side="agent") as (conn, process):
    ...
```

### 6.13 `exceptions.py` — Error Types

```python
class RequestError(Exception):
    code: int
    message: str
    data: Any

    @classmethod
    def method_not_found(cls, method: str) -> RequestError  # -32601
    # ... other factory methods for standard error codes
```

### 6.14 `telemetry.py` — Observability

Provides `StreamObserver` protocol for tapping into raw JSON-RPC messages for logging, debugging, and monitoring.

---

## 7. Helpers Reference — Every Builder Function

The `acp.helpers` module provides type-safe builder functions. Using these instead of constructing models directly ensures your code stays aligned with schema updates.

### 7.1 Content Block Builders

```python
from acp import text_block, image_block, audio_block, resource_link_block, resource_block
from acp import embedded_text_resource, embedded_blob_resource

# Plain text
text_block("Hello, world!")
# → TextContentBlock(type="text", text="Hello, world!")

# Base64-encoded image
image_block(data="iVBOR...", mime_type="image/png", uri="file:///screenshot.png")
# → ImageContentBlock(type="image", data="iVBOR...", mime_type="image/png", uri=...)

# Base64-encoded audio
audio_block(data="RIFF...", mime_type="audio/wav")
# → AudioContentBlock(type="audio", data="RIFF...", mime_type="audio/wav")

# Reference to a file (link only, not content)
resource_link_block("main.py", "file:///project/main.py", mime_type="text/x-python", size=1024)
# → ResourceContentBlock(type="resource_link", name="main.py", uri=..., ...)

# Inline text resource
res = embedded_text_resource("file:///context.txt", "Some context text", mime_type="text/plain")
resource_block(res)
# → EmbeddedResourceContentBlock(type="resource", resource=TextResourceContents(...))

# Inline binary resource
blob = embedded_blob_resource("file:///image.pdf", "base64data...", mime_type="application/pdf")
resource_block(blob)
# → EmbeddedResourceContentBlock(type="resource", resource=BlobResourceContents(...))
```

### 7.2 Tool Call Builders

```python
from acp import start_tool_call, start_read_tool_call, start_edit_tool_call, update_tool_call

# Generic tool call
start_tool_call("call_001", "Search codebase",
    kind="search", status="pending",
    raw_input={"query": "def main"})

# Read file tool call (pre-filled kind, status, location)
start_read_tool_call("call_002", "Read main.py", path="/project/main.py")

# Edit file tool call (pre-filled kind, location, raw_input)
start_edit_tool_call("call_003", "Fix bug", path="/project/main.py", content="new code...")

# Update an existing tool call
update_tool_call("call_002",
    status="completed",
    content=[tool_content(text_block("File contents here"))],
    raw_output={"lines": 42})
```

### 7.3 Tool Call Content Builders

```python
from acp import tool_content, tool_diff_content, tool_terminal_ref

# Wrap any content block as tool call content
tool_content(text_block("Command output: OK"))
# → ContentToolCallContent(type="content", content=TextContentBlock(...))

# File diff (edit)
tool_diff_content("main.py", new_text="fixed code", old_text="buggy code")
# → FileEditToolCallContent(type="diff", path="main.py", new_text=..., old_text=...)

# File diff (new file creation — no old_text)
tool_diff_content("new_file.py", new_text="print('hello')")
# → FileEditToolCallContent(type="diff", path="new_file.py", new_text=..., old_text=None)

# Terminal reference
tool_terminal_ref("term_001")
# → TerminalToolCallContent(type="terminal", terminal_id="term_001")
```

### 7.4 Session Update Builders

```python
from acp import (
    update_agent_message, update_agent_message_text,
    update_agent_thought, update_agent_thought_text,
    update_user_message, update_user_message_text,
    update_plan, plan_entry,
    update_available_commands, update_current_mode,
    session_notification,
)

# Agent message (any content block)
update_agent_message(text_block("Here's the fix..."))
update_agent_message(image_block(data="...", mime_type="image/png"))

# Agent message (text shorthand)
update_agent_message_text("Here's the fix...")

# Agent thought (reasoning)
update_agent_thought_text("I need to check the test file first...")

# User message echo
update_user_message_text("Fix the bug in main.py")

# Execution plan
update_plan([
    plan_entry("Read the file", priority="high", status="completed"),
    plan_entry("Apply the fix", priority="high", status="in_progress"),
    plan_entry("Run tests", priority="medium", status="pending"),
])

# Available commands
from acp.schema import AvailableCommand
update_available_commands([AvailableCommand(id="cancel", name="Cancel")])

# Mode change
update_current_mode("architect")

# Wrap any update with a session ID for the notification envelope
session_notification("session_123", update_agent_message_text("Done!"))
```

---

## 8. Contrib Utilities — Production Patterns

The `acp.contrib` module provides experimental but powerful utilities for common production patterns. Import from `acp.contrib.*` — they are opt-in and never loaded by the core runtime.

### 8.1 `SessionAccumulator` — State Tracking

Reconciles streamed session updates into a single, immutable snapshot. Essential for building UIs that display agent state.

```python
from acp.contrib.session_state import SessionAccumulator, SessionSnapshot

accumulator = SessionAccumulator(auto_reset_on_session_change=True)

# Feed notifications as they arrive
snapshot: SessionSnapshot = accumulator.apply(notification)

# Or get current state at any time
snapshot = accumulator.snapshot()

# Subscribe to state changes
@accumulator.subscribe
def on_change(snapshot: SessionSnapshot, notification: SessionNotification):
    render_ui(snapshot)
```

**`SessionSnapshot`** contains:

```python
class SessionSnapshot:
    session_id: str
    tool_calls: dict[str, ToolCallView]    # Merged start + progress
    plan_entries: tuple[PlanEntry, ...]
    current_mode_id: str | None
    available_commands: tuple[AvailableCommand, ...]
    user_messages: tuple[UserMessageChunk, ...]
    agent_messages: tuple[AgentMessageChunk, ...]
    agent_thoughts: tuple[AgentThoughtChunk, ...]
```

**Key behavior**: Tool calls from `ToolCallStart` and `ToolCallProgress` are merged by `tool_call_id` into a single `ToolCallView` with the latest status, title, content, etc. This means you don't need to track tool call lifecycle yourself — the accumulator does it.

### 8.2 `ToolCallTracker` — Tool Call Lifecycle Management

For agents that need to track tool call state (ID mapping, streaming text accumulation, status transitions):

```python
from acp.contrib.tool_calls import ToolCallTracker

tracker = ToolCallTracker()

# Start a tool call (generates internal ACP tool call ID)
start_update = tracker.start("my_read_op", title="Read main.py", kind="read")
# → ToolCallStart with auto-generated tool_call_id

# Update status
progress_update = tracker.progress("my_read_op", status="in_progress")
# → ToolCallProgress

# Stream text content incrementally
chunk1 = tracker.append_stream_text("my_read_op", "Line 1\n")
chunk2 = tracker.append_stream_text("my_read_op", "Line 2\n")
# Accumulates text into a single ContentToolCallContent

# Get current view
view = tracker.view("my_read_op")
# → TrackedToolCallView with all accumulated state

# Get model for permission requests
tool_model = tracker.tool_call_model("my_read_op")
# → ToolCallUpdate (for use in request_permission)

# Clean up
tracker.forget("my_read_op")
```

### 8.3 `PermissionBroker` — Approval Workflows

Wraps the permission request flow with sensible defaults:

```python
from acp.contrib.permissions import PermissionBroker, default_permission_options

broker = PermissionBroker(
    session_id="abc123",
    requester=conn.request_permission,  # The actual RPC call
    tracker=tracker,                     # Optional ToolCallTracker for context
    default_options=default_permission_options(),  # Allow Once, Allow Always, Reject
)

# Request permission with context
response = await broker.request_for(
    external_id="my_delete_op",
    description="Delete temporary files",
    options=None,  # Uses defaults
    tool_call=tracker.tool_call_model("my_delete_op") if tracker else None,
)

# Check outcome
if response.outcome.outcome == "selected":
    option_id = response.outcome.option_id
    # "allow-once", "allow-session", or "reject"
```

**`default_permission_options()`** returns:

```python
(
    PermissionOption(option_id="allow-once", name="Allow", kind="allow_once"),
    PermissionOption(option_id="allow-session", name="Always Allow", kind="allow_always"),
    PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
)
```

---

## 9. Capabilities & Initialization

### The Initialization Handshake

Every ACP connection starts with an `initialize` exchange. This is where the agent and client discover each other's features:

```
Client                                Agent
  │                                     │
  │── initialize ──────────────────────►│
  │   {protocolVersion: 1,              │
  │    clientCapabilities: {            │
  │      fs: {readTextFile: true,       │
  │           writeTextFile: true},     │
  │      terminal: true                 │
  │    },                               │
  │    clientInfo: {name: "zed", ...}}  │
  │                                     │
  │◄──────────────────── response ──────│
  │   {protocolVersion: 1,              │
  │    agentCapabilities: {             │
  │      loadSession: true,             │
  │      promptCapabilities: {          │
  │        image: true,                 │
  │        audio: false,                │
  │        embeddedContext: true         │
  │      },                             │
  │      mcpCapabilities: {             │
  │        http: true, sse: true        │
  │      },                             │
  │      sessionCapabilities: {         │
  │        fork: true, list: true       │
  │      }                              │
  │    },                               │
  │    agentInfo: {name: "my-agent"},   │
  │    authMethods: [...]}              │
  │                                     │
```

### Agent Capabilities

| Capability | What It Means |
|---|---|
| `loadSession` | Agent supports `session/load` (resume existing sessions) |
| `mcpCapabilities.http` | Agent can connect to HTTP MCP servers |
| `mcpCapabilities.sse` | Agent can connect to SSE MCP servers |
| `promptCapabilities.image` | Agent accepts image content blocks in prompts |
| `promptCapabilities.audio` | Agent accepts audio content blocks in prompts |
| `promptCapabilities.embeddedContext` | Agent accepts embedded resource content in prompts |
| `sessionCapabilities.fork` | Agent supports `session/fork` *(unstable)* |
| `sessionCapabilities.list` | Agent supports `session/list` *(unstable)* |
| `sessionCapabilities.resume` | Agent supports `session/resume` *(unstable)* |

### Client Capabilities

| Capability | What It Means |
|---|---|
| `fs.readTextFile` | Client supports `fs/read_text_file` (agent can read files) |
| `fs.writeTextFile` | Client supports `fs/write_text_file` (agent can write files) |
| `terminal` | Client supports `terminal/*` operations (agent can run commands) |

### Why Capabilities Matter

An agent should check client capabilities before trying to use features:

```python
async def prompt(self, prompt, session_id, **kwargs):
    # Don't try to read files if the client doesn't support it
    if self._client_capabilities and self._client_capabilities.fs and self._client_capabilities.fs.read_text_file:
        content = await self._conn.read_text_file(path="main.py", session_id=session_id)
    else:
        # Fall back to asking the user to paste the file
        await self._conn.session_update(session_id, update_agent_message_text("Please paste the file contents"))
```

---

## 10. Unstable & Experimental Features

Some ACP features are marked **unstable** — they may change or be removed in future protocol versions. To use them, you must opt in:

```python
# Agent side
await run_agent(my_agent, use_unstable_protocol=True)

# Client side
conn = connect_to_agent(my_client, stdin, stdout, use_unstable_protocol=True)
```

### Unstable Methods

| Method | Purpose |
|--------|---------|
| `session/list` | List all sessions with optional cursor pagination |
| `session/set_model` | Change the AI model mid-session |
| `session/fork` | Create a child session from an existing one |
| `session/resume` | Resume a session without replaying message history |
| `$/cancel_request` | Cancel a specific in-flight request by ID |

### Unstable Session Updates

| Update | Purpose |
|--------|---------|
| `usage_update` | Report token usage and cost information |

### Behavior Without Opt-In

If `use_unstable_protocol=False` (default), calling unstable methods raises a `RequestError` with a `UserWarning`, protecting against accidental use of features that may change.

---

## 11. Code Generation Pipeline

The Python SDK doesn't hand-write protocol types — it generates them from the canonical ACP JSON Schema. This ensures the SDK always matches the protocol specification.

### Pipeline Overview

```
schema/schema.json  ──►  gen_schema.py  ──►  src/acp/schema.py  (Pydantic models)
schema/meta.json    ──►  gen_meta.py    ──►  src/acp/meta.py    (method constants)
src/acp/**/*.py     ──►  gen_signature.py ──►  (fixes function signatures)
```

### Running Code Generation

```bash
# Regenerate from a specific schema version
ACP_SCHEMA_VERSION=v0.10.8 make gen-all

# Or manually
python scripts/gen_all.py --version v0.10.8
```

### Step 1: `gen_schema.py`

1. Runs `datamodel-code-generator` on `schema.json` to produce raw Pydantic models
2. Post-processes the output:
   - Renames generic numbered models (e.g., `SessionUpdate1` → `AgentMessageChunk`)
   - Fixes enum types to use `Literal` type aliases
   - Sets correct default values
   - Adds documentation comments from JSON schema descriptions
   - Injects custom `BaseModel` with camelCase/snake_case compatibility
   - Creates type aliases for enums (`ToolKind`, `StopReason`, etc.)

### Step 2: `gen_meta.py`

Reads `meta.json` and generates `meta.py` with:
- `AGENT_METHODS` dict (12 methods)
- `CLIENT_METHODS` dict (9 methods)  
- `PROTOCOL_VERSION` constant

### Step 3: `gen_signature.py`

Scans all SDK files for functions decorated with `@param_model(ModelClass)` and regenerates their signatures based on the Pydantic model's field definitions. This ensures function signatures always match the schema.

### When to Regenerate

- When the upstream ACP schema releases a new version
- After modifying `schema/schema.json` locally for testing
- When contributing to the SDK and updating protocol features

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| **ACP** | Agent-Client Protocol — bidirectional JSON-RPC 2.0 protocol for AI agent ↔ client communication |
| **Agent** | The AI-powered side: processes prompts, calls tools, streams responses |
| **Client** | The user-facing side: editor, CLI, UI, notebook that displays agent output |
| **Session** | A stateful conversation context with unique ID, mode, model, and config |
| **Prompt** | A list of content blocks sent by the client for the agent to process |
| **Session Update** | A notification streamed from agent to client during prompt processing |
| **Content Block** | A typed unit of content: text, image, audio, resource link, or embedded resource |
| **Tool Call** | An action the agent takes, tracked with start/progress/complete lifecycle |
| **Tool Kind** | Category of tool action: read, edit, delete, execute, search, think, etc. |
| **Permission** | A structured approval flow: agent requests → client presents options → user decides |
| **Capability** | A feature flag negotiated during initialization (e.g., file I/O, terminals) |
| **MCP** | Model Context Protocol — complementary protocol for LLM ↔ tool communication |
| **Extension Method** | Custom RPC method not in the core protocol, for protocol extensions |
| **Stop Reason** | Why a prompt response ended: end_turn, max_tokens, cancelled, refusal |
| **Plan Entry** | A step in the agent's execution plan with content, priority, and status |
| **Golden File** | A reference JSON fixture used to validate wire format compatibility |
| **Unstable** | A feature that may change in future protocol versions (opt-in required) |

---

> **Next:** See `ACP_PRACTICAL_GUIDE.md` for hands-on code examples, step-by-step agent/client building, framework integration with DeepAgent/LangGraph, and advanced patterns.
