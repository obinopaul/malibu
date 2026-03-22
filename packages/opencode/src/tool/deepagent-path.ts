import path from "path"
import { Instance } from "../project/instance"
import { Filesystem } from "../util/filesystem"

function project(raw: string) {
  return path.resolve(Instance.worktree, `.${raw}`)
}

export function resolveDeepPath(raw: string, input?: { base?: string; strict?: boolean }) {
  if (raw.startsWith("/")) {
    const next = project(raw)
    if (input?.strict) return next
    const real = path.resolve(raw)
    if (Instance.containsPath(real)) return real
    if (Filesystem.stat(next)) return next
    if (!Filesystem.stat(real)) return next
    return real
  }
  if (path.isAbsolute(raw)) return raw
  const next = path.resolve(input?.base ?? Instance.directory, raw)
  if (Filesystem.stat(next)) return next
  const root = path.resolve(Instance.worktree, raw)
  if (Filesystem.stat(root)) return root
  return next
}

export function resolveDeepSearch(raw?: string, input?: { base?: string; strict?: boolean }) {
  if (!raw) return input?.base ?? Instance.directory
  return resolveDeepPath(raw, input)
}

export function resolveToolPath(raw: string, input?: { base?: string }) {
  if (path.isAbsolute(raw)) return raw
  return resolveDeepPath(raw, input)
}

export function resolveToolSearch(raw?: string, input?: { base?: string }) {
  if (!raw) return input?.base ?? Instance.directory
  return resolveToolPath(raw, input)
}
