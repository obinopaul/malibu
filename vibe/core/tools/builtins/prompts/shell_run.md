Use `shell_run` to execute commands inside a persistent shell session.

- Set `wait_for_output=false` for long-running commands
- Use `shell_view` to inspect progress later
- Use `shell_write` to send follow-up input to a running process
- Use `run_directory` when one command needs a temporary cwd override

Prefer `bash` only for one-off stateless commands.

Executes a bash command in a persistent shell session

Usage notes:
- It is very helpful if you write a clear, concise description of what this command does in 5-10 words
- To run multiple commands, join them with ';' or '&&'. Do not use newlines
- For long-running tasks (e.g., deployments), set `wait_for_output` to False and monitor progress with the `BashView` tool
- You can specify an optional timeout in seconds (up to {MAX_TIMEOUT} seconds). If not specified, commands will timeout after {DEFAULT_TIMEOUT} seconds
