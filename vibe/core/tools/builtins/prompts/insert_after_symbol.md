Use `insert_after_symbol` to add code immediately after an existing symbol.

- The insertion point is derived from the symbol range, not a text search.
- Content is indented from the target location for deterministic placement.
- Prefer this when appending a related helper, declaration, or implementation after a symbol.
Insert code immediately after a symbol (function, class, method, etc.) using LSP-based positioning.

## Usage notes

- The content is inserted at the same indentation level as the target symbol — indentation is preserved automatically
- Useful for adding new methods after existing ones, appending helper functions, or adding related code after a class definition
- When to use vs edit_file: use insert_after_symbol for structured insertion that should appear directly after a specific code element; use edit_file for general text replacement anywhere in a file
- The symbol is located by name using LSP, so you don't need to know the exact line number
