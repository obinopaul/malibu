from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from vibe.core.config.harness_files import get_harness_files_manager
from vibe.core.deepagent.adapters import (
    LANGCHAIN_AVAILABLE,
    VibeChatModel,
    build_langchain_tools,
    langchain_messages_to_vibe,
    vibe_messages_to_langchain,
)
from vibe.core.llm.format import APIToolFormatHandler
from vibe.core.logger import logger
from vibe.core.system_prompt import get_universal_system_prompt
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    CompactEndEvent,
    CompactStartEvent,
    LLMMessage,
    LLMUsage,
    ReasoningEvent,
    Role,
    ToolCallEvent,
    UserMessageEvent,
)

if TYPE_CHECKING:
    from vibe.core.agent_loop import AgentLoop

try:
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.graph import BASE_AGENT_PROMPT
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from deepagents.middleware.skills import SkillsMiddleware
    from deepagents.middleware.summarization import create_summarization_middleware
    from langchain.agents import create_agent
    from langgraph.checkpoint.memory import InMemorySaver

    DEEPAGENT_AVAILABLE = True
except ModuleNotFoundError:
    DEEPAGENT_AVAILABLE = False


class DeepAgentDependencyError(RuntimeError):
    """Raised when the DeepAgent runtime is requested without its dependencies."""


@dataclass
class _StreamState:
    emitted_tool_call_ids: set[str] = field(default_factory=set)
    tool_call_buffers: dict[str | int, dict[str, Any]] = field(default_factory=dict)
    assistant_message_ids: dict[str, str] = field(default_factory=dict)
    summarization_active: bool = False
    summary_tool_call_id: str | None = None


@dataclass(frozen=True)
class _SkillSourceMount:
    path: Path
    source_kind: str
    skill_names: tuple[str, ...]

    @property
    def source(self) -> str:
        return str(self.path)


@dataclass(frozen=True)
class _RuntimeContract:
    orchestrator: str
    model_adapter: str
    tool_adapter: str
    backend: str
    checkpointer: str
    thread_id_source: str
    middleware: tuple[str, ...]
    skill_mounts: tuple[_SkillSourceMount, ...]


@dataclass(frozen=True)
class _RuntimeSpec:
    model: VibeChatModel
    backend: Any
    tools: list[Any]
    middleware: list[Any]
    checkpointer: Any
    system_prompt: str
    contract: _RuntimeContract


class DeepAgentRuntime:
    """Bridge AgentLoop to a LangChain agent with selected DeepAgent middleware.

    Contract ownership is explicit:
    - Vibe owns providers, tool permissions, session logging, and event translation.
    - LangChain owns the agent loop and thread-scoped checkpointed execution.
    - DeepAgent contributes focused middleware for skills, summarization, and
      tool-call patching.
    """

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop
        self._agent: Any = None
        self._checkpointer: Any = None
        self._runtime_contract: _RuntimeContract | None = None
        self._side_event_queue: asyncio.Queue[BaseEvent] | None = None
        self._active_tool_calls = 0

    @classmethod
    def is_supported(cls) -> bool:
        return DEEPAGENT_AVAILABLE and LANGCHAIN_AVAILABLE

    @property
    def runtime_contract(self) -> _RuntimeContract | None:
        return self._runtime_contract

    def invalidate(self) -> None:
        self._agent = None
        self._checkpointer = None
        self._runtime_contract = None

    async def clear_state(self) -> None:
        self.invalidate()

    async def act(self, msg: str) -> AsyncGenerator[BaseEvent]:
        await self._ensure_agent()

        user_message = LLMMessage(role=Role.user, content=msg)
        self._loop.messages.append(user_message)
        self._loop.stats.steps += 1
        self._loop._current_user_message_id = user_message.message_id

        if user_message.message_id is None:
            msg = "User message must have a message_id"
            raise RuntimeError(msg)

        yield UserMessageEvent(content=msg, message_id=user_message.message_id)

        async for event in self._stream_turn(msg):
            yield event

        await self._sync_messages_from_state()
        await self._sync_context_tokens()

    async def _ensure_agent(self) -> None:
        if self._agent is not None:
            return
        if not self.is_supported():
            msg = (
                "DeepAgent runtime requires the 'deepagents', 'langchain', and "
                "'langgraph' packages to be installed."
            )
            raise DeepAgentDependencyError(msg)

        spec = self._build_runtime_spec()
        self._runtime_contract = spec.contract
        self._log_runtime_contract(spec.contract)
        self._agent = self._create_agent_from_spec(spec)

        if len(self._loop.messages) > 1:
            await self._hydrate_agent_state()

    def _build_runtime_spec(self) -> _RuntimeSpec:
        checkpointer = self._build_checkpointer()
        model = VibeChatModel(loop=self._loop)
        backend = self._build_backend()
        skill_mounts = self._build_skill_mounts()
        tools = self._build_tools()
        middleware = self._build_middleware(
            model=model, backend=backend, skill_mounts=skill_mounts
        )
        return _RuntimeSpec(
            model=model,
            backend=backend,
            tools=tools,
            middleware=middleware,
            checkpointer=checkpointer,
            system_prompt=self._build_system_prompt(),
            contract=_RuntimeContract(
                orchestrator="langchain.create_agent",
                model_adapter=type(model).__name__,
                tool_adapter="build_langchain_tools",
                backend=type(backend).__name__,
                checkpointer=type(checkpointer).__name__,
                thread_id_source="AgentLoop.conversation_id",
                middleware=tuple(type(item).__name__ for item in middleware),
                skill_mounts=tuple(skill_mounts),
            ),
        )

    def _build_checkpointer(self) -> Any:
        if self._checkpointer is None:
            self._checkpointer = InMemorySaver()
        return self._checkpointer

    def _build_backend(self) -> Any:
        return FilesystemBackend(virtual_mode=False)

    def _build_tools(self) -> list[Any]:
        return build_langchain_tools(
            self._loop,
            emit_event=self._emit_side_event,
            on_tool_started=self._on_tool_started,
            on_tool_finished=self._on_tool_finished,
        )

    def _build_middleware(
        self,
        *,
        model: VibeChatModel,
        backend: Any,
        skill_mounts: list[_SkillSourceMount],
    ) -> list[Any]:
        middleware: list[Any] = [
            create_summarization_middleware(model, backend),
            PatchToolCallsMiddleware(),
        ]
        if skill_sources := self._build_skill_sources(skill_mounts):
            middleware.insert(0, SkillsMiddleware(backend=backend, sources=skill_sources))
        return middleware

    def _build_skill_mounts(self) -> list[_SkillSourceMount]:
        skills_by_dir: dict[Path, set[str]] = {}
        for skill in self._loop.skill_manager.available_skills.values():
            source_dir = skill.skill_dir.parent.resolve()
            skills_by_dir.setdefault(source_dir, set()).add(skill.name)

        return [
            _SkillSourceMount(
                path=path,
                source_kind=self._classify_skill_source(path),
                skill_names=tuple(sorted(skill_names)),
            )
            for path, skill_names in sorted(skills_by_dir.items(), key=lambda item: str(item[0]))
        ]

    @staticmethod
    def _build_skill_sources(skill_mounts: list[_SkillSourceMount]) -> list[str]:
        return [mount.source for mount in skill_mounts]

    def _classify_skill_source(self, skill_dir: Path) -> str:
        resolved_skill_dir = skill_dir.resolve()
        configured_paths = {
            path.resolve() for path in self._loop.config.skill_paths if path.is_dir()
        }
        if resolved_skill_dir in configured_paths:
            return "config-skill-path"

        manager = get_harness_files_manager()
        project_paths = {path.resolve() for path in manager.project_skills_dirs}
        user_paths = {path.resolve() for path in manager.user_skills_dirs}

        if resolved_skill_dir in project_paths:
            return (
                "project-agents-skills"
                if resolved_skill_dir.parts[-2:] == (".agents", "skills")
                else "project-vibe-skills"
            )
        if resolved_skill_dir in user_paths:
            return "user-skill-path"
        return "discovered-skill-path"

    def _create_agent_from_spec(self, spec: _RuntimeSpec) -> Any:
        return create_agent(
            spec.model,
            system_prompt=spec.system_prompt,
            tools=spec.tools,
            middleware=spec.middleware,
            checkpointer=spec.checkpointer,
            name=str(self._loop.agent_profile.name),
        ).with_config({
            "recursion_limit": 1000,
            "metadata": {"ls_integration": "deepagents"},
        })

    def _log_runtime_contract(self, contract: _RuntimeContract) -> None:
        logger.info(
            "Configured DeepAgent runtime orchestrator=%s model_adapter=%s tool_adapter=%s backend=%s checkpointer=%s thread_id_source=%s middleware=%s",
            contract.orchestrator,
            contract.model_adapter,
            contract.tool_adapter,
            contract.backend,
            contract.checkpointer,
            contract.thread_id_source,
            ", ".join(contract.middleware) or "<none>",
        )
        for mount in contract.skill_mounts:
            logger.info(
                "Mounted DeepAgent skill source kind=%s path=%s skills=%s",
                mount.source_kind,
                mount.path,
                ", ".join(mount.skill_names),
            )

    def _build_system_prompt(self) -> str:
        system_prompt = get_universal_system_prompt(
            self._loop.tool_manager,
            self._loop.config,
            self._loop.skill_manager,
            self._loop.agent_manager,
        ).strip()
        if not system_prompt:
            return BASE_AGENT_PROMPT
        return f"{system_prompt}\n\n{BASE_AGENT_PROMPT}"

    async def _hydrate_agent_state(self) -> None:
        if self._agent is None:
            return
        history = self._to_langchain_history(self._loop.messages[1:])
        if not history:
            return
        await self._agent.aupdate_state(
            self._build_runnable_config(), {"messages": history}
        )

    async def _stream_turn(self, msg: str) -> AsyncGenerator[BaseEvent]:
        if self._agent is None:
            return

        state = _StreamState()
        stream = self._agent.astream(
            {"messages": [{"role": "user", "content": msg}]},
            stream_mode=["messages", "updates"],
            subgraphs=True,
            config=self._build_runnable_config(),
            durability="exit",
        )
        iterator = stream.__aiter__()
        self._side_event_queue = asyncio.Queue()

        stream_task: asyncio.Task[Any] | None = asyncio.create_task(anext(iterator))
        queue_task: asyncio.Task[Any] | None = asyncio.create_task(
            self._side_event_queue.get()
        )
        start_time = time.perf_counter()
        total_usage = LLMUsage()

        try:
            while True:
                if (
                    stream_task is None
                    and self._active_tool_calls == 0
                    and (
                        self._side_event_queue is None or self._side_event_queue.empty()
                    )
                ):
                    break

                pending = {
                    task for task in (stream_task, queue_task) if task is not None
                }
                if not pending:
                    break

                done, _ = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                if queue_task in done:
                    queued_event = queue_task.result()
                    yield queued_event
                    queue_task = (
                        asyncio.create_task(self._side_event_queue.get())
                        if self._side_event_queue is not None
                        else None
                    )

                if stream_task not in done:
                    if stream_task is None and self._active_tool_calls == 0:
                        break
                    continue

                try:
                    chunk = stream_task.result()
                except StopAsyncIteration:
                    stream_task = None
                    if self._active_tool_calls == 0 and (
                        self._side_event_queue is None or self._side_event_queue.empty()
                    ):
                        break
                    continue

                async for event, usage in self._process_stream_chunk(chunk, state):
                    if usage is not None:
                        total_usage += usage
                    yield event

                stream_task = asyncio.create_task(anext(iterator))

            if self._side_event_queue is not None:
                while not self._side_event_queue.empty():
                    yield await self._side_event_queue.get()
        finally:
            elapsed = time.perf_counter() - start_time
            self._side_event_queue = None
            for task in (stream_task, queue_task):
                if task is not None and not task.done():
                    task.cancel()
            if total_usage.prompt_tokens or total_usage.completion_tokens:
                self._loop._update_stats(total_usage, elapsed)

    async def _process_stream_chunk(
        self, chunk: object, state: _StreamState
    ) -> AsyncGenerator[tuple[BaseEvent, LLMUsage | None], None]:
        if not isinstance(chunk, tuple) or len(chunk) != 3:  # noqa: PLR2004
            return

        namespace, stream_mode, data = chunk
        if namespace:
            return
        if stream_mode != "messages":
            return
        if not isinstance(data, tuple) or len(data) != 2:  # noqa: PLR2004
            return

        message, metadata = data
        if not hasattr(message, "content"):
            return

        if LANGCHAIN_AVAILABLE:
            from langchain_core.messages import (
                AIMessage,
                AIMessageChunk,
                HumanMessage,
                ToolMessage,
            )

            if isinstance(message, (HumanMessage, ToolMessage)):
                return
            if not isinstance(message, (AIMessage, AIMessageChunk)):
                return

        if self._is_summarization_chunk(metadata):
            if not state.summarization_active:
                state.summarization_active = True
                state.summary_tool_call_id = str(uuid4())
                yield (
                    CompactStartEvent(
                        tool_call_id=state.summary_tool_call_id,
                        current_context_tokens=self._loop.stats.context_tokens,
                        threshold=self._loop.config.get_active_model().auto_compact_threshold,
                    ),
                    None,
                )
            return

        if state.summarization_active and state.summary_tool_call_id is not None:
            state.summarization_active = False
            yield (
                CompactEndEvent(
                    tool_call_id=state.summary_tool_call_id,
                    old_context_tokens=self._loop.stats.context_tokens,
                    new_context_tokens=self._loop.stats.context_tokens,
                    summary_length=0,
                ),
                None,
            )

        usage = self._extract_usage(message)
        for event in self._extract_message_events(message, state):
            yield event, usage

    def _extract_message_events(
        self, message: Any, state: _StreamState
    ) -> list[BaseEvent]:
        external_id = str(getattr(message, "id", "") or uuid4())
        message_id = state.assistant_message_ids.setdefault(external_id, str(uuid4()))
        events: list[BaseEvent] = []

        if reasoning := self._extract_reasoning(message):
            events.append(ReasoningEvent(content=reasoning, message_id=message_id))

        if text := self._extract_text(message):
            events.append(AssistantEvent(content=text, message_id=message_id))

        events.extend(self._extract_tool_call_events(message, state))

        return events

    def _extract_tool_call_events(
        self, message: Any, state: _StreamState
    ) -> list[ToolCallEvent]:
        blocks = getattr(message, "content_blocks", None)
        events: list[ToolCallEvent] = []
        if not isinstance(blocks, list):
            blocks = getattr(message, "tool_calls", [])

        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            if (block_type := block.get("type")) not in {
                None,
                "tool_call",
                "tool_call_chunk",
            }:
                continue

            buffer_key = block.get("index")
            if buffer_key is None:
                buffer_key = block.get("id") or index

            buffer = state.tool_call_buffers.setdefault(
                buffer_key,
                {
                    "id": None,
                    "name": None,
                    "args_dict": None,
                    "args_text": "",
                    "index": block.get("index"),
                },
            )

            if isinstance(block.get("id"), str):
                buffer["id"] = block["id"]
            if isinstance(block.get("name"), str):
                buffer["name"] = block["name"]

            match block.get("args"):
                case dict() as args_dict:
                    buffer["args_dict"] = args_dict
                case str() as args_text:
                    buffer["args_text"] += args_text

            call_id = str(buffer["id"] or uuid4())
            tool_name = buffer["name"]
            if not isinstance(tool_name, str) or not tool_name:
                continue
            if call_id in state.emitted_tool_call_ids:
                continue

            tool_class = self._loop.tool_manager.available_tools.get(tool_name)
            if tool_class is None:
                continue

            args_model, _ = tool_class._get_tool_args_results()
            validated_args = None
            args_payload = buffer["args_dict"]
            if args_payload is None and buffer["args_text"]:
                try:
                    args_payload = json.loads(buffer["args_text"])
                except json.JSONDecodeError:
                    args_payload = None
            if args_payload is not None:
                try:
                    validated_args = args_model.model_validate(args_payload)
                except Exception:
                    validated_args = None

            state.emitted_tool_call_ids.add(call_id)
            events.append(
                ToolCallEvent(
                    tool_call_id=call_id,
                    tool_call_index=buffer.get("index"),
                    tool_name=tool_name,
                    tool_class=tool_class,
                    args=validated_args,
                )
            )

        return events

    @staticmethod
    def _extract_text(message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )

        content_blocks = getattr(message, "content_blocks", None)
        if not isinstance(content_blocks, list):
            return ""
        return "".join(
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )

    @staticmethod
    def _extract_reasoning(message: Any) -> str | None:
        additional_kwargs = getattr(message, "additional_kwargs", {})
        if isinstance(additional_kwargs, dict) and isinstance(
            additional_kwargs.get("reasoning_content"), str
        ):
            return additional_kwargs["reasoning_content"] or None

        content_blocks = getattr(message, "content_blocks", None)
        if not isinstance(content_blocks, list):
            return None

        parts = [
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict)
            and block.get("type") in {"reasoning", "thinking"}
            and isinstance(block.get("text"), str)
        ]
        return "".join(parts) or None

    @staticmethod
    def _extract_usage(message: Any) -> LLMUsage | None:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            return None
        return LLMUsage(
            prompt_tokens=int(usage.get("input_tokens", 0) or 0),
            completion_tokens=int(usage.get("output_tokens", 0) or 0),
        )

    @staticmethod
    def _is_summarization_chunk(metadata: object) -> bool:
        return (
            isinstance(metadata, dict) and metadata.get("lc_source") == "summarization"
        )

    async def _emit_side_event(self, event: BaseEvent) -> None:
        if self._side_event_queue is not None:
            await self._side_event_queue.put(event)

    def _on_tool_started(self) -> None:
        self._active_tool_calls += 1

    def _on_tool_finished(self) -> None:
        self._active_tool_calls = max(0, self._active_tool_calls - 1)

    def _build_runnable_config(self) -> dict[str, Any]:
        metadata: dict[str, str] = {}
        if self._loop.entrypoint_metadata:
            metadata.update(self._loop.entrypoint_metadata.model_dump())
        metadata["cwd"] = str(Path.cwd())
        metadata["agent_name"] = str(self._loop.agent_profile.name)
        return {
            "configurable": {"thread_id": self._loop.conversation_id},
            "metadata": metadata,
        }

    @staticmethod
    def _to_langchain_history(messages: list[LLMMessage]) -> list[Any]:
        return vibe_messages_to_langchain(messages) if LANGCHAIN_AVAILABLE else []

    async def _sync_messages_from_state(self) -> None:
        if self._agent is None:
            return

        state = await self._agent.aget_state(self._build_runnable_config())
        if not state or not getattr(state, "values", None):
            return

        history = langchain_messages_to_vibe(state.values.get("messages", []))
        system_message = self._loop.messages[0]
        existing_history = list(self._loop.messages[1:])
        cleaned_history = [
            message for message in history if message.role != Role.system
        ]
        self._loop.messages.reset([system_message, *cleaned_history])

        if (observer := self._loop.message_observer) is None:
            return

        for message in self._get_appended_messages(existing_history, cleaned_history):
            observer(message)

    async def _sync_context_tokens(self) -> None:
        try:
            active_model = self._loop.config.get_active_model()
            provider = self._loop.config.get_provider_for_model(active_model)
            context_tokens = await self._loop.backend.count_tokens(
                model=active_model,
                messages=self._loop.messages,
                tools=APIToolFormatHandler().get_available_tools(
                    self._loop.tool_manager
                ),
                extra_headers=self._loop._get_extra_headers(provider),
                metadata=(
                    self._loop.entrypoint_metadata.model_dump()
                    if self._loop.entrypoint_metadata
                    else None
                ),
            )
        except Exception:
            return

        self._loop.stats.context_tokens = context_tokens

    @staticmethod
    def _get_appended_messages(
        existing_history: list[LLMMessage], synced_history: list[LLMMessage]
    ) -> list[LLMMessage]:
        prefix_length = 0
        max_prefix = min(len(existing_history), len(synced_history))
        while prefix_length < max_prefix:
            if DeepAgentRuntime._message_signature(
                existing_history[prefix_length]
            ) != DeepAgentRuntime._message_signature(synced_history[prefix_length]):
                break
            prefix_length += 1
        return synced_history[prefix_length:]

    @staticmethod
    def _message_signature(message: LLMMessage) -> str:
        return json.dumps(
            message.model_dump(mode="json", exclude={"message_id"}),
            sort_keys=True,
            ensure_ascii=False,
        )
