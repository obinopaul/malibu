Use `shell_run` to execute commands inside a persistent shell session.

- Set `wait_for_output=false` for long-running commands
- Use `shell_view` to inspect progress later
- Use `shell_write` to send follow-up input to a running process
- Use `run_directory` when one command needs a temporary cwd override

Prefer `bash` only for one-off stateless commands.
