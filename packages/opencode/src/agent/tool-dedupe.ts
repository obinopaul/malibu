export function dedupeRequestTools<T extends { name: string }>(tools: T[]) {
  const seen = new Set<string>()
  const kept = [] as T[]
  const dropped = [] as string[]

  for (const tool of tools) {
    if (seen.has(tool.name)) {
      dropped.push(tool.name)
      continue
    }
    seen.add(tool.name)
    kept.push(tool)
  }

  return { kept, dropped }
}
