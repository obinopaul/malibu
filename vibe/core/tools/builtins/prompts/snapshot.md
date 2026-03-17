Use the `snapshot` tool to capture and inspect filesystem state through Malibu's shadow git snapshot store.

Guidance:
- Prefer `take` before risky mutations when you need an explicit rollback point.
- `take` without explicit files snapshots dirty tracked and untracked files when the current directory is inside a git repository.
- Use `list` to inspect recent snapshots, `diff` to compare a snapshot against current files, and `revert` only when you intentionally want rollback.
- `cleanup` is maintenance only; do not use it as part of normal task execution.
