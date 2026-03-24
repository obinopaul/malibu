import { NodeChildProcessSpawner, NodeFileSystem, NodePath } from "@effect/platform-node"
import { Effect, Layer, Schema, ServiceMap, Stream } from "effect"
import { FetchHttpClient, HttpClient, HttpClientRequest, HttpClientResponse } from "effect/unstable/http"
import { makeRunPromise } from "@/effect/run-service"
import { withTransientReadRetry } from "@/util/effect-http-client"
import { ChildProcess, ChildProcessSpawner } from "effect/unstable/process"
import path from "path"
import { readdir, readFile } from "fs/promises"
import z from "zod"
import { BusEvent } from "@/bus/bus-event"
import { Flag } from "../flag/flag"
import { Log } from "../util/log"
import { NamedError } from "@malibu-ai/util/error"

declare global {
  const MALIBU_VERSION: string
  const MALIBU_CHANNEL: string
}

export namespace Installation {
  const log = Log.create({ service: "installation" })
  const ROOT = path.resolve(import.meta.dir, "../../../..")
  const PROBES = [
    "packages/opencode/node_modules/deepagents",
    "packages/opencode/node_modules/gitlab-ai-provider",
    "packages/opencode/node_modules/@babel/core",
  ]
  let health: Promise<void> | undefined

  export type Method = "curl" | "npm" | "yarn" | "pnpm" | "bun" | "brew" | "scoop" | "choco" | "unknown"
  export const DependencyHealthError = NamedError.create(
    "DependencyHealthError",
    z.object({
      message: z.string(),
    }),
  )

  export const Event = {
    Updated: BusEvent.define(
      "installation.updated",
      z.object({
        version: z.string(),
      }),
    ),
    UpdateAvailable: BusEvent.define(
      "installation.update-available",
      z.object({
        version: z.string(),
      }),
    ),
  }

  export const Info = z
    .object({
      version: z.string(),
      latest: z.string(),
    })
    .meta({
      ref: "InstallationInfo",
    })
  export type Info = z.infer<typeof Info>

  export const VERSION = typeof MALIBU_VERSION === "string" ? MALIBU_VERSION : "local"
  export const CHANNEL = typeof MALIBU_CHANNEL === "string" ? MALIBU_CHANNEL : "local"
  export const USER_AGENT = `malibu/${CHANNEL}/${VERSION}/${Flag.MALIBU_CLIENT}`

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

  async function pinned(root: string) {
    const pkg = await Bun.file(path.join(root, "package.json")).json().catch(() => ({})) as { packageManager?: string }
    if (!pkg.packageManager?.startsWith("bun@")) return undefined
    return pkg.packageManager.slice("bun@".length)
  }

  async function probe(dir: string) {
    await readdir(dir)
    await readFile(path.join(dir, "package.json"), "utf8")
  }

  function message(input: {
    root: string
    failures: Array<{ path: string; error: string }>
    version?: string
    expected?: string
  }) {
    const lines = [
      "Malibu dependency health check failed before tool execution.",
    ]
    if (input.version) lines.push(input.version)
    if (input.failures.length > 0) {
      lines.push("Unreadable dependency entries:")
      lines.push(...input.failures.map((item) => `- ${path.relative(input.root, item.path) || item.path}: ${item.error}`))
    }
    lines.push("")
    lines.push("Recovery:")
    lines.push(`1. Use Bun ${input.expected ?? "from package.json"}.`)
    lines.push("2. Clear the broken Bun install state for this repo.")
    lines.push("3. Reinstall dependencies with Bun.")
    lines.push("4. Rerun the tool smoke tests.")
    return lines.join("\n")
  }

  export async function checkDependencyHealth(input?: { root?: string; bun?: string; probes?: string[] }) {
    const root = input?.root ?? ROOT
    const expected = await pinned(root)
    const actual = input?.bun ?? Bun.version
    const failures = [] as Array<{ path: string; error: string }>
    const version = mismatch(expected, actual)

    for (const item of input?.probes ?? PROBES) {
      const next = path.resolve(root, item)
      try {
        await probe(next)
      } catch (error) {
        failures.push({
          path: next,
          error: detail(error),
        })
      }
    }

    if (!version && failures.length === 0) return
    throw new DependencyHealthError({
      message: message({
        root,
        failures,
        version,
      }),
    })
  }

  export function resetDependencyHealth() {
    health = undefined
  }

  function isCompiledBinary() {
    const exec = path.basename(process.execPath).toLowerCase()
    return exec === "malibu" || exec === "malibu.exe"
  }

  export async function verifyDependencyHealth(input?: { root?: string; bun?: string; probes?: string[] }) {
    if (process.env.MALIBU_SKIP_DEPENDENCY_HEALTH_CHECK === "1") return
    if (isCompiledBinary()) return
    if (input) return checkDependencyHealth(input)
    if (!health) health = checkDependencyHealth()
    return health
  }

  export function isPreview() {
    return CHANNEL !== "latest"
  }

  export function isLocal() {
    return CHANNEL === "local"
  }

  export class UpgradeFailedError extends Schema.TaggedErrorClass<UpgradeFailedError>()("UpgradeFailedError", {
    stderr: Schema.String,
  }) {}

  // Response schemas for external version APIs
  const GitHubRelease = Schema.Struct({ tag_name: Schema.String })
  const NpmPackage = Schema.Struct({ version: Schema.String })
  const BrewFormula = Schema.Struct({ versions: Schema.Struct({ stable: Schema.String }) })
  const BrewInfoV2 = Schema.Struct({
    formulae: Schema.Array(Schema.Struct({ versions: Schema.Struct({ stable: Schema.String }) })),
  })
  const ChocoPackage = Schema.Struct({
    d: Schema.Struct({ results: Schema.Array(Schema.Struct({ Version: Schema.String })) }),
  })
  const ScoopManifest = NpmPackage

  export interface Interface {
    readonly info: () => Effect.Effect<Info>
    readonly method: () => Effect.Effect<Method>
    readonly latest: (method?: Method) => Effect.Effect<string>
    readonly upgrade: (method: Method, target: string) => Effect.Effect<void, UpgradeFailedError>
  }

  export class Service extends ServiceMap.Service<Service, Interface>()("@malibu/Installation") {}

  export const layer: Layer.Layer<Service, never, HttpClient.HttpClient | ChildProcessSpawner.ChildProcessSpawner> =
    Layer.effect(
      Service,
      Effect.gen(function* () {
        const http = yield* HttpClient.HttpClient
        const httpOk = HttpClient.filterStatusOk(withTransientReadRetry(http))
        const spawner = yield* ChildProcessSpawner.ChildProcessSpawner

        const text = Effect.fnUntraced(
          function* (cmd: string[], opts?: { cwd?: string; env?: Record<string, string> }) {
            const proc = ChildProcess.make(cmd[0], cmd.slice(1), {
              cwd: opts?.cwd,
              env: opts?.env,
              extendEnv: true,
            })
            const handle = yield* spawner.spawn(proc)
            const out = yield* Stream.mkString(Stream.decodeText(handle.stdout))
            yield* handle.exitCode
            return out
          },
          Effect.scoped,
          Effect.catch(() => Effect.succeed("")),
        )

        const run = Effect.fnUntraced(
          function* (cmd: string[], opts?: { cwd?: string; env?: Record<string, string> }) {
            const proc = ChildProcess.make(cmd[0], cmd.slice(1), {
              cwd: opts?.cwd,
              env: opts?.env,
              extendEnv: true,
            })
            const handle = yield* spawner.spawn(proc)
            const [stdout, stderr] = yield* Effect.all(
              [Stream.mkString(Stream.decodeText(handle.stdout)), Stream.mkString(Stream.decodeText(handle.stderr))],
              { concurrency: 2 },
            )
            const code = yield* handle.exitCode
            return { code, stdout, stderr }
          },
          Effect.scoped,
          Effect.catch(() => Effect.succeed({ code: ChildProcessSpawner.ExitCode(1), stdout: "", stderr: "" })),
        )

        const getBrewFormula = Effect.fnUntraced(function* () {
          const tapFormula = yield* text(["brew", "list", "--formula", "obinopaul/tap/malibu"])
          if (tapFormula.includes("malibu")) return "obinopaul/tap/malibu"
          const coreFormula = yield* text(["brew", "list", "--formula", "malibu"])
          if (coreFormula.includes("malibu")) return "malibu"
          return "malibu"
        })

        const upgradeCurl = Effect.fnUntraced(
          function* (target: string) {
            const response = yield* httpOk.execute(HttpClientRequest.get("https://malibu.ai/install"))
            const body = yield* response.text
            const bodyBytes = new TextEncoder().encode(body)
            const proc = ChildProcess.make("bash", [], {
              stdin: Stream.make(bodyBytes),
              env: { VERSION: target },
              extendEnv: true,
            })
            const handle = yield* spawner.spawn(proc)
            const [stdout, stderr] = yield* Effect.all(
              [Stream.mkString(Stream.decodeText(handle.stdout)), Stream.mkString(Stream.decodeText(handle.stderr))],
              { concurrency: 2 },
            )
            const code = yield* handle.exitCode
            return { code, stdout, stderr }
          },
          Effect.scoped,
          Effect.orDie,
        )

        const methodImpl = Effect.fn("Installation.method")(function* () {
          if (process.execPath.includes(path.join(".malibu", "bin"))) return "curl" as Method
          if (process.execPath.includes(path.join(".local", "bin"))) return "curl" as Method
          const exec = process.execPath.toLowerCase()

          const checks: Array<{ name: Method; command: () => Effect.Effect<string> }> = [
            { name: "npm", command: () => text(["npm", "list", "-g", "--depth=0"]) },
            { name: "yarn", command: () => text(["yarn", "global", "list"]) },
            { name: "pnpm", command: () => text(["pnpm", "list", "-g", "--depth=0"]) },
            { name: "bun", command: () => text(["bun", "pm", "ls", "-g"]) },
            { name: "brew", command: () => text(["brew", "list", "--formula", "malibu"]) },
            { name: "scoop", command: () => text(["scoop", "list", "malibu"]) },
            { name: "choco", command: () => text(["choco", "list", "--limit-output", "malibu"]) },
          ]

          checks.sort((a, b) => {
            const aMatches = exec.includes(a.name)
            const bMatches = exec.includes(b.name)
            if (aMatches && !bMatches) return -1
            if (!aMatches && bMatches) return 1
            return 0
          })

          for (const check of checks) {
            const output = yield* check.command()
            const installedName =
              check.name === "brew" || check.name === "choco" || check.name === "scoop" ? "malibu" : "malibu-ai"
            if (output.includes(installedName)) {
              return check.name
            }
          }

          return "unknown" as Method
        })

        const latestImpl = Effect.fn("Installation.latest")(function* (installMethod?: Method) {
          const detectedMethod = installMethod || (yield* methodImpl())

          if (detectedMethod === "brew") {
            const formula = yield* getBrewFormula()
            if (formula.includes("/")) {
              const infoJson = yield* text(["brew", "info", "--json=v2", formula])
              const info = yield* Schema.decodeUnknownEffect(Schema.fromJsonString(BrewInfoV2))(infoJson)
              return info.formulae[0].versions.stable
            }
            const response = yield* httpOk.execute(
              HttpClientRequest.get("https://formulae.brew.sh/api/formula/malibu.json").pipe(
                HttpClientRequest.acceptJson,
              ),
            )
            const data = yield* HttpClientResponse.schemaBodyJson(BrewFormula)(response)
            return data.versions.stable
          }

          if (detectedMethod === "npm" || detectedMethod === "bun" || detectedMethod === "pnpm") {
            const r = (yield* text(["npm", "config", "get", "registry"])).trim()
            const reg = r || "https://registry.npmjs.org"
            const registry = reg.endsWith("/") ? reg.slice(0, -1) : reg
            const channel = CHANNEL
            const response = yield* httpOk.execute(
              HttpClientRequest.get(`${registry}/malibu-ai/${channel}`).pipe(HttpClientRequest.acceptJson),
            )
            const data = yield* HttpClientResponse.schemaBodyJson(NpmPackage)(response)
            return data.version
          }

          if (detectedMethod === "choco") {
            const response = yield* httpOk.execute(
              HttpClientRequest.get(
                "https://community.chocolatey.org/api/v2/Packages?$filter=Id%20eq%20%27malibu%27%20and%20IsLatestVersion&$select=Version",
              ).pipe(HttpClientRequest.setHeaders({ Accept: "application/json;odata=verbose" })),
            )
            const data = yield* HttpClientResponse.schemaBodyJson(ChocoPackage)(response)
            return data.d.results[0].Version
          }

          if (detectedMethod === "scoop") {
            const response = yield* httpOk.execute(
              HttpClientRequest.get(
                "https://raw.githubusercontent.com/ScoopInstaller/Main/master/bucket/malibu.json",
              ).pipe(HttpClientRequest.setHeaders({ Accept: "application/json" })),
            )
            const data = yield* HttpClientResponse.schemaBodyJson(ScoopManifest)(response)
            return data.version
          }

          const response = yield* httpOk.execute(
            HttpClientRequest.get("https://api.github.com/repos/obinopaul/malibu/releases/latest").pipe(
              HttpClientRequest.acceptJson,
            ),
          )
          const data = yield* HttpClientResponse.schemaBodyJson(GitHubRelease)(response)
          return data.tag_name.replace(/^v/, "")
        }, Effect.orDie)

        const upgradeImpl = Effect.fn("Installation.upgrade")(function* (m: Method, target: string) {
          let result: { code: ChildProcessSpawner.ExitCode; stdout: string; stderr: string } | undefined
          switch (m) {
            case "curl":
              result = yield* upgradeCurl(target)
              break
            case "npm":
              result = yield* run(["npm", "install", "-g", `malibu-ai@${target}`])
              break
            case "pnpm":
              result = yield* run(["pnpm", "install", "-g", `malibu-ai@${target}`])
              break
            case "bun":
              result = yield* run(["bun", "install", "-g", `malibu-ai@${target}`])
              break
            case "brew": {
              const formula = yield* getBrewFormula()
              const env = { HOMEBREW_NO_AUTO_UPDATE: "1" }
              if (formula.includes("/")) {
                const tap = yield* run(["brew", "tap", "obinopaul/tap"], { env })
                if (tap.code !== 0) {
                  result = tap
                  break
                }
                const repo = yield* text(["brew", "--repo", "obinopaul/tap"])
                const dir = repo.trim()
                if (dir) {
                  const pull = yield* run(["git", "pull", "--ff-only"], { cwd: dir, env })
                  if (pull.code !== 0) {
                    result = pull
                    break
                  }
                }
              }
              result = yield* run(["brew", "upgrade", formula], { env })
              break
            }
            case "choco":
              result = yield* run(["choco", "upgrade", "malibu", `--version=${target}`, "-y"])
              break
            case "scoop":
              result = yield* run(["scoop", "install", `malibu@${target}`])
              break
            default:
              return yield* new UpgradeFailedError({ stderr: `Unknown method: ${m}` })
          }
          if (!result || result.code !== 0) {
            const stderr = m === "choco" ? "not running from an elevated command shell" : result?.stderr || ""
            return yield* new UpgradeFailedError({ stderr })
          }
          log.info("upgraded", {
            method: m,
            target,
            stdout: result.stdout,
            stderr: result.stderr,
          })
          yield* text([process.execPath, "--version"])
        })

        return Service.of({
          info: Effect.fn("Installation.info")(function* () {
            return {
              version: VERSION,
              latest: yield* latestImpl(),
            }
          }),
          method: methodImpl,
          latest: latestImpl,
          upgrade: upgradeImpl,
        })
      }),
    )

  export const defaultLayer = layer.pipe(
    Layer.provide(FetchHttpClient.layer),
    Layer.provide(NodeChildProcessSpawner.layer),
    Layer.provide(NodeFileSystem.layer),
    Layer.provide(NodePath.layer),
  )

  const runPromise = makeRunPromise(Service, defaultLayer)

  export async function info(): Promise<Info> {
    return runPromise((svc) => svc.info())
  }

  export async function method(): Promise<Method> {
    return runPromise((svc) => svc.method())
  }

  export async function latest(installMethod?: Method): Promise<string> {
    return runPromise((svc) => svc.latest(installMethod))
  }

  export async function upgrade(m: Method, target: string): Promise<void> {
    return runPromise((svc) => svc.upgrade(m, target))
  }
}
