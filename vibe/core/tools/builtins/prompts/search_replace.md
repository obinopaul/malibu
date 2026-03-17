Use `search_replace` to make targeted changes to files using SEARCH/REPLACE blocks. This tool finds exact text matches and replaces them.

Arguments:
- `file_path`: The path to the file to modify
- `content`: The SEARCH/REPLACE blocks defining the changes

The content format is:

```
<<<<<<< SEARCH
[exact text to find in the file]
=======
[exact text to replace it with]
>>>>>>> REPLACE
```

You can include multiple SEARCH/REPLACE blocks to make multiple changes to the same file:

```
<<<<<<< SEARCH
def old_function():
    return "old value"
=======
def new_function():
    return "new value"
>>>>>>> REPLACE

<<<<<<< SEARCH
import os
=======
import os
import sys
>>>>>>> REPLACE
```

IMPORTANT:

- The SEARCH text must match EXACTLY (including whitespace, indentation, and line endings)
- The SEARCH text must appear exactly once in the file - if it appears multiple times, the tool will error
- Use at least 5 equals signs (=====) between SEARCH and REPLACE sections
- The tool will provide detailed error messages showing context if search text is not found
- Each search/replace block is applied in order, so later blocks see the results of earlier ones
- Be careful with escape sequences in string literals - use \n not \\n for newlines in code

Custom editing tool for viewing, creating and editing files in plain-text format
* State is persistent across command calls and discussions with the user
* If `path` is a text file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep
* The `create` command cannot be used if the specified `path` already exists as a file
* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`
* The `undo_edit` command will revert the last edit made to the file at `path`
* This tool can be used for creating and editing files in plain-text format.


Before using this tool:
1. Use the view tool to understand the file's contents and context
2. Verify the directory path is correct (only applicable when creating new files):
   - Use the view tool to verify the parent directory exists and is the correct location

When making edits:
   - Ensure the edit results in idiomatic, correct code
   - Do not leave the code in a broken state
   - Always use absolute file paths (starting with /)

CRITICAL REQUIREMENTS FOR USING THIS TOOL:

1. EXACT MATCHING: The `old_str` parameter must match EXACTLY one or more consecutive lines from the file, including all whitespace and indentation. The tool will fail if `old_str` matches multiple locations or doesn't match exactly with the file content.

2. UNIQUENESS: The `old_str` must uniquely identify a single instance in the file:
   - Include sufficient context before and after the change point (3-5 lines recommended)
   - If not unique, the replacement will not be performed

3. REPLACEMENT: The `new_str` parameter should contain the edited lines that replace the `old_str`. Both strings must be different.

Remember: when making multiple file edits in a row to the same file, you should prefer to send all edits in a single message with multiple calls to this tool, rather than multiple messages with a single call each."""
