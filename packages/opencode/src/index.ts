import path from "path"
import { readdir, readFile } from "fs/promises"
import { EOL } from "os"

const ROOT = path.resolve(import.meta.dir, "../../..")
const PROBES = [
  "packages/opencode/node_modules/deepagents",
  "packages/opencode/node_modules/gitlab-ai-provider",
  "packages/opencode/node_modules/@babel/core",
]
const HEALTH_SKIP = new Set(["completion", "upgrade", "uninstall", "--help", "-h", "--version", "-v"])
const rawVersion = Reflect.get(globalThis, "MALIBU_VERSION")
const VERSION = typeof rawVersion === "string" ? rawVersion : "local"

function isCompiledBinary() {
  // In compiled Bun binaries, process.execPath points to the malibu binary itself.
  // In development, process.execPath points to the bun runtime.
  const exec = path.basename(process.execPath).toLowerCase()
  return exec === "malibu" || exec === "malibu.exe"
}

function shouldCheckHealth(argv: string[]) {
  if (process.env.MALIBU_SKIP_DEPENDENCY_HEALTH_CHECK === "1") return false
  if (isCompiledBinary()) return false
  return !argv.some((item) => HEALTH_SKIP.has(item))
}

function detail(error: unknown) {
  if (error instanceof Error) return error.message
  return String(error)
}

function parse(version: string) {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)/)
  if (!match) return
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
  }
}

function mismatch(expected?: string, actual?: string) {
  if (!expected || !actual) return
  const exp = parse(expected)
  const act = parse(actual)
  if (!exp || !act) {
    if (expected !== actual) return `Expected Bun ${expected} but found ${actual}.`
    return
  }
  if (exp.major !== act.major || exp.minor !== act.minor) {
    return `Expected Bun ${expected} but found ${actual}.`
  }
  if (act.patch < exp.patch) {
    return `Expected Bun ${expected} or newer patch release, but found ${actual}.`
  }
}

async function pinned() {
  const pkg = await Bun.file(path.join(ROOT, "package.json")).json().catch(() => ({})) as { packageManager?: string }
  if (!pkg.packageManager?.startsWith("bun@")) return undefined
  return pkg.packageManager.slice("bun@".length)
}

async function probe(dir: string) {
  await readdir(dir)
  await readFile(path.join(dir, "package.json"), "utf8")
}

async function verifyHealth() {
  const expected = await pinned()
  const failures = [] as string[]
  const version = mismatch(expected, Bun.version)

  for (const item of PROBES) {
    const next = path.resolve(ROOT, item)
    try {
      await probe(next)
    } catch (error) {
      failures.push(`${item}: ${detail(error)}`)
    }
  }

  if (!version && failures.length === 0) return
  throw new Error(
    [
      "Malibu dependency health check failed before tool execution.",
      ...(version ? [version] : []),
      ...failures,
      "",
      "Recovery:",
      `1. Use Bun ${expected ?? "from package.json"}.`,
      "2. Clear the broken Bun install state for this repo.",
      "3. Reinstall dependencies with Bun.",
      "4. Rerun the tool smoke tests.",
    ].join("\n"),
  )
}

try {
  if (process.argv.slice(2).some((item) => item === "--version" || item === "-v")) {
    process.stdout.write(VERSION + EOL)
  } else {
    if (shouldCheckHealth(process.argv.slice(2))) {
      await verifyHealth()
    }
    const { runCli } = await import("./cli-main")
    await runCli()
  }
} catch (e) {
  process.stderr.write((e instanceof Error ? e.message : String(e)) + EOL)
  process.exitCode = 1
} finally {
  // Some subprocesses don't react properly to SIGTERM and similar signals.
  // Most notably, some docker-container-based MCP servers don't handle such signals unless
  // run using `docker run --init`.
  // Explicitly exit to avoid any hanging subprocesses.
  process.exit()
}
