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
