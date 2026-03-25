# Task Tool Parallel Execution Diagnostic Report
Generated: 2026-03-25T12:14:23.420Z

## Test: single task — no checkpointer
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|      6 | agent_created |  |
|     20 | AIMessageChunk:tool_call | id=call_1 name=task content={"description":"Explore the codebase","subagent_type":"explore"} |
|     49 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     75 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     78 | stream_end | Total events: 3 |
|     78 | orphaned_tool_calls | 1 orphaned: call_1 |

### Summary
- Events: 6
- Tool calls detected: 2
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 2

---

## Test: 2 parallel tasks — no checkpointer
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|      3 | agent_created |  |
|     13 | AIMessageChunk:tool_call | id=call_explore_1 name=task content={"description":"Explore agent dir","subagent_type":"explore"} |
|     13 | AIMessageChunk:tool_call | id=call_explore_2 name=task content={"description":"Explore test dir","subagent_type":"explore"} |
|     32 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     33 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     43 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     46 | stream_end | Total events: 4 |
|     46 | orphaned_tool_calls | 2 orphaned: call_explore_1, call_explore_2 |

### Summary
- Events: 8
- Tool calls detected: 3
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 3

---

## Test: 3 parallel same-type tasks — no checkpointer
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|      4 | agent_created |  |
|     19 | AIMessageChunk:tool_call | id=call_1 name=task content={"description":"Explore area 1","subagent_type":"explore"} |
|     19 | AIMessageChunk:tool_call | id=call_2 name=task content={"description":"Explore area 2","subagent_type":"explore"} |
|     19 | AIMessageChunk:tool_call | id=call_3 name=task content={"description":"Explore area 3","subagent_type":"explore"} |
|     60 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     61 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     63 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     78 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     79 | stream_end | Total events: 5 |
|     79 | orphaned_tool_calls | 3 orphaned: call_1, call_2, call_3 |

### Summary
- Events: 10
- Tool calls detected: 4
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 4

---

## Test: 2 parallel tasks — SQLite checkpointer
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|     14 | checkpointer_created | /tmp/malibu-test-cp-1774440858191.db |
|     17 | agent_created |  |
|     32 | AIMessageChunk:tool_call | id=call_cp_1 name=task content={"description":"Explore with checkpointer A","subagent_type":"explore"} |
|     32 | AIMessageChunk:tool_call | id=call_cp_2 name=task content={"description":"Explore with checkpointer B","subagent_type":"explore"} |
|     54 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     54 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     66 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     69 | stream_end | Total events: 4 |
|     69 | orphaned_tool_calls | 2 orphaned: call_cp_1, call_cp_2 |

### Summary
- Events: 9
- Tool calls detected: 3
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 3

---

## Test: 3 parallel tasks — SQLite checkpointer
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|     17 | agent_created |  |
|     35 | AIMessageChunk:tool_call | id=call_3cp_1 name=task content={"description":"Explore area 1 (CP)","subagent_type":"explore"} |
|     35 | AIMessageChunk:tool_call | id=call_3cp_2 name=task content={"description":"Explore area 2 (CP)","subagent_type":"explore"} |
|     35 | AIMessageChunk:tool_call | id=call_3cp_3 name=task content={"description":"Explore area 3 (CP)","subagent_type":"explore"} |
|     71 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     73 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     74 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     85 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     87 | stream_end | Total events: 5 |
|     87 | orphaned_tool_calls | 3 orphaned: call_3cp_1, call_3cp_2, call_3cp_3 |

### Summary
- Events: 10
- Tool calls detected: 4
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 4

---

## Test: background middleware — 2 parallel tasks
Status: **CRASHED**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|      1 | bg_middleware_created |  |

### Crash Details

```
Error: Middleware backgroundSubAgentMiddleware is defined multiple times

Stack trace:
Error: Middleware backgroundSubAgentMiddleware is defined multiple times
    at new ReactAgent (/mnt/c/Users/pault/Documents/3. AI and Machine Learning/2. Deep Learning/1c. App/Projects/malibu/node_modules/.bun/langchain@1.2.34+3b59f6c9f9bb89ca/node_modules/langchain/dist/agents/ReactAgent.js:108:47)
    at createAgent (/mnt/c/Users/pault/Documents/3. AI and Machine Learning/2. Deep Learning/1c. App/Projects/malibu/node_modules/.bun/langchain@1.2.34+3b59f6c9f9bb89ca/node_modules/langchain/dist/agents/index.js:9:13)
    at createMalibuAgent (/mnt/c/Users/pault/Documents/3. AI and Machine Learning/2. Deep Learning/1c. App/Projects/malibu/packages/opencode/src/agent/create-agent.ts:190:17)
    at <anonymous> (/mnt/c/Users/pault/Documents/3. AI and Machine Learning/2. Deep Learning/1c. App/Projects/malibu/packages/opencode/test/agent/subagent-parallel.test.ts:1099:25)
    at processTicksAndRejections (native:7:39)
```

### Summary
- Events: 1
- Tool calls detected: 0
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 0

---

## Overall Summary
- Total tests: 6
- Passed: 5
- Crashed: 1
