<p align="center">
  <h1 align="center">Malibu</h1>
</p>
<p align="center">The open source AI coding agent for the terminal.</p>
<p align="center">
  <a href="https://www.npmjs.com/package/malibu-ai"><img alt="npm" src="https://img.shields.io/npm/v/malibu-ai?style=flat-square" /></a>
  <a href="https://github.com/obinopaul/malibu/actions/workflows/release.yml"><img alt="Build status" src="https://img.shields.io/github/actions/workflow/status/obinopaul/malibu/release.yml?style=flat-square&branch=main" /></a>
  <a href="https://github.com/obinopaul/malibu"><img alt="GitHub stars" src="https://img.shields.io/github/stars/obinopaul/malibu?style=flat-square" /></a>
</p>

---

### Installation

```bash
# Quick install (curl)
curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash

# npm (all platforms)
npm i -g malibu-ai@latest          # or bun/pnpm/yarn
```

#### Installation Directory

The install script respects the following priority order for the installation path:

1. `$MALIBU_INSTALL_DIR` - Custom installation directory
2. `$XDG_BIN_DIR` - XDG Base Directory Specification compliant path
3. `$HOME/bin` - Standard user binary directory (if it exists)
4. `$HOME/.malibu/bin` - Default fallback

```bash
# Examples
MALIBU_INSTALL_DIR=/usr/local/bin curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash
XDG_BIN_DIR=$HOME/.local/bin curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash
```

### Agents

Malibu includes two built-in agents you can switch between with the `Tab` key.

- **build** - Default, full-access agent for development work
- **plan** - Read-only agent for analysis and code exploration
  - Denies file edits by default
  - Asks permission before running bash commands
  - Ideal for exploring unfamiliar codebases or planning changes

Also included is a **general** subagent for complex searches and multistep tasks.
This is used internally and can be invoked using `@general` in messages.

### Features

- Provider-agnostic: works with Claude, OpenAI, Google, or local models
- 100% open source (MIT)
- Out-of-the-box LSP support
- Terminal UI (TUI) focused
- Client/server architecture
- MCP (Model Context Protocol) support

### Development

```bash
# Clone and install
git clone https://github.com/obinopaul/malibu.git
cd malibu
bun install

# Run in dev mode
bun run dev
```

### Contributing

If you're interested in contributing to Malibu, please read our [contributing docs](./CONTRIBUTING.md) before submitting a pull request.

### FAQ

#### How is this different from Claude Code?

It's very similar to Claude Code in terms of capability. Here are the key differences:

- 100% open source
- Not coupled to any provider. Malibu can be used with Claude, OpenAI, Google, or even local models. As models evolve, the gaps between them will close and pricing will drop, so being provider-agnostic is important.
- Out-of-the-box LSP support
- A focus on TUI — pushing the limits of what's possible in the terminal.
- A client/server architecture. This, for example, can allow Malibu to run on your computer while you drive it remotely from a mobile app.

---

**GitHub:** [obinopaul/malibu](https://github.com/obinopaul/malibu)
