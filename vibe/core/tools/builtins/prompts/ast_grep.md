Use `ast_grep` for structural code search when plain text regex is too weak.

- `pattern` is an AST-aware code pattern, not a regex
- `path` defaults to `.`
- `include` narrows which files are searched
- `language` forces the parser when auto-detection is not enough

Examples:
- Python function definitions: `def $NAME($ARGS): $BODY`
- JavaScript imports: `import $NAME from "$MODULE"`
- React hooks: `useEffect($CALLBACK, $DEPS)`

Use `grep` for raw text search. Use `ast_grep` when syntax matters.

Searches for AST patterns within code files using structural matching. Supports multiple programming languages and returns matches with file paths, line numbers, and code context.
YOU MUST USE THIS TOOL WHENEVER YOU WANT TO SEARCH FOR CODE.
Usage:
- AST patterns: Use code-like patterns with wildcards (e.g., 'function $NAME($ARGS) { $BODY }', 'import $MODULE from "$PATH"')
- Wildcards: Use $UPPERCASE for capturing parts (e.g., $NAME, $ARGS, $BODY)
- Language auto-detection: Automatically detects programming language from file extensions
- Filter files by pattern with the `include` parameter (e.g., '*.js', '*.{ts,tsx}')
- Supports 20+ programming languages including JavaScript, TypeScript, Python, Java, Go, Rust, etc.
