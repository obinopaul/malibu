# ACP (Agent-Client Protocol) — Practical Guide

> **Audience:** AI engineers who want to build with ACP — running examples, writing agents and clients, integrating agent frameworks, and understanding protocol details.
>
> **Companion document:** See `ACP_COMPLETE_GUIDE.md` for the full reference on every ACP component, type, and message.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Building Your First ACP Agent](#2-building-your-first-acp-agent)
3. [Building Your First ACP Client](#3-building-your-first-acp-client)
4. [Advanced Agent Patterns](#4-advanced-agent-patterns)
5. [Plugging Agent Frameworks into ACP](#5-plugging-agent-frameworks-into-acp)
6. [Wire Format & Protocol Details](#6-wire-format--protocol-details)
7. [Testing & Development](#7-testing--development)
8. [Migration & Versioning](#8-migration--versioning)

---

## 1. Getting Started

### 1.1 Installation

```bash
# Using pip
pip install agent-client-protocol

# Using uv (recommended)
uv add agent-client-protocol
```

For development (clone + full tooling):

```bash
git clone https://github.com/anthropics/python-sdk.git
cd python-sdk
make install   # Sets up uv, installs deps, configures pre-commit hooks
```

### 1.2 Running Your First Agent — Echo Agent

The simplest way to see ACP in action:

```bash
python examples/echo_agent.py
```

This starts an agent that listens on stdin/stdout. It echoes back whatever the client sends. Leave it running — it's waiting for a client to connect.

### 1.3 Running the Interactive Client

In a separate terminal:

```bash
python examples/client.py examples/agent.py
```

This spawns `agent.py` as a subprocess and connects to it. You'll see a `>` prompt:

```
> Hello agent!
| Agent: Client sent:
| Agent: Hello agent!
> Fix the bug in main.py
| Agent: Client sent:
| Agent: Fix the bug in main.py
```

### 1.4 Running the Duet (Self-Contained Demo)

The duet example embeds both agent and client in one script:

```bash
python examples/duet.py
```

This is identical to running `client.py` + `agent.py` separately, but managed in a single process using `spawn_agent_process()`.

### 1.5 Connecting from Zed Editor

Add to Zed's `settings.json`:

```json
{
  "agent_servers": {
    "Echo Agent (Python)": {
      "type": "custom",
      "command": "/path/to/python",
      "args": ["/path/to/echo_agent.py"]
    }
  }
}
```

Zed will spawn the agent and communicate over ACP automatically.

### 1.6 Running the Gemini CLI Bridge

If you have Google's Gemini CLI installed:

```bash
# Auto-approve all permissions
python examples/gemini.py --yolo

# Specific model + sandboxed
python examples/gemini.py --sandbox --model gemini-1.5-pro

# Debug output
python examples/gemini.py --debug

# Custom Gemini binary path
ACP_GEMINI_BIN=/path/to/gemini python examples/gemini.py
```

### 1.7 Summary of Examples

| Example | Command | What It Does |
|---------|---------|-------------|
| `echo_agent.py` | `python examples/echo_agent.py` | Minimal agent — echoes input back |
| `agent.py` | `python examples/agent.py` | Full-featured agent with sessions, modes, auth |
| `client.py` | `python examples/client.py examples/agent.py` | Interactive client that spawns an agent |
| `duet.py` | `python examples/duet.py` | Embedded agent + client in one script |
| `gemini.py` | `python examples/gemini.py --yolo` | Bridges to Gemini CLI with permissions, file I/O, terminals |

---

## 2. Building Your First ACP Agent

### 2.1 Minimal Agent (Echo)

Here's the complete echo agent — the simplest possible ACP agent:

```python
import asyncio
from typing import Any
from uuid import uuid4

from acp import (
    Agent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    text_block,
    update_agent_message,
)
from acp.interfaces import Client
from acp.schema import (
    ClientCapabilities,
    HttpMcpServer,
    Implementation,
    McpServerStdio,
    SseMcpServer,
    TextContentBlock,
    ImageContentBlock,
    AudioContentBlock,
    ResourceContentBlock,
    EmbeddedResourceContentBlock,
)


class EchoAgent(Agent):
    _conn: Client  # Reference to the connected client

    def on_connect(self, conn: Client) -> None:
        """Called when a client connects. Store the connection for later use."""
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        """Respond to initialization — just echo back the protocol version."""
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(
        self, cwd: str, mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio], **kwargs: Any
    ) -> NewSessionResponse:
        """Create a new session with a unique ID."""
        return NewSessionResponse(session_id=uuid4().hex)

    async def prompt(
        self,
        prompt: list[
            TextContentBlock | ImageContentBlock | AudioContentBlock
            | ResourceContentBlock | EmbeddedResourceContentBlock
        ],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        """Process the prompt by echoing each content block back."""
        for block in prompt:
            text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
            chunk = update_agent_message(text_block(text))
            await self._conn.session_update(session_id=session_id, update=chunk)
        return PromptResponse(stop_reason="end_turn")


async def main() -> None:
    await run_agent(EchoAgent())


if __name__ == "__main__":
    asyncio.run(main())
```

**Key patterns:**
1. **Subclass `Agent`** — Implement the methods you need
2. **Store `_conn` in `on_connect`** — This is how the agent calls back to the client
3. **`run_agent()`** — Starts the agent on stdio, blocks until the connection closes
4. **Stream responses via `session_update()`** — Don't return text in `PromptResponse`; stream it as notifications
5. **Return `PromptResponse`** with appropriate `stop_reason`

### 2.2 Full-Featured Agent

Here's a production-ready agent template showing all major features:

```python
import asyncio
import logging
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    Agent,
    AuthenticateResponse,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    SetSessionModeResponse,
    run_agent,
    text_block,
    update_agent_message,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    ClientCapabilities,
    Implementation,
    HttpMcpServer,
    McpServerStdio,
    SseMcpServer,
    TextContentBlock,
    ImageContentBlock,
    AudioContentBlock,
    ResourceContentBlock,
    EmbeddedResourceContentBlock,
    AgentMessageChunk,
)


class MyAgent(Agent):
    _conn: Client

    def __init__(self) -> None:
        self._next_session_id = 0
        self._sessions: set[str] = set()

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        # Store client capabilities so you know what features are available
        self._client_caps = client_capabilities
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(name="my-agent", title="My Custom Agent", version="1.0.0"),
        )

    async def authenticate(self, method_id: str, **kwargs: Any) -> AuthenticateResponse | None:
        return AuthenticateResponse()

    async def new_session(
        self, cwd: str, mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio], **kwargs: Any
    ) -> NewSessionResponse:
        session_id = str(self._next_session_id)
        self._next_session_id += 1
        self._sessions.add(session_id)
        return NewSessionResponse(session_id=session_id, modes=None)

    async def load_session(
        self, cwd: str, session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any
    ) -> LoadSessionResponse | None:
        self._sessions.add(session_id)
        return LoadSessionResponse()

    async def set_session_mode(self, mode_id: str, session_id: str, **kwargs: Any) -> SetSessionModeResponse | None:
        return SetSessionModeResponse()

    async def prompt(
        self,
        prompt: list[TextContentBlock | ImageContentBlock | AudioContentBlock
                     | ResourceContentBlock | EmbeddedResourceContentBlock],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        # ─── YOUR AGENT LOGIC HERE ───

        # Stream a response back to the client
        await self._conn.session_update(
            session_id, update_agent_message(text_block("Processing your request..."))
        )

        # Example: process each content block
        for block in prompt:
            if isinstance(block, TextContentBlock):
                # Handle text input
                user_text = block.text
            elif isinstance(block, ImageContentBlock):
                # Handle image input
                pass
            elif isinstance(block, ResourceContentBlock):
                # Handle file reference
                pass

        # Stream the final response
        await self._conn.session_update(
            session_id, update_agent_message(text_block("Done!"))
        )

        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        logging.info("Cancelled session %s", session_id)

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"status": "not_implemented"}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await run_agent(MyAgent())


if __name__ == "__main__":
    asyncio.run(main())
```

### 2.3 What Methods Must You Implement?

| Method | Required? | Why |
|--------|----------|-----|
| `on_connect` | Yes | Store the client connection reference |
| `initialize` | Yes | Negotiate protocol version and capabilities |
| `new_session` | Yes | Create a session ID for the conversation |
| `prompt` | Yes | Handle user messages — this is your agent's main logic |
| `cancel` | Recommended | Handle cancellation gracefully |
| `load_session` | Optional | If you want to support resuming sessions |
| `set_session_mode` | Optional | If your agent has multiple modes |
| `set_config_option` | Optional | If you expose configuration |
| `authenticate` | Optional | If you need authentication |
| `ext_method` / `ext_notification` | Optional | For custom protocol extensions |

---

## 3. Building Your First ACP Client

### 3.1 Minimal Client

```python
import asyncio
import os
import sys
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    Client,
    RequestError,
    connect_to_agent,
    text_block,
)
from acp.core import ClientSideConnection
from acp.schema import (
    AgentMessageChunk,
    PermissionOption,
    ReadTextFileResponse,
    RequestPermissionResponse,
    TextContentBlock,
    ToolCallUpdate,
    WriteTextFileResponse,
    ClientCapabilities,
    Implementation,
)
import asyncio.subprocess as aio_subprocess


class SimpleClient(Client):
    """A minimal ACP client that prints agent messages."""

    async def session_update(self, session_id, update, **kwargs) -> None:
        """Handle streaming updates from the agent."""
        if isinstance(update, AgentMessageChunk):
            content = update.content
            if isinstance(content, TextContentBlock):
                print(f"Agent: {content.text}")

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        """Handle permission requests — reject everything by default."""
        raise RequestError.method_not_found("session/request_permission")

    async def write_text_file(self, content, path, session_id, **kwargs):
        raise RequestError.method_not_found("fs/write_text_file")

    async def read_text_file(self, path, session_id, **kwargs):
        raise RequestError.method_not_found("fs/read_text_file")

    async def create_terminal(self, command, session_id, **kwargs):
        raise RequestError.method_not_found("terminal/create")

    async def terminal_output(self, session_id, terminal_id, **kwargs):
        raise RequestError.method_not_found("terminal/output")

    async def release_terminal(self, session_id, terminal_id, **kwargs):
        raise RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kwargs):
        raise RequestError.method_not_found("terminal/wait_for_exit")

    async def kill_terminal(self, session_id, terminal_id, **kwargs):
        raise RequestError.method_not_found("terminal/kill")

    async def ext_method(self, method, params):
        raise RequestError.method_not_found(method)

    async def ext_notification(self, method, params):
        pass


async def main():
    # Spawn the agent as a subprocess
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "examples/echo_agent.py",
        stdin=aio_subprocess.PIPE,
        stdout=aio_subprocess.PIPE,
    )

    client = SimpleClient()
    conn = connect_to_agent(client, proc.stdin, proc.stdout)

    # 1. Initialize
    await conn.initialize(
        protocol_version=PROTOCOL_VERSION,
        client_capabilities=ClientCapabilities(),
        client_info=Implementation(name="my-client", version="1.0.0"),
    )

    # 2. Create session
    session = await conn.new_session(mcp_servers=[], cwd=os.getcwd())
    print(f"Session: {session.session_id}")

    # 3. Send prompts
    await conn.prompt(session_id=session.session_id, prompt=[text_block("Hello from my client!")])

    proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
```

### 3.2 Client with File I/O and Permissions

A more capable client that supports agent file operations and permission requests:

```python
class CapableClient(Client):
    def __init__(self):
        self._files: dict[str, str] = {}  # In-memory file storage

    async def session_update(self, session_id, update, **kwargs) -> None:
        if isinstance(update, AgentMessageChunk):
            text = getattr(update.content, "text", str(update.content))
            print(f"Agent: {text}")

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        """Interactive permission handler — let user choose."""
        print(f"\n⚠ Agent requests permission: {tool_call.title}")
        for i, opt in enumerate(options):
            print(f"  [{i}] {opt.name} ({opt.kind})")

        choice = int(input("Select option: "))
        selected = options[choice]

        from acp.schema import AllowedOutcome
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=selected.option_id)
        )

    async def read_text_file(self, path, session_id, line=None, limit=None, **kwargs):
        """Read a file from the local filesystem."""
        with open(path) as f:
            content = f.read()
        return ReadTextFileResponse(content=content, path=path)

    async def write_text_file(self, content, path, session_id, **kwargs):
        """Write a file to the local filesystem."""
        with open(path, "w") as f:
            f.write(content)
        return WriteTextFileResponse()

    # Terminal methods - implement if your client supports terminal operations
    async def create_terminal(self, command, session_id, args=None, cwd=None, env=None, **kwargs):
        """Create a terminal and run a command."""
        import subprocess
        full_cmd = [command] + (args or [])
        proc = subprocess.Popen(full_cmd, cwd=cwd, capture_output=True, text=True)
        # In a real implementation, you'd track the process and return a terminal_id
        from acp.schema import CreateTerminalResponse
        return CreateTerminalResponse(terminal_id="term_001")

    # ... implement other terminal methods as needed
```

### 3.3 Using `spawn_agent_process` (Recommended)

The easiest way to connect to an agent:

```python
from acp import spawn_agent_process, PROTOCOL_VERSION, text_block

async def main():
    client = SimpleClient()

    async with spawn_agent_process(client, sys.executable, "examples/agent.py") as (conn, process):
        # Connection is established, agent process is running
        await conn.initialize(protocol_version=PROTOCOL_VERSION)
        session = await conn.new_session(mcp_servers=[], cwd=os.getcwd())

        # Interactive loop
        while True:
            user_input = input("> ")
            if not user_input:
                break
            await conn.prompt(session_id=session.session_id, prompt=[text_block(user_input)])

    # Context manager handles process cleanup automatically
```

### 3.4 Client Method Reference

| Method | When It's Called | What To Do |
|--------|-----------------|------------|
| `session_update` | Agent streams any update | Display to user (text, tool calls, plans, etc.) |
| `request_permission` | Agent needs user approval | Show options to user, return their choice |
| `read_text_file` | Agent wants to read a file | Read from filesystem and return content |
| `write_text_file` | Agent wants to write a file | Write to filesystem |
| `create_terminal` | Agent wants to run a command | Spawn process, return terminal ID |
| `terminal_output` | Agent wants command output | Return stdout/stderr of terminal |
| `wait_for_terminal_exit` | Agent waiting for command | Block until process exits |
| `release_terminal` | Agent done with terminal | Clean up process resources |
| `kill_terminal` | Agent wants to stop command | Kill the process |

---

## 4. Advanced Agent Patterns

### 4.1 Streaming Tool Calls

Show the client what your agent is doing in real time:

```python
from acp import (
    start_tool_call, start_read_tool_call, start_edit_tool_call,
    update_tool_call, tool_content, tool_diff_content, tool_terminal_ref,
    text_block, update_agent_message_text,
)

async def prompt(self, prompt, session_id, **kwargs):
    # 1. Start a read tool call
    read_start = start_read_tool_call("call_001", "Read main.py", path="/project/main.py")
    await self._conn.session_update(session_id, read_start)

    # 2. Actually read the file via the client
    file_content = await self._conn.read_text_file(path="/project/main.py", session_id=session_id)

    # 3. Mark the read as completed
    read_done = update_tool_call("call_001",
        status="completed",
        content=[tool_content(text_block(file_content.content))])
    await self._conn.session_update(session_id, read_done)

    # 4. Start an edit tool call
    edit_start = start_edit_tool_call("call_002", "Fix bug in main.py",
        path="/project/main.py", content="fixed code here...")
    await self._conn.session_update(session_id, edit_start)

    # 5. Write the fix
    await self._conn.write_text_file(
        content="fixed code here...", path="/project/main.py", session_id=session_id
    )

    # 6. Mark the edit as completed with a diff
    edit_done = update_tool_call("call_002",
        status="completed",
        content=[tool_diff_content("main.py", new_text="fixed code", old_text="buggy code")])
    await self._conn.session_update(session_id, edit_done)

    # 7. Send agent message
    await self._conn.session_update(session_id, update_agent_message_text("Bug fixed!"))
    return PromptResponse(stop_reason="end_turn")
```

### 4.2 Permission Flows

Request user approval before sensitive operations:

```python
from acp.schema import PermissionOption, AllowedOutcome

async def prompt(self, prompt, session_id, **kwargs):
    # Define permission options
    options = [
        PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
        PermissionOption(option_id="always", name="Always Allow", kind="allow_always"),
        PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
    ]

    # Create a tool call to show context
    tool_update = ToolCallUpdate(
        tool_call_id="call_005",
        title="Delete temp files",
        kind="delete",
    )

    # Request permission
    response = await self._conn.request_permission(
        options=options, session_id=session_id, tool_call=tool_update
    )

    if response.outcome.outcome == "selected":
        if response.outcome.option_id in ("allow", "always"):
            # Proceed with the operation
            await self._conn.session_update(session_id,
                update_agent_message_text("Deleting temp files..."))
        else:
            await self._conn.session_update(session_id,
                update_agent_message_text("Operation rejected by user."))
    elif response.outcome.outcome == "cancelled":
        return PromptResponse(stop_reason="cancelled")

    return PromptResponse(stop_reason="end_turn")
```

### 4.3 Execution Plans

Report multi-step plans with live status updates:

```python
from acp import update_plan, plan_entry

async def prompt(self, prompt, session_id, **kwargs):
    # Send initial plan
    await self._conn.session_update(session_id, update_plan([
        plan_entry("Analyze the codebase", priority="high", status="in_progress"),
        plan_entry("Identify the bug", priority="high", status="pending"),
        plan_entry("Write the fix", priority="medium", status="pending"),
        plan_entry("Run tests", priority="medium", status="pending"),
    ]))

    # ... do analysis ...

    # Update plan as you progress
    await self._conn.session_update(session_id, update_plan([
        plan_entry("Analyze the codebase", priority="high", status="completed"),
        plan_entry("Identify the bug", priority="high", status="completed"),
        plan_entry("Write the fix", priority="medium", status="in_progress"),
        plan_entry("Run tests", priority="medium", status="pending"),
    ]))

    # ... write fix ...

    # Final update — all done
    await self._conn.session_update(session_id, update_plan([
        plan_entry("Analyze the codebase", priority="high", status="completed"),
        plan_entry("Identify the bug", priority="high", status="completed"),
        plan_entry("Write the fix", priority="medium", status="completed"),
        plan_entry("Run tests", priority="medium", status="completed"),
    ]))

    return PromptResponse(stop_reason="end_turn")
```

### 4.4 Terminal Operations

Run commands on the client's machine:

```python
async def prompt(self, prompt, session_id, **kwargs):
    # Create a terminal and run tests
    terminal = await self._conn.create_terminal(
        command="python",
        args=["-m", "pytest", "tests/", "-v"],
        cwd="/home/user/project",
        session_id=session_id,
    )

    # Stream the tool call for visibility
    tc_start = start_tool_call("call_010", "Run pytest",
        kind="execute", status="in_progress",
        content=[tool_terminal_ref(terminal.terminal_id)])
    await self._conn.session_update(session_id, tc_start)

    # Wait for completion
    exit_info = await self._conn.wait_for_terminal_exit(
        session_id=session_id, terminal_id=terminal.terminal_id
    )

    # Get the output
    output = await self._conn.terminal_output(
        session_id=session_id, terminal_id=terminal.terminal_id
    )

    # Report results
    tc_done = update_tool_call("call_010",
        status="completed" if exit_info.exit_status and exit_info.exit_status.exit_code == 0 else "failed",
        content=[tool_content(text_block(output.output))])
    await self._conn.session_update(session_id, tc_done)

    # Release terminal resources
    await self._conn.release_terminal(session_id=session_id, terminal_id=terminal.terminal_id)

    return PromptResponse(stop_reason="end_turn")
```

### 4.5 Streaming Thoughts (Agent Reasoning)

Let users see what the agent is thinking:

```python
from acp import update_agent_thought_text

async def prompt(self, prompt, session_id, **kwargs):
    # Stream reasoning
    await self._conn.session_update(session_id,
        update_agent_thought_text("Let me analyze the error message..."))

    await self._conn.session_update(session_id,
        update_agent_thought_text("The stack trace points to line 42 in main.py..."))

    await self._conn.session_update(session_id,
        update_agent_thought_text("This is a null pointer — the variable was never initialized."))

    # Stream the actual response
    await self._conn.session_update(session_id,
        update_agent_message_text("I found the bug. The variable `user` is used before initialization on line 42."))

    return PromptResponse(stop_reason="end_turn")
```

### 4.6 Session Modes

Support different operating modes (e.g., Code vs Architect):

```python
from acp.schema import SessionModeState, SessionMode

class MultiModeAgent(Agent):
    def __init__(self):
        self._modes = SessionModeState(
            current_mode_id="code",
            available_modes=[
                SessionMode(id="code", name="Code", description="Write and edit code"),
                SessionMode(id="architect", name="Architect", description="Plan and design"),
                SessionMode(id="review", name="Review", description="Review code changes"),
            ],
        )
        self._session_modes: dict[str, str] = {}

    async def new_session(self, cwd, mcp_servers, **kwargs):
        session_id = uuid4().hex
        self._session_modes[session_id] = "code"
        return NewSessionResponse(session_id=session_id, modes=self._modes)

    async def set_session_mode(self, mode_id, session_id, **kwargs):
        self._session_modes[session_id] = mode_id
        return SetSessionModeResponse()

    async def prompt(self, prompt, session_id, **kwargs):
        current_mode = self._session_modes.get(session_id, "code")

        if current_mode == "code":
            # Write/edit code
            pass
        elif current_mode == "architect":
            # High-level planning only
            pass
        elif current_mode == "review":
            # Code review feedback
            pass

        return PromptResponse(stop_reason="end_turn")
```

### 4.7 Using `field_meta` for Custom Metadata

Attach arbitrary metadata to any content block or update:

```python
chunk = update_agent_message(text_block("Hello"))
chunk.field_meta = {"source": "my_agent", "confidence": 0.95}
chunk.content.field_meta = {"language": "en"}

await self._conn.session_update(session_id=session_id, update=chunk)
# Wire format includes: "_meta": {"source": "my_agent", "confidence": 0.95}
```

### 4.8 Extension Methods

Add custom RPC methods beyond the core protocol:

```python
# Agent side — handle custom client requests
async def ext_method(self, method: str, params: dict) -> dict:
    if method == "custom/get_agent_status":
        return {"active_sessions": len(self._sessions), "uptime": 3600}
    raise RequestError.method_not_found(method)

async def ext_notification(self, method: str, params: dict) -> None:
    if method == "custom/preferences_changed":
        self._preferences = params
```

---

## 5. Plugging Agent Frameworks into ACP

This is the most important section for AI engineers. Here's how to take **any** agent framework and expose it as an ACP agent.

### 5.1 The Universal Pattern

Regardless of your agent framework (LangChain, LangGraph, CrewAI, AutoGen, custom), the pattern is always the same:

```
┌─────────────────────────────────────────┐
│      YOUR AGENT FRAMEWORK               │
│  (LangGraph, CrewAI, AutoGen, custom)  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      ACP WRAPPER (your code)            │
│  - Subclass acp.Agent                   │
│  - Convert ACP inputs → framework       │
│  - Convert framework outputs → ACP      │
│  - Stream updates during processing     │
│  - Handle interrupts/permissions        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      ACP RUNTIME                        │
│  await run_agent(wrapper)               │
│  → stdio transport → any ACP client     │
└─────────────────────────────────────────┘
```

### 5.2 Step-by-Step Integration

**Step 1: Create your ACP wrapper class**

```python
from acp import Agent as ACPAgent, run_agent
from acp.schema import AgentCapabilities, PromptCapabilities

class MyFrameworkACPAgent(ACPAgent):
    def __init__(self, framework_agent):
        self._framework_agent = framework_agent
        self._conn = None

    def on_connect(self, conn):
        self._conn = conn

    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(
                prompt_capabilities=PromptCapabilities(image=True)
            ),
        )

    async def new_session(self, cwd, mcp_servers=None, **kwargs):
        session_id = uuid4().hex
        # Initialize your framework's session state here
        return NewSessionResponse(session_id=session_id)
```

**Step 2: Convert ACP content blocks to your framework's format**

```python
def _convert_acp_to_framework(self, prompt):
    """Convert ACP content blocks to your framework's message format."""
    messages = []
    for block in prompt:
        if isinstance(block, TextContentBlock):
            messages.append({"role": "user", "content": block.text})
        elif isinstance(block, ImageContentBlock):
            data_uri = f"data:{block.mime_type};base64,{block.data}"
            messages.append({"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_uri}}
            ]})
        elif isinstance(block, ResourceContentBlock):
            messages.append({"role": "user", "content": f"[File: {block.name}] {block.uri}"})
        elif isinstance(block, EmbeddedResourceContentBlock):
            if hasattr(block.resource, "text"):
                messages.append({"role": "user", "content": block.resource.text})
    return messages
```

**Step 3: Stream framework output as ACP updates**

```python
async def prompt(self, prompt, session_id, **kwargs):
    messages = self._convert_acp_to_framework(prompt)

    # Run your framework and stream results
    async for event in self._framework_agent.astream(messages):
        if event.type == "text":
            await self._conn.session_update(session_id,
                update_agent_message_text(event.text))
        elif event.type == "tool_call":
            await self._conn.session_update(session_id,
                start_tool_call(event.id, event.name, kind=self._map_tool_kind(event)))
        elif event.type == "tool_result":
            await self._conn.session_update(session_id,
                update_tool_call(event.id, status="completed",
                    content=[tool_content(text_block(str(event.result)))]))

    return PromptResponse(stop_reason="end_turn")
```

**Step 4: Launch**

```python
async def main():
    my_agent = create_my_framework_agent(...)  # Your framework's agent
    acp_wrapper = MyFrameworkACPAgent(my_agent)
    await run_agent(acp_wrapper)

asyncio.run(main())
```

### 5.3 DeepAgent + LangGraph Integration (Real-World Example)

The `deepagents-acp/` folder in this repository shows a complete, production-grade integration of DeepAgent (a LangChain/LangGraph-based framework) with ACP. Here's how it works:

#### Architecture

```
┌─────────────────────────────────────────┐
│  LangGraph CompiledStateGraph           │
│  (create_deep_agent with tools,         │
│   checkpointer, interrupts, middleware) │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  AgentServerACP (extends acp.Agent)     │
│  ● initialize() → report capabilities  │
│  ● new_session() → create session       │
│  ● set_session_mode() → reset agent     │
│  ● prompt() → convert blocks,           │
│    astream messages+updates,            │
│    handle tool calls & interrupts       │
│  ● cancel() → stop execution           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  ACP Protocol (stdio)                   │
│  → Zed / VS Code / any ACP client      │
└─────────────────────────────────────────┘
```

#### Key Features of the DeepAgent Integration

**1. Agent Factory Pattern** — Creates agents dynamically per session with mode-specific config:

```python
class AgentServerACP(ACPAgent):
    def __init__(self, agent, *, modes=None):
        # agent can be:
        #   - A compiled LangGraph (static)
        #   - A callable(AgentSessionContext) -> CompiledStateGraph (factory)
        self._agent_factory = agent
        self._modes = modes
```

**2. Session Mode → Interrupt Config** — Different modes control which tools need approval:

```python
mode_to_interrupt = {
    "ask_before_edits": {
        "edit_file": {"allowed_decisions": ["approve", "reject"]},
        "write_file": {"allowed_decisions": ["approve", "reject"]},
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "reject"]},
    },
    "accept_edits": {
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "reject"]},
    },
    "accept_everything": {},  # No interrupts
}
```

**3. Content Block Conversion** (ACP → LangChain):

```python
# TextContentBlock → LangChain text content
[{"type": "text", "text": block.text}]

# ImageContentBlock → LangChain image_url
[{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]

# ResourceContentBlock → descriptive text
[{"type": "text", "text": "[Resource: main.py\nURI: file://main.py]"}]

# EmbeddedResourceContentBlock → inline text or blob reference
[{"type": "text", "text": "[Embedded text/x-python resource: ...code..."}]
```

**4. Tool Call Streaming** — Chunks arrive incrementally from LangGraph and are accumulated:

```python
async def prompt(self, prompt, session_id, **kwargs):
    # Convert ACP content blocks to LangChain messages
    content_blocks = []
    for block in prompt:
        if isinstance(block, TextContentBlock):
            content_blocks.extend(convert_text_block_to_content_blocks(block))
        elif isinstance(block, ImageContentBlock):
            content_blocks.extend(convert_image_block_to_content_blocks(block))
        # ... handle all content types

    # Stream from LangGraph
    async for stream_mode, chunk in self._agent.astream(
        {"messages": [{"role": "user", "content": content_blocks}]},
        stream_mode=["messages", "updates"],
    ):
        if stream_mode == "messages":
            # Process text chunks and tool call chunks
            message_chunk, metadata = chunk
            if hasattr(message_chunk, "content") and message_chunk.content:
                await self._conn.session_update(session_id,
                    update_agent_message(text_block(message_chunk.content)))
            if hasattr(message_chunk, "tool_call_chunks"):
                await self._process_tool_call_chunks(session_id, message_chunk, ...)
        elif stream_mode == "updates":
            # Handle tool results, plan updates, interrupts
            ...
```

**5. Human-in-the-Loop (HITL) Permissions** — When LangGraph interrupts, ACP requests permission:

```python
async def _handle_interrupts(self, session_id, snapshot):
    """Handle LangGraph interrupts by requesting ACP permissions."""
    for task in snapshot.tasks:
        for interrupt in task.interrupts:
            tool_name = interrupt.value.get("tool_name", "unknown")

            # Auto-approve if this command type was previously whitelisted
            if self._is_auto_approved(session_id, tool_name, interrupt):
                return Command(resume=[{"type": "approve"}])

            # Build permission options
            options = [
                PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
                PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
            ]

            # For execute commands, add "Always allow {command}" option
            if tool_name == "execute":
                cmd_type = extract_command_types(command_str)[0]
                options.append(PermissionOption(
                    option_id=f"always_{cmd_type}",
                    name=f"Always allow '{cmd_type}'",
                    kind="allow_always"
                ))

            # Send ACP permission request to client
            response = await self._conn.request_permission(
                options=options,
                session_id=session_id,
                tool_call=ToolCallUpdate(tool_call_id=tool_call_id, title=title),
            )

            if response.outcome.outcome == "selected":
                option_id = response.outcome.option_id
                if option_id.startswith("always_"):
                    # Whitelist this command type for the session
                    self._allowed_command_types[session_id].add((tool_name, cmd_type))
                if "approve" in option_id or option_id.startswith("always_"):
                    return Command(resume=[{"type": "approve"}])
                else:
                    return Command(resume=[{"type": "reject"}])
```

**6. Command Security Parsing** — Prevents over-permissioning of shell commands:

```python
from deepagents_acp.utils import extract_command_types

# Different signatures for different security contexts
extract_command_types("npm install")           # → ["npm install"]
extract_command_types("npm run build")         # → ["npm run build"]
extract_command_types("python -m pytest")      # → ["python -m pytest"]
extract_command_types("python -m pip install") # → ["python -m pip"]
extract_command_types("python -c 'code'")      # → ["python -c"]
extract_command_types("cd x && npm install")   # → ["cd", "npm install"]
extract_command_types("ls | grep foo")         # → ["ls", "grep"]

# Approving "npm install" does NOT auto-approve "npm run arbitrary_script"
```

**7. LocalContext Middleware** — Auto-detects the development environment:

```python
# Runs a shell script that detects:
# - CWD, project language, monorepo layout
# - Package manager (uv/poetry/pip/npm/yarn/pnpm)
# - Python/Node versions, git branch, uncommitted changes
# - Test command, file listing, directory tree, Makefile

class LocalContextMiddleware:
    async def before_agent(self, state, config):
        """Inject development context into the system prompt."""
        context = await self._detect_local_context()
        # Modifies system prompt to include environment awareness
```

#### Running the DeepAgent ACP Agent

```bash
# From the deepagents-acp directory
./run_demo_agent.sh

# Or manually
uv run --project deepagents-acp python deepagents-acp/examples/demo_agent.py
```

#### Creating Your Own DeepAgent + ACP Integration

```python
import asyncio
from acp import run_agent as run_acp_agent
from acp.schema import SessionMode, SessionModeState
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, LocalShellBackend, StateBackend
from langgraph.checkpoint.memory import MemorySaver
from deepagents_acp.server import AgentServerACP, AgentSessionContext

def build_agent(context: AgentSessionContext):
    """Create a DeepAgent configured for the session context."""
    return create_deep_agent(
        checkpointer=MemorySaver(),
        backend=CompositeBackend(default=LocalShellBackend(root_dir=context.cwd)),
        interrupt_on={"execute": {"allowed_decisions": ["approve", "reject"]}},
    )

modes = SessionModeState(
    current_mode_id="accept_edits",
    available_modes=[
        SessionMode(id="accept_edits", name="Accept Edits"),
        SessionMode(id="ask_before_edits", name="Ask Before Edits"),
    ],
)

acp_agent = AgentServerACP(agent=build_agent, modes=modes)
asyncio.run(run_acp_agent(acp_agent))
```

### 5.4 Template: Integrating Any Framework

Here's a minimal, copy-paste template for wrapping **any** agent framework:

```python
"""Template: Wrap any agent framework as an ACP agent."""
import asyncio
from typing import Any
from uuid import uuid4

from acp import (
    Agent as ACPAgent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    text_block,
    update_agent_message,
    update_agent_message_text,
    start_tool_call,
    update_tool_call,
    tool_content,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    ClientCapabilities,
    Implementation,
    HttpMcpServer,
    McpServerStdio,
    SseMcpServer,
    TextContentBlock,
    ImageContentBlock,
    AudioContentBlock,
    ResourceContentBlock,
    EmbeddedResourceContentBlock,
)


class FrameworkACPAgent(ACPAgent):
    """Replace 'Framework' with your framework name."""

    _conn: Client

    def __init__(self, agent_factory):
        """
        agent_factory: a callable or object that creates/is your framework's agent.
        """
        self._agent_factory = agent_factory
        self._sessions: dict[str, Any] = {}

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(name="framework-agent", version="1.0.0"),
        )

    async def new_session(self, cwd, mcp_servers=None, **kwargs):
        session_id = uuid4().hex
        # TODO: Initialize your framework's session/thread state
        self._sessions[session_id] = {"cwd": cwd}
        return NewSessionResponse(session_id=session_id)

    async def prompt(self, prompt, session_id, **kwargs):
        # ─── STEP 1: Convert ACP content blocks to framework input ───
        user_input = ""
        for block in prompt:
            if isinstance(block, TextContentBlock):
                user_input += block.text
            elif isinstance(block, ImageContentBlock):
                pass  # TODO: Handle images
            elif isinstance(block, ResourceContentBlock):
                user_input += f"\n[File: {block.name}]"
            elif isinstance(block, EmbeddedResourceContentBlock):
                if hasattr(block.resource, "text"):
                    user_input += f"\n{block.resource.text}"

        # ─── STEP 2: Run your framework ───
        # Replace this with your actual framework invocation:
        #
        # For LangChain:
        #   result = await chain.ainvoke({"input": user_input})
        #
        # For CrewAI:
        #   result = await crew.kickoff_async(inputs={"query": user_input})
        #
        # For AutoGen:
        #   result = await agent.run(task=user_input)
        #
        # For streaming frameworks, iterate over chunks:
        #   async for chunk in framework.astream(input):
        #       await self._conn.session_update(session_id,
        #           update_agent_message_text(chunk.text))

        result_text = f"Echo: {user_input}"  # Placeholder

        # ─── STEP 3: Stream result as ACP updates ───
        await self._conn.session_update(session_id, update_agent_message_text(result_text))

        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id, **kwargs):
        # TODO: Cancel your framework's execution
        pass


async def main():
    # TODO: Create your framework's agent
    my_agent = None  # Replace with your agent creation

    acp_wrapper = FrameworkACPAgent(agent_factory=my_agent)
    await run_agent(acp_wrapper)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Wire Format & Protocol Details

### 6.1 JSON-RPC 2.0 Envelope

Every ACP message is a single line of JSON (newline-delimited):

```
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}\n
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1}}\n
{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"abc","update":{...}}}\n
```

- **Requests**: Have `id` + `method` + `params` → expect a response with matching `id`
- **Responses**: Have `id` + `result` (success) or `error` (failure)
- **Notifications**: Have `method` + `params` but NO `id` → no response

### 6.2 Golden Wire Format Examples

These examples are from the SDK's golden test fixtures (`tests/golden/`), which define the exact expected wire format:

#### Content Blocks

```json
// Text
{"type": "text", "text": "Hello, world!"}

// Image
{"type": "image", "mimeType": "image/png", "data": "iVBORw0KGgo..."}

// Audio
{"type": "audio", "mimeType": "audio/wav", "data": "UklGR..."}

// Resource Link (reference to a file)
{"type": "resource_link", "uri": "file:///project/main.py", "name": "main.py", "mimeType": "text/x-python", "size": 12345}

// Embedded Text Resource (inline file content)
{"type": "resource", "resource": {"uri": "file:///project/main.py", "mimeType": "text/x-python", "text": "def main():\n    pass"}}

// Embedded Blob Resource (inline binary)
{"type": "resource", "resource": {"uri": "file:///data.pdf", "mimeType": "application/pdf", "blob": "JVBERi0..."}}
```

#### Session Updates

```json
// Agent message
{"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Here's the fix..."}}

// Agent thought
{"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "I need to check..."}}

// Tool call start
{"sessionUpdate": "tool_call", "toolCallId": "call_001", "title": "Read main.py", "kind": "read", "status": "pending", "locations": [{"path": "/project/main.py"}]}

// Tool call update with diff content
{"sessionUpdate": "tool_call_update", "toolCallId": "call_001", "status": "completed", "content": [{"type": "diff", "path": "main.py", "oldText": "buggy", "newText": "fixed"}]}

// Plan
{"sessionUpdate": "plan", "entries": [{"content": "Read file", "priority": "high", "status": "completed"}, {"content": "Fix bug", "priority": "high", "status": "in_progress"}]}

// Cancel notification
{"sessionId": "abc123"}
```

#### Permission Flow

```json
// Request (agent → client)
{"sessionId": "abc", "toolCall": {"toolCallId": "c1"}, "options": [{"optionId": "allow-once", "name": "Allow", "kind": "allow_once"}, {"optionId": "reject", "name": "Reject", "kind": "reject_once"}]}

// Response — selected
{"outcome": "selected", "optionId": "allow-once"}

// Response — cancelled
{"outcome": "cancelled"}
```

### 6.3 Message Flow Diagrams

**Standard Prompt Flow:**
```
Client                              Agent
  │                                   │
  │── initialize ────────────────────►│
  │◄──────────────── response ────────│
  │                                   │
  │── session/new ───────────────────►│
  │◄──────────────── response ────────│
  │                                   │
  │── session/prompt ────────────────►│
  │                                   │
  │◄─── session/update (thought) ─────│  ← notification
  │◄─── session/update (tool_call) ───│  ← notification
  │◄─── session/update (message) ─────│  ← notification
  │◄─── session/update (message) ─────│  ← notification
  │                                   │
  │◄──────────────── response ────────│  ← PromptResponse{stop_reason: "end_turn"}
  │                                   │
```

**Permission Flow (during prompt):**
```
Client                              Agent
  │── session/prompt ────────────────►│
  │                                   │
  │◄─── session/update (tool_call) ───│
  │                                   │
  │◄─── request_permission ───────────│  ← Agent asks for approval
  │                                   │
  │── permission response ───────────►│  ← User approves/rejects
  │                                   │
  │◄─── session/update (tool_done) ───│  ← Tool completes
  │◄─── session/update (message) ─────│
  │                                   │
  │◄──────────────── response ────────│
```

**Cancel Flow:**
```
Client                              Agent
  │── session/prompt ────────────────►│
  │                                   │
  │◄─── session/update (message) ─────│
  │                                   │
  │── session/cancel ────────────────►│  ← notification (no response)
  │                                   │
  │◄──────────────── response ────────│  ← PromptResponse{stop_reason: "cancelled"}
```

---

## 7. Testing & Development

### 7.1 Development Commands

```bash
# Install development environment
make install

# Run all checks (format, lint, types, dependency validation)
make check

# Run test suite
make test

# Or manually with pytest
uv run python -m pytest

# Run with Gemini CLI tests (optional)
ACP_ENABLE_GEMINI_TESTS=1 make test
ACP_GEMINI_BIN=/path/to/gemini ACP_ENABLE_GEMINI_TESTS=1 make test
```

### 7.2 Testing Your Own Agent

Use the SDK's testing patterns:

```python
import pytest
from acp import connect_to_agent, PROTOCOL_VERSION, text_block
from acp.core import AgentSideConnection, ClientSideConnection

@pytest.mark.asyncio
async def test_my_agent():
    """Test your agent using in-process loopback."""
    import asyncio

    # Create paired streams (in-process, no subprocess needed)
    agent_to_client = asyncio.StreamReader()
    client_to_agent = asyncio.StreamReader()

    agent_writer = asyncio.StreamWriter(...)  # Wire these together
    client_writer = asyncio.StreamWriter(...)

    # Or use the SDK's TCP loopback helper from conftest.py:
    # See tests/conftest.py for the _Server fixture pattern
```

The simplest approach for integration testing is `spawn_agent_process`:

```python
import pytest
from acp import spawn_agent_process, PROTOCOL_VERSION, text_block
import sys

@pytest.mark.asyncio
async def test_my_agent_integration():
    """Full integration test via subprocess."""
    client = MyTestClient()  # A client that records updates

    async with spawn_agent_process(
        client, sys.executable, "my_agent.py"
    ) as (conn, process):
        # Initialize
        resp = await conn.initialize(protocol_version=PROTOCOL_VERSION)
        assert resp.protocol_version == PROTOCOL_VERSION

        # Create session
        session = await conn.new_session(cwd="/tmp", mcp_servers=[])
        assert session.session_id

        # Send prompt
        result = await conn.prompt(
            session_id=session.session_id,
            prompt=[text_block("Hello!")],
        )
        assert result.stop_reason == "end_turn"

        # Check what the agent sent to the client
        assert len(client.updates) > 0
```

### 7.3 Golden File Testing

The SDK uses golden files to validate wire format compatibility. If you modify the schema, update golden fixtures:

```python
# tests/test_golden.py pattern
def test_json_golden_roundtrip(name, model_cls):
    """Load golden JSON, parse to model, serialize back — must be identical."""
    raw = load_golden(name)
    model = model_cls.model_validate(raw)
    assert dump_model(model) == raw

def test_helpers_match_golden(name, builder):
    """Verify helper functions produce exact golden output."""
    raw = load_golden(name)
    model = builder()
    assert dump_model(model) == raw
```

### 7.4 SDK Test Coverage Areas

| Test File | What It Tests |
|-----------|--------------|
| `test_rpc.py` | Full bidirectional protocol flows (init, prompt, files, terminals, permissions, extensions) |
| `test_golden.py` | Wire format compatibility (37 golden fixtures) |
| `test_compatibility.py` | Legacy API backward compatibility (camelCase → snake_case) |
| `test_unstable.py` | Experimental features (list_sessions, fork, resume, set_model) |
| `test_utils.py` | Utility functions (serialization, case conversion) |
| `contrib/test_contrib_permissions.py` | PermissionBroker |
| `contrib/test_contrib_session_state.py` | SessionAccumulator |
| `contrib/test_contrib_tool_calls.py` | ToolCallTracker |
| `real_user/test_permission_flow.py` | Permission requests during prompts |
| `real_user/test_cancel_prompt_flow.py` | Cancel interrupts long-running prompts |
| `real_user/test_mcp_servers_optional.py` | Optional MCP server parameter |
| `real_user/test_stdio_limits.py` | Buffer size limits (50MB default) |

---

## 8. Migration & Versioning

### 8.1 Schema Versioning

The SDK tracks the upstream ACP JSON Schema version. Current version: `refs/tags/v0.10.8`.

To regenerate code from a new schema version:

```bash
ACP_SCHEMA_VERSION=v0.10.8 make gen-all
```

This downloads the new schema and regenerates:
- `src/acp/schema.py` (Pydantic models)
- `src/acp/meta.py` (method constants)
- Function signatures throughout the SDK

### 8.2 Migrating from 0.6 → 0.7

**Change 1: Snake_case fields**

```python
# Before (0.6)
PromptResponse(stopReason="end_turn")
params.sessionId

# After (0.7+)
PromptResponse(stop_reason="end_turn")
params.session_id
```

Both forms still work at runtime due to the camelCase compatibility layer, but snake_case is canonical.

**Change 2: Simplified entry points**

```python
# Before (0.6)
conn = AgentSideConnection(lambda conn: Agent(), writer, reader)
await asyncio.Event().wait()

# After (0.7+)
await run_agent(MyAgent())
```

**Change 3: Explicit parameters instead of request objects**

```python
# Before (0.6)
async def prompt(self, params: PromptRequest) -> PromptResponse:
    text = params.prompt[0].text

# After (0.7+)
async def prompt(self, prompt, session_id, **kwargs) -> PromptResponse:
    text = prompt[0].text
```

### 8.3 Migrating from 0.7 → 0.8

**Change 1: Schema bump to 0.10.8**

Regenerate with:
```bash
ACP_SCHEMA_VERSION=v0.10.8 make gen-all
```

New type: `SessionInfoUpdate` added to the session update union.

**Change 2: TerminalHandle removed**

```python
# Before (0.7)
handle = await conn.create_terminal(...)
await conn.terminal_output(terminal_id=handle.id, ...)

# After (0.8+)
resp = await conn.create_terminal(...)
await conn.terminal_output(terminal_id=resp.terminal_id, ...)
```

**Change 3: Larger stdio buffer (50MB default)**

The default buffer was increased from 64KB to 50MB for multimodal use cases. Customize if needed:

```python
await run_agent(agent, stdio_buffer_limit_bytes=2 * 1024 * 1024)  # 2MB
```

---

## Quick Reference Card

### Agent Side — Most Common Operations

```python
# Start the agent
await run_agent(my_agent)

# Stream text to client
await self._conn.session_update(session_id, update_agent_message_text("Hello!"))

# Stream thought to client
await self._conn.session_update(session_id, update_agent_thought_text("Thinking..."))

# Start a tool call
await self._conn.session_update(session_id, start_tool_call("id", "Title", kind="read"))

# Complete a tool call
await self._conn.session_update(session_id, update_tool_call("id", status="completed"))

# Update execution plan
await self._conn.session_update(session_id, update_plan([plan_entry("Step 1", status="completed")]))

# Read a file from client
content = await self._conn.read_text_file(path="file.py", session_id=session_id)

# Write a file to client
await self._conn.write_text_file(content="code", path="file.py", session_id=session_id)

# Request permission
resp = await self._conn.request_permission(options=[...], session_id=sid, tool_call=tc)

# Run a terminal command
term = await self._conn.create_terminal(command="python", args=["-m", "pytest"], session_id=sid)
output = await self._conn.terminal_output(session_id=sid, terminal_id=term.terminal_id)
```

### Client Side — Most Common Operations

```python
# Connect to agent
conn = connect_to_agent(my_client, stdin, stdout)

# Or spawn agent as subprocess
async with spawn_agent_process(client, "python", "agent.py") as (conn, proc):
    ...

# Initialize
await conn.initialize(protocol_version=PROTOCOL_VERSION)

# Create session
session = await conn.new_session(cwd="/project", mcp_servers=[])

# Send prompt
result = await conn.prompt(session_id=session.session_id, prompt=[text_block("Hello")])

# Cancel
await conn.cancel(session_id=session.session_id)

# Change mode
await conn.set_session_mode(session_id=session.session_id, mode_id="architect")
```

---

> **Companion document:** See `ACP_COMPLETE_GUIDE.md` for the full reference on every ACP component, data type, and protocol message.
