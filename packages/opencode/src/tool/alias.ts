const map = new Map<string, string>([
  ["list", "ls"],
  ["ls", "ls"],
  ["read", "read_file"],
  ["read_file", "read_file"],
  ["write", "write_file"],
  ["write_file", "write_file"],
  ["edit", "edit_file"],
  ["edit_file", "edit_file"],
  ["bash", "execute"],
  ["execute", "execute"],
  ["todowrite", "write_todos"],
  ["write_todos", "write_todos"],
  ["todoread", "todoread"],
  ["task", "task"],
  ["glob", "glob"],
  ["grep", "grep"],
])

export function canonTool(name?: string) {
  if (!name) return ""
  return map.get(name) ?? name
}

export function sameTool(a?: string, b?: string) {
  if (!a || !b) return false
  return canonTool(a) === canonTool(b)
}
