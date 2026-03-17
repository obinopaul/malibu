Use `rename_symbol` for workspace-safe renames through LSP.

- Prefer it over manual search/replace when changing identifiers.
- The tool only applies edits for files inside the current workspace root.
- The result reports changed files, skipped paths, and post-edit diagnostics.
Rename a symbol across the entire codebase using LSP refactoring. This is a safe, semantic rename that updates all references to the symbol — function calls, imports, type annotations, and more.

## Usage notes

- Uses LSP to understand code semantics, so it only renames actual references to the symbol — not unrelated text that happens to match
- Updates all files in the codebase that reference the symbol
- When to use vs search-and-replace (edit_file with match_all):
  - Use rename_symbol for safe semantic renames — it understands code structure and only changes actual references
  - Use edit_file match_all for simple text replacement when the string is unique and context doesn't matter
- Edge cases: string literals and comments that mention the symbol name are NOT renamed (they are not code references). If you need those updated too, do a follow-up search-and-replace
- Always use find_referencing_symbols first if you want to preview the scope of changes before renaming
