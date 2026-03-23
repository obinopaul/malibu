/**
 * Tool name alias map — canonicalizes tool names to Malibu native names.
 *
 * After the createMalibuAgent migration, the canonical tool names are:
 *   read, list, write, edit, bash, glob, grep
 *
 * Old DeepAgent names (read_file, ls, execute, etc.) are kept as aliases
 * for backward compatibility with existing sessions and middleware that
 * may still reference them internally (e.g., SubAgentMiddleware, TodoListMiddleware).
 */
const map = new Map<string, string>([
  // Malibu native names (canonical)
  ["read", "read"],
  ["list", "list"],
  ["write", "write"],
  ["edit", "edit"],
  ["bash", "bash"],
  ["glob", "glob"],
  ["grep", "grep"],
  // DeepAgent aliases → Malibu native
  ["read_file", "read"],
  ["ls", "list"],
  ["write_file", "write"],
  ["edit_file", "edit"],
  ["execute", "bash"],
  // Middleware tools (unchanged)
  ["todowrite", "todowrite"],
  ["write_todos", "todowrite"],
  ["todoread", "todoread"],
  ["task", "task"],
])

export function canonTool(name?: string) {
  if (!name) return ""
  return map.get(name) ?? name
}

export function sameTool(a?: string, b?: string) {
  if (!a || !b) return false
  return canonTool(a) === canonTool(b)
}
