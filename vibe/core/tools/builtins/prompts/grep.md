Use `grep` to recursively search for a regular expression pattern in files.

- It's very fast and automatically ignores files that you should not read like .pyc files, .venv directories, etc.
- Use this to find where functions are defined, how variables are used, or to locate specific error messages.
Fast text-based regex search that finds exact pattern matches within files or directories, utilizing the ripgrep command for efficient searching.\nResults will be formatted in the style of ripgrep and can be configured to include line numbers and content.\nTo avoid overwhelming output, the results are capped at 50 matches.\nUse the include or exclude patterns to filter the search scope by file type or specific paths.\n\nThis is best for finding exact text matches or regex patterns.\nMore precise than semantic search for finding specific strings or patterns.\nThis is preferred over semantic search when we know the exact symbol/function name/etc. to search in some set of directories/file types.

Usage:
- Supports full regex syntax (eg. "log.*Error", "function\\s+\\w+", etc.)
- Filter files by pattern with the `include` parameter (eg. "*.js", "*.{ts,tsx}")
- If you need to identify/count the number of matches within files, use the Bash tool with `rg` (ripgrep) directly. Do NOT use `grep`
