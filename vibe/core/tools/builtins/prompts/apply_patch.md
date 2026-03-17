Use `apply_patch` for structured multi-file edits when a simple exact replacement is not enough.

- Prefer `search_replace` for a small exact edit in one file.
- Use `apply_patch` when you need adds, deletes, moves, or multiple hunks across files.
- The input must use the Malibu patch envelope:

```text
*** Begin Patch
*** Update File: path/to/file.py
@@
-old
+new
*** End Patch
```

Supported operations:
- `*** Add File: <path>`
- `*** Delete File: <path>`
- `*** Update File: <path>`
- Optional `*** Move to: <new path>` after `*** Update File`

Rules:
- Every patch must start with `*** Begin Patch` and end with `*** End Patch`
- Added file contents and inserted lines must start with `+`
- Updated hunks use ` `, `-`, and `+` prefixes like a simplified diff
- Include enough surrounding context for each hunk to apply unambiguously
- If you only need one literal replacement, use `search_replace` instead
