Use `insert_before_symbol` to add code immediately before an existing symbol.

- The insertion point is derived from the symbol range, not a text search.
- Content is indented from the target location for deterministic placement.
- Prefer this when adding a helper or declaration relative to an existing symbol.
Insert code immediately before a symbol (function, class, method, etc.) using LSP-based positioning.

## Usage notes

- The content is inserted at the same indentation level as the target symbol — indentation is preserved automatically
- Useful for adding decorators, imports, comments, or new functions/classes before existing code
- When to use vs edit_file: use insert_before_symbol for structured insertion that should appear directly before a specific code element; use edit_file for general text replacement anywhere in a file
- The symbol is located by name using LSP, so you don't need to know the exact line number
