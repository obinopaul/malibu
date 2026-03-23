// ── State ──────────────────────────────────────
let expr = ""
let mode = "deg" // deg | rad
let memory = 0
let history = []
let second = false

const $expr = document.getElementById("expression")
const $result = document.getElementById("result")
const $history = document.getElementById("history-panel")
const $histList = document.getElementById("history-list")

// ── Input helpers ─────────────────────────────
function input(val) {
  expr += val
  render()
}

function inputFn(fn) {
  expr += fn
  render()
}

function backspace() {
  // Remove a whole function name if at the end, otherwise single char
  const fns = [
    "sin(",
    "cos(",
    "tan(",
    "asin(",
    "acos(",
    "atan(",
    "sinh(",
    "cosh(",
    "tanh(",
    "log(",
    "ln(",
    "sqrt(",
    "abs(",
    "fact(",
  ]
  for (const fn of fns) {
    if (expr.endsWith(fn)) {
      expr = expr.slice(0, -fn.length)
      render()
      return
    }
  }
  expr = expr.slice(0, -1)
  render()
}

function clearAll() {
  expr = ""
  $result.textContent = "0"
  $result.classList.remove("error")
  $expr.textContent = ""
}

function negate() {
  if (!expr) return
  // Wrap current expression in negation
  expr = `(-(${expr}))`
  render()
}

// ── Angle mode ────────────────────────────────
function setAngleMode(m) {
  mode = m
  document.getElementById("deg-btn").classList.toggle("active", m === "deg")
  document.getElementById("rad-btn").classList.toggle("active", m === "rad")
}

// ── 2nd function toggle ───────────────────────
function toggleSecond() {
  second = !second
  document.getElementById("second-btn").classList.toggle("active", second)

  const sinBtn = document.getElementById("sin-btn")
  const cosBtn = document.getElementById("cos-btn")
  const tanBtn = document.getElementById("tan-btn")

  if (second) {
    sinBtn.textContent = "asin"
    sinBtn.onclick = () => inputFn("asin(")
    cosBtn.textContent = "acos"
    cosBtn.onclick = () => inputFn("acos(")
    tanBtn.textContent = "atan"
    tanBtn.onclick = () => inputFn("atan(")
  } else {
    sinBtn.textContent = "sin"
    sinBtn.onclick = () => inputFn("sin(")
    cosBtn.textContent = "cos"
    cosBtn.onclick = () => inputFn("cos(")
    tanBtn.textContent = "tan"
    tanBtn.onclick = () => inputFn("tan(")
  }
}

// ── Memory ────────────────────────────────────
function memoryStore() {
  const val = parseFloat($result.textContent)
  if (!isNaN(val)) memory = val
}

function memoryRecall() {
  input(String(memory))
}

function memoryClear() {
  memory = 0
}

function memoryAdd() {
  const val = parseFloat($result.textContent)
  if (!isNaN(val)) memory += val
}

// ── Render ────────────────────────────────────
function render() {
  $expr.textContent = beautify(expr)

  // Live preview
  try {
    const val = compute(expr)
    if (val !== undefined && !isNaN(val) && isFinite(val)) {
      $result.textContent = format(val)
      $result.classList.remove("error")
    }
  } catch {
    // Keep previous result during typing
  }
}

function beautify(str) {
  return str.replace(/\*/g, "×").replace(/\//g, "÷").replace(/pi/g, "π").replace(/PI/g, "π")
}

function format(num) {
  if (Number.isInteger(num) && Math.abs(num) < 1e15) return num.toString()
  const s = num.toPrecision(12)
  // Remove trailing zeros
  return parseFloat(s).toString()
}

// ── Evaluate ──────────────────────────────────
function evaluate() {
  if (!expr) return

  try {
    const val = compute(expr)
    if (val === undefined || isNaN(val)) throw new Error("Invalid")

    const display = beautify(expr)

    // Add to history
    history.unshift({ expr: display, result: format(val) })
    if (history.length > 50) history.pop()
    renderHistory()

    $expr.textContent = display + " ="
    $result.textContent = format(val)
    $result.classList.remove("error")
    $result.classList.remove("pop")
    void $result.offsetWidth // trigger reflow
    $result.classList.add("pop")

    expr = format(val)
  } catch (err) {
    $result.textContent = "Error"
    $result.classList.add("error")
  }
}

// ── Compute (safe math parser) ────────────────
function compute(raw) {
  let s = raw
    .replace(/π/g, `(${Math.PI})`)
    .replace(/(?<![a-zA-Z])e(?![a-zA-Z])/g, `(${Math.E})`)
    .replace(/×/g, "*")
    .replace(/÷/g, "/")
    .replace(/\^/g, "**")

  // Auto-close open parens
  const open = (s.match(/\(/g) || []).length
  const close = (s.match(/\)/g) || []).length
  s += ")".repeat(Math.max(0, open - close))

  // Replace math functions with our safe versions
  s = s.replace(/sin\(/g, "_sin(")
  s = s.replace(/cos\(/g, "_cos(")
  s = s.replace(/tan\(/g, "_tan(")
  s = s.replace(/asin\(/g, "_asin(")
  s = s.replace(/acos\(/g, "_acos(")
  s = s.replace(/atan\(/g, "_atan(")
  s = s.replace(/sinh\(/g, "_sinh(")
  s = s.replace(/cosh\(/g, "_cosh(")
  s = s.replace(/tanh\(/g, "_tanh(")
  s = s.replace(/log\(/g, "_log(")
  s = s.replace(/ln\(/g, "_ln(")
  s = s.replace(/sqrt\(/g, "_sqrt(")
  s = s.replace(/abs\(/g, "_abs(")
  s = s.replace(/fact\(/g, "_fact(")

  // Validate: only allow safe characters
  if (/[^0-9+\-*/()._%,\s]/.test(s)) throw new Error("Invalid characters")

  // Build safe function context
  const toRad = (x) => (mode === "deg" ? (x * Math.PI) / 180 : x)
  const fromRad = (x) => (mode === "deg" ? (x * 180) / Math.PI : x)

  const ctx = {
    _sin: (x) => Math.sin(toRad(x)),
    _cos: (x) => Math.cos(toRad(x)),
    _tan: (x) => Math.tan(toRad(x)),
    _asin: (x) => fromRad(Math.asin(x)),
    _acos: (x) => fromRad(Math.acos(x)),
    _atan: (x) => fromRad(Math.atan(x)),
    _sinh: (x) => Math.sinh(x),
    _cosh: (x) => Math.cosh(x),
    _tanh: (x) => Math.tanh(x),
    _log: (x) => Math.log10(x),
    _ln: (x) => Math.log(x),
    _sqrt: (x) => Math.sqrt(x),
    _abs: (x) => Math.abs(x),
    _fact: (n) => {
      n = Math.round(n)
      if (n < 0 || n > 170) return NaN
      if (n === 0 || n === 1) return 1
      let r = 1
      for (let i = 2; i <= n; i++) r *= i
      return r
    },
  }

  // Use Function constructor with safe context
  const keys = Object.keys(ctx)
  const vals = Object.values(ctx)
  const fn = new Function(...keys, `"use strict"; return (${s})`)
  return fn(...vals)
}

// ── History ───────────────────────────────────
function toggleHistory() {
  $history.classList.toggle("open")
}

function renderHistory() {
  $histList.innerHTML = ""
  for (const item of history) {
    const div = document.createElement("div")
    div.className = "history-item"
    div.innerHTML = `<div class="hist-expr">${item.expr}</div><div class="hist-result">${item.result}</div>`
    div.onclick = () => {
      expr = item.result
      render()
      $history.classList.remove("open")
    }
    $histList.appendChild(div)
  }
}

function clearHistory() {
  history = []
  renderHistory()
}

// ── Keyboard support ──────────────────────────
document.addEventListener("keydown", (e) => {
  const key = e.key

  if (key >= "0" && key <= "9") input(key)
  else if (key === ".") input(".")
  else if (key === "+") input("+")
  else if (key === "-") input("-")
  else if (key === "*") input("×")
  else if (key === "/") {
    e.preventDefault()
    input("÷")
  } else if (key === "%") input("%")
  else if (key === "(") input("(")
  else if (key === ")") input(")")
  else if (key === "^") input("^")
  else if (key === "Enter" || key === "=") {
    e.preventDefault()
    evaluate()
  } else if (key === "Backspace") backspace()
  else if (key === "Escape") clearAll()
  else if (key === "p") input("π")
})
