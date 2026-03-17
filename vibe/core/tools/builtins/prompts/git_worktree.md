Use the `git_worktree` tool for isolated branch worktrees.

Guidance:
- Prefer `list` or `get` before mutating an existing worktree.
- `create`, `remove`, and `reset` are mutating operations and may return a pre-mutation `snapshot_id`.
- Use worktrees when you need a clean parallel branch workspace without disturbing the current tree.
- If a target worktree is missing, stop and inspect with `list` rather than guessing names.
