/**
 * Bun preload plugin — forces `langchain` to resolve to its Node.js entry
 * instead of the browser entry.
 *
 * The `--conditions=browser` flag (needed for solid-js / @opentui TUI)
 * causes `langchain` to resolve to `dist/browser.js` which is missing
 * exports like `countTokensApproximately` that `deepagents` needs.
 */
import { plugin } from "bun"
import { resolve } from "path"

// Resolve the Node entry point for langchain relative to this script.
// The `--conditions=browser` flag (needed for solid-js / @opentui TUI)
// causes langchain to resolve to `dist/browser.js` which lacks exports
// like `countTokensApproximately` that `deepagents` needs.
const langchainNodeEntry = resolve(
  import.meta.dir,
  "../node_modules/langchain/dist/index.js",
)

plugin({
  name: "langchain-node-resolver",
  setup(build) {
    build.onResolve({ filter: /^langchain$/ }, () => {
      return { path: langchainNodeEntry }
    })
  },
})
