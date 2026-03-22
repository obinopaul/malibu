/**
 * Bun preload plugin — forces `langchain` to resolve to its Node.js entry
 * instead of the browser entry.
 *
 * The `--conditions=browser` flag (needed for solid-js / @opentui TUI)
 * causes `langchain` to resolve to `dist/browser.js` which is missing
 * exports like `countTokensApproximately` that `deepagents` needs.
 */
import { plugin } from "bun"

plugin({
  name: "langchain-node-resolver",
  setup(build) {
    // Intercept bare "langchain" imports and force the Node entry point
    build.onResolve({ filter: /^langchain$/ }, (args) => {
      return {
        path: "langchain/dist/index.js",
        namespace: "node-resolve",
      }
    })
  },
})
