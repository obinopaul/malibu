Use `replace_symbol_body` to rewrite the implementation of a symbol while keeping its declaration when possible.

- `preserve_signature=true` uses explicit Python logic plus brace-delimited body logic for languages like JavaScript, TypeScript, Go, Rust, Java, Kotlin, C#, C/C++, PHP, Dart, and Swift.
- This is safer than manual patching when you want to keep the same function or class name and signature.
- The result includes the replaced range and any LSP diagnostics after the edit.
