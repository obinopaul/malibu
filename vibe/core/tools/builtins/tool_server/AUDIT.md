`tool_server` is intentionally not integrated into Malibu's native runtime in this phase.

Current blockers:
- Foreign import namespace usage, including `malibu.agent.*` references.
- A separate tool abstraction stack that does not match Malibu's native `BaseTool` and `ToolManager` contracts.
- Runtime assumptions around external workspace and settings objects that Malibu does not provide.
- A duplicate execution model that overlaps with Malibu's existing tool loop and DeepAgent adapter path.

Until those blockers are resolved, this directory remains source material only.
