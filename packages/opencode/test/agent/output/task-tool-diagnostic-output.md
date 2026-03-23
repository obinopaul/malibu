# Task Tool Parallel Execution Diagnostic Report
Generated: 2026-03-23T16:55:41.601Z

## Test: single task — no checkpointer
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|     20 | agent_created |  |
|     77 | AIMessageChunk:tool_call | id=call_1 name=task content={"description":"Explore the codebase","subagent_type":"explore"} |
|    106 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|    118 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|    123 | stream_end | Total events: 3 |
|    123 | orphaned_tool_calls | 1 orphaned: call_1 |

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
|      8 | agent_created |  |
|     17 | AIMessageChunk:tool_call | id=call_explore_1 name=task content={"description":"Explore agent dir","subagent_type":"explore"} |
|     17 | AIMessageChunk:tool_call | id=call_explore_2 name=task content={"description":"Explore test dir","subagent_type":"explore"} |
|     43 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     43 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     62 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     69 | stream_end | Total events: 4 |
|     69 | orphaned_tool_calls | 2 orphaned: call_explore_1, call_explore_2 |

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
|      6 | agent_created |  |
|     15 | AIMessageChunk:tool_call | id=call_1 name=task content={"description":"Explore area 1","subagent_type":"explore"} |
|     15 | AIMessageChunk:tool_call | id=call_2 name=task content={"description":"Explore area 2","subagent_type":"explore"} |
|     15 | AIMessageChunk:tool_call | id=call_3 name=task content={"description":"Explore area 3","subagent_type":"explore"} |
|     35 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     36 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     36 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     47 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     50 | stream_end | Total events: 5 |
|     50 | orphaned_tool_calls | 3 orphaned: call_1, call_2, call_3 |

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
|     10 | checkpointer_created | /tmp/malibu-test-cp-1774284936698.db |
|     18 | agent_created |  |
|     34 | AIMessageChunk:tool_call | id=call_cp_1 name=task content={"description":"Explore with checkpointer A","subagent_type":"explore"} |
|     34 | AIMessageChunk:tool_call | id=call_cp_2 name=task content={"description":"Explore with checkpointer B","subagent_type":"explore"} |
|     57 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     58 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     70 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     74 | stream_end | Total events: 4 |
|     74 | orphaned_tool_calls | 2 orphaned: call_cp_1, call_cp_2 |

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
|     13 | agent_created |  |
|     23 | AIMessageChunk:tool_call | id=call_3cp_1 name=task content={"description":"Explore area 1 (CP)","subagent_type":"explore"} |
|     23 | AIMessageChunk:tool_call | id=call_3cp_2 name=task content={"description":"Explore area 2 (CP)","subagent_type":"explore"} |
|     23 | AIMessageChunk:tool_call | id=call_3cp_3 name=task content={"description":"Explore area 3 (CP)","subagent_type":"explore"} |
|     48 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     48 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     49 | AIMessageChunk:text | Subagent exploration complete. Found relevant files. |
|     63 | AIMessageChunk:text | All tasks completed. Here is the summary. |
|     68 | stream_end | Total events: 5 |
|     68 | orphaned_tool_calls | 3 orphaned: call_3cp_1, call_3cp_2, call_3cp_3 |

### Summary
- Events: 10
- Tool calls detected: 4
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 4

---

## Test: background middleware — 2 parallel tasks
Status: **PASS**

### Event Timeline

| T+ms | Type | Details |
|------|------|---------|
|      2 | bg_middleware_created |  |
|      6 | agent_created |  |
|     17 | AIMessageChunk:tool_call | id=call_bg_1 name=background_task content={"description":"Explore area 1","subagent_type":"general-purpose"} |
|     17 | AIMessageChunk:tool_call | id=call_bg_2 name=background_task content={"description":"Explore area 2","subagent_type":"general-purpose"} |
|     33 | AIMessageChunk:tool_call | id=call_wait name=wait_background_task content={} |
|     35 | AIMessageChunk:text | Background task completed successfully. |
|     36 | AIMessageChunk:text | Background task completed successfully. |
|     44 | AIMessageChunk:text | Both background tasks completed. Here is the combined result. |
|     48 | stream_end | Total events: 5 |
|     48 | registry_state | pending=0 |

### Summary
- Events: 10
- Tool calls detected: 3
- Tool messages received: 0
- Errors: 0
- Orphaned tool calls: 3

---

## Overall Summary
- Total tests: 6
- Passed: 6
- Crashed: 0
