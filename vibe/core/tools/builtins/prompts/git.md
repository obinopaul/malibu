Use the `git` tool for repository-aware status, diff, log, branch inspection, and guarded commits.

Guidance:
- Prefer `action="context"` when you need a compact repository summary.
- Use `status`, `diff`, `log`, `branch`, and `branches` before considering `commit`.
- `commit` is guarded and may return a `snapshot_id` created before the mutation.
- Treat protected-branch commit refusals as hard stops, not retry prompts.
- When a commit fails because there are no staged changes, inspect the repo state instead of repeating the same call.
