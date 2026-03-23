"use client"

import { useMemo, useState } from "react"

type Mode = "deg" | "rad"
type Tab = "main" | "unit"
type Unit = "length" | "temp" | "weight"

const ops = [
  ["sin", "cos", "tan", "ln", "log"],
  ["(", ")", "^", "√", "%"],
  ["7", "8", "9", "÷", "AC"],
  ["4", "5", "6", "×", "⌫"],
  ["1", "2", "3", "-", "π"],
  ["0", ".", "+/-", "+", "="],
]

const units = {
  length: {
    label: "Length",
    list: ["m", "km", "mi", "ft"],
  },
  temp: {
    label: "Temperature",
    list: ["C", "F", "K"],
  },
  weight: {
    label: "Weight",
    list: ["kg", "g", "lb", "oz"],
  },
} as const

function angle(v: number, mode: Mode) {
  if (mode === "deg") return (v * Math.PI) / 180
  return v
}

function fact(v: number) {
  if (!Number.isInteger(v) || v < 0) return Number.NaN
  return Array.from({ length: v }, (_, i) => i + 1).reduce((a, b) => a * b, 1)
}

function evalx(input: string, mode: Mode) {
  const expr = input
    .replace(/÷/g, "/")
    .replace(/×/g, "*")
    .replace(/π/g, `${Math.PI}`)
    .replace(/√\(/g, "sqrt(")
    .replace(/√/g, "sqrt")
    .replace(/\^/g, "**")
    .replace(/(\d+(?:\.\d+)?)%/g, "($1/100)")

  const fn = Function("sin", "cos", "tan", "ln", "log", "sqrt", "fact", `return (${expr})`)

  return fn(
    (v: number) => Math.sin(angle(v, mode)),
    (v: number) => Math.cos(angle(v, mode)),
    (v: number) => Math.tan(angle(v, mode)),
    (v: number) => Math.log(v),
    (v: number) => Math.log10(v),
    (v: number) => Math.sqrt(v),
    fact,
  )
}

function convert(cat: Unit, from: string, to: string, v: number) {
  if (cat === "length") {
    const base = from === "m" ? v : from === "km" ? v * 1000 : from === "mi" ? v * 1609.344 : v * 0.3048
    return to === "m" ? base : to === "km" ? base / 1000 : to === "mi" ? base / 1609.344 : base / 0.3048
  }

  if (cat === "temp") {
    const base = from === "C" ? v : from === "F" ? ((v - 32) * 5) / 9 : v - 273.15
    return to === "C" ? base : to === "F" ? (base * 9) / 5 + 32 : base + 273.15
  }

  const base = from === "kg" ? v : from === "g" ? v / 1000 : from === "lb" ? v * 0.45359237 : v * 0.0283495231
  return to === "kg" ? base : to === "g" ? base * 1000 : to === "lb" ? base / 0.45359237 : base / 0.0283495231
}

export default function Home() {
  const [tab, setTab] = useState<Tab>("main")
  const [mode, setMode] = useState<Mode>("deg")
  const [expr, setExpr] = useState("")
  const [view, setView] = useState("0")
  const [log, setLog] = useState<string[]>([])
  const [cat, setCat] = useState<Unit>("length")
  const [from, setFrom] = useState("m")
  const [to, setTo] = useState("km")
  const [raw, setRaw] = useState("1")

  const ans = useMemo(() => {
    const v = Number(raw)
    if (Number.isNaN(v)) return "—"
    return convert(cat, from, to, v).toFixed(4)
  }, [cat, from, raw, to])

  const push = (key: string) => {
    if (key === "AC") {
      setExpr("")
      setView("0")
      return
    }

    if (key === "⌫") {
      const next = expr.slice(0, -1)
      setExpr(next)
      setView(next || "0")
      return
    }

    if (key === "+/-") {
      const next = expr.startsWith("-") ? expr.slice(1) : `-${expr || "0"}`
      setExpr(next)
      setView(next)
      return
    }

    if (key === "=") {
      try {
        const out = evalx(expr, mode)
        const next = Number.isFinite(out) ? `${out}` : "Error"
        if (next !== "Error") setLog((s) => [`${expr} = ${next}`, ...s].slice(0, 6))
        setExpr(next === "Error" ? "" : next)
        setView(next)
      } catch {
        setExpr("")
        setView("Error")
      }
      return
    }

    const map =
      key === "sin" || key === "cos" || key === "tan" || key === "ln" || key === "log"
        ? `${key}(`
        : key === "√"
          ? "√("
          : key

    const next = `${expr}${map}`
    setExpr(next)
    setView(next)
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#07111f] text-white">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(117,219,255,0.22),_transparent_25%),radial-gradient(circle_at_85%_15%,_rgba(191,90,242,0.22),_transparent_25%),radial-gradient(circle_at_bottom,_rgba(255,174,79,0.18),_transparent_30%)]" />
      <div className="pointer-events-none absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] [background-size:72px_72px]" />

      <section className="relative mx-auto flex min-h-screen max-w-7xl flex-col gap-10 px-6 py-10 lg:flex-row lg:items-stretch lg:px-10">
        <div className="flex flex-1 flex-col justify-between rounded-[2rem] border border-white/10 bg-white/8 p-8 shadow-[0_40px_120px_rgba(2,8,23,0.8)] backdrop-blur-2xl">
          <div className="space-y-8">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="font-mono text-xs uppercase tracking-[0.45em] text-cyan-200/80">NovaCalc X</p>
                <h1 className="mt-3 max-w-xl text-5xl font-black tracking-[-0.06em] text-white sm:text-7xl">
                  An advanced calculator with a luxury control-panel soul.
                </h1>
              </div>
              <div className="rounded-full border border-white/15 bg-black/20 px-4 py-2 text-sm text-white/70">
                Local Next.js app
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {[
                ["Scientific", "Trig, logs, roots, powers, constants"],
                ["Converter", "Length, temperature, and weight modes"],
                ["Memory", "Recent expressions stay visible while you work"],
              ].map(([title, copy]) => (
                <div key={title} className="rounded-[1.5rem] border border-white/10 bg-white/6 p-5">
                  <p className="text-sm font-semibold uppercase tracking-[0.3em] text-cyan-200/70">{title}</p>
                  <p className="mt-3 text-sm leading-7 text-white/72">{copy}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-10 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {log.length ? (
              log.map((item, i) => (
                <div
                  key={`${item}-${i}`}
                  className="rounded-[1.25rem] border border-white/10 bg-black/20 p-4 font-mono text-sm text-white/70"
                >
                  {item}
                </div>
              ))
            ) : (
              <div className="rounded-[1.25rem] border border-dashed border-white/15 bg-black/10 p-4 text-sm text-white/45 xl:col-span-3">
                Your solved expressions will glow here.
              </div>
            )}
          </div>
        </div>

        <div className="w-full max-w-2xl rounded-[2rem] border border-white/10 bg-[#0b1728]/95 p-5 shadow-[0_20px_80px_rgba(8,15,35,0.8)] backdrop-blur-xl">
          <div className="flex gap-3 rounded-full border border-white/10 bg-white/5 p-2">
            {[
              ["main", "Calculator"],
              ["unit", "Converter"],
            ].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id as Tab)}
                className={`flex-1 rounded-full px-4 py-3 text-sm font-semibold transition ${
                  tab === id ? "bg-white text-slate-900" : "text-white/65 hover:bg-white/8"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "main" ? (
            <div className="mt-5 space-y-4">
              <div className="rounded-[1.75rem] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.11),rgba(255,255,255,0.03))] p-5">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em] text-white/45">
                  <span>Expression</span>
                  <button
                    onClick={() => setMode((s) => (s === "deg" ? "rad" : "deg"))}
                    className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-cyan-100"
                  >
                    {mode}
                  </button>
                </div>
                <p className="mt-5 min-h-8 break-all font-mono text-sm text-cyan-100/75">{expr || "Ready for input"}</p>
                <p className="mt-3 break-all text-right font-mono text-5xl font-semibold tracking-[-0.04em] text-white sm:text-6xl">
                  {view}
                </p>
              </div>

              <div className="grid grid-cols-5 gap-3">
                {ops.flat().map((key) => {
                  const hot = ["=", "+", "-", "×", "÷"].includes(key)
                  const glow = ["sin", "cos", "tan", "ln", "log", "√", "^", "%"].includes(key)
                  return (
                    <button
                      key={key}
                      onClick={() => push(key)}
                      className={`h-16 rounded-[1.35rem] border text-lg font-semibold transition duration-200 hover:-translate-y-0.5 ${
                        hot
                          ? "border-transparent bg-[linear-gradient(135deg,#9ef7ff,#7f8cff_52%,#f0a8ff)] text-slate-950 shadow-[0_12px_30px_rgba(127,140,255,0.35)]"
                          : glow
                            ? "border-cyan-300/15 bg-cyan-300/8 text-cyan-100 hover:bg-cyan-300/15"
                            : "border-white/10 bg-white/6 text-white hover:bg-white/12"
                      }`}
                    >
                      {key}
                    </button>
                  )
                })}
              </div>
            </div>
          ) : (
            <div className="mt-5 space-y-4">
              <div className="rounded-[1.75rem] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.11),rgba(255,255,255,0.03))] p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-white/45">Smart converter</p>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  {(Object.keys(units) as Unit[]).map((id) => (
                    <button
                      key={id}
                      onClick={() => {
                        setCat(id)
                        setFrom(units[id].list[0])
                        setTo(units[id].list[1])
                      }}
                      className={`rounded-[1.25rem] border px-4 py-4 text-left transition ${
                        cat === id ? "border-cyan-300/35 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/8"
                      }`}
                    >
                      <p className="font-semibold text-white">{units[id].label}</p>
                      <p className="mt-1 text-sm text-white/55">Precision with instant output</p>
                    </button>
                  ))}
                </div>
                <div className="mt-5 grid gap-3 md:grid-cols-[1.3fr,1fr,1fr]">
                  <input
                    value={raw}
                    onChange={(e) => setRaw(e.target.value)}
                    className="rounded-[1.2rem] border border-white/10 bg-black/20 px-4 py-4 text-lg outline-none placeholder:text-white/25"
                    placeholder="Enter a number"
                  />
                  <select
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                    className="rounded-[1.2rem] border border-white/10 bg-black/20 px-4 py-4 outline-none"
                  >
                    {units[cat].list.map((item) => (
                      <option key={item} value={item} className="bg-slate-900">
                        {item}
                      </option>
                    ))}
                  </select>
                  <select
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    className="rounded-[1.2rem] border border-white/10 bg-black/20 px-4 py-4 outline-none"
                  >
                    {units[cat].list.map((item) => (
                      <option key={item} value={item} className="bg-slate-900">
                        {item}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="mt-5 rounded-[1.5rem] border border-emerald-300/20 bg-emerald-300/10 p-5">
                  <p className="text-xs uppercase tracking-[0.3em] text-emerald-100/60">Converted value</p>
                  <p className="mt-3 font-mono text-4xl font-semibold tracking-[-0.05em] text-emerald-50">{ans}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  )
}
