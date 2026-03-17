Use the `git` tool for repository-aware context, status, diff, log, branch inspection, and guarded commits.

Perform structured git operations with implementation-aligned actions and predictable output.

Guidance:
- Prefer `action="context"` when you need a compact repository summary.
- Use `status`, `diff`, `log`, `branch`, and `branches` before considering `commit`.
- `commit` may return a `snapshot_id` created before mutation.
- If commit fails due to missing staged changes, inspect status/diff before retrying.

## Available actions

- context: Show compact repository summary.
- status: Show current repository status.
- diff: Show differences (supports `staged`).
- log: Show commit history (supports `n` and `oneline`).
- branch: Show current branch.
- branches: List branches.
- commit: Create commit (requires `message`, supports optional `files` pre-stage list).

## Arguments

- `action` (required): One of the supported actions.
- `cwd` (optional): Repository directory.
- `staged` (optional): Use staged diff for `action="diff"`.
- `n` (optional): Number of commits for `action="log"`.
- `oneline` (optional): One-line format for `action="log"`.
- `message` (required for commit): Commit message.
- `files` (optional for commit): File paths to stage before committing.

## Notes

- Actions such as `checkout`, `push`, `pull`, `stash`, `merge`, and `create_pr` are not part of this tool's current action set.
- Use shell git commands only when you need operations outside this action set.
