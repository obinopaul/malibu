# RELEASES

How Malibu's release system works, every file involved, and how to publish new versions.

## How It All Fits Together

Malibu uses **GitHub Actions** for CI/CD (Continuous Integration / Continuous Delivery). Here's the big picture:

```
You write code
    |
    v
git commit + git push          <-- pushes code to GitHub (no release happens)
    |                              CI runs: typecheck + tests
    v
git tag v0.2.0                 <-- creates a version tag locally
git push origin v0.2.0         <-- pushes the tag to GitHub
    |
    v
GitHub Actions detects the tag  <-- the "v*" pattern in release.yml triggers
    |
    v
Release workflow runs automatically:
  1. Builds binaries for all platforms (Linux, macOS, Windows)
  2. Creates a GitHub Release with downloadable archives
  3. Publishes to npm registry
  4. Pushes Docker image to ghcr.io
  5. Updates Homebrew tap and AUR package
    |
    v
Users can now install via:
  curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash
```

## What Is CI/CD?

**CI (Continuous Integration)** = automatically testing/building your code when you push changes.

**CD (Continuous Delivery)** = automatically publishing/deploying your code when you're ready to release.

In Malibu's case:
- **CI** happens on every push to main and on pull requests (GitHub Actions runs typecheck + tests)
- **CI also runs locally** before every push (the Husky pre-push hook runs `bun typecheck`)
- **CD** happens when you push a git tag (GitHub Actions builds, packages, and publishes the release)

---

## Every File Involved in CI/CD

Here's a complete map of every file that plays a role in the pipeline:

### GitHub Actions Workflows (`.github/workflows/`)

| File | Trigger | What It Does |
|------|---------|-------------|
| `.github/workflows/ci.yml` | Every push to `main` + every PR | Runs typecheck (`bun run typecheck`) and tests (`bun test`) |
| `.github/workflows/release.yml` | Push of a `v*` tag | Builds binaries, creates GitHub Release, publishes to npm |

### Required Project Files

| File | Purpose | What Happens If Missing |
|------|---------|------------------------|
| `.github/TEAM_MEMBERS` | List of GitHub usernames (one per line) for the team. Used by the build script (`packages/script/src/index.ts`) to identify team members. | **Build fails** with `ENOENT: no such file or directory` |
| `install` | Bash script at project root. Users run this via `curl \| bash` to install Malibu on their machine. | Users can't install via the one-liner curl command |
| `packages/opencode/package.json` | Contains the `"version"` field (e.g., `"0.1.0"`). This is the source of truth for Malibu's version. | Build won't know the version |

### Build & Publish Scripts (`packages/opencode/script/`)

| File | Used By | What It Does |
|------|---------|-------------|
| `script/build.ts` | Release workflow (Job 1) | Compiles Malibu into standalone binaries for 11 platform targets (Linux x64/arm64, macOS x64/arm64, Windows x64/arm64, plus musl and baseline variants). Uses `Bun.build()` with compile mode. |
| `script/publish.ts` | Release workflow (Job 3) | Publishes all platform binaries to npm, pushes Docker images to `ghcr.io`, updates AUR (Arch Linux) package, and updates Homebrew tap. |
| `script/preload-langchain.ts` | `bun dev` (development only) | Bun preload plugin that forces langchain to resolve to Node entry. Only used during development, not in builds. |
| `script/postinstall.mjs` | npm package | Runs after `npm install malibu-ai` — downloads the correct platform binary. |

### Version Logic (`packages/script/src/index.ts`)

This file determines the version number used during builds. The logic is:

1. If `MALIBU_VERSION` env var is set (e.g., by the release workflow) --> use that
2. If on a non-main branch --> generate a preview version like `0.0.0-branchname-202603241200`
3. Otherwise --> fetch the latest version from npm and bump it

The release workflow sets `MALIBU_VERSION` to the tag name (e.g., `v0.1.0`), so in release builds, the version always comes from the git tag.

### Local Git Hooks (`.husky/`)

| File | When It Runs | What It Does |
|------|-------------|-------------|
| `.husky/pre-push` | Before every `git push` | 1. Checks that your Bun version matches `package.json`'s `packageManager` field. 2. Runs `bun typecheck` (via Turbo, across all packages). If typecheck fails, the push is **blocked**. |

This is powered by [Husky](https://typicode.github.io/husky/). It's installed automatically when you run `bun install` (via the `"prepare": "husky"` script in root `package.json`).

### Monorepo Build Tool (`turbo.json`)

Turborepo coordinates tasks across the monorepo's 5 packages. When you run `bun typecheck`, Turbo runs typecheck in all packages in parallel and caches results. If nothing changed, it replays from cache ("FULL TURBO").

### Dependency Patches (`patches/`)

Bun's patch system lets you fix bugs in dependencies without forking them. These are applied automatically on `bun install`. Current patches:

| Patch | Why |
|-------|-----|
| `langchain@1.2.34.patch` | Removes the `"browser"` export entry so langchain always resolves to the Node entry (which has all exports like `countTokensApproximately`) |
| `solid-js@1.9.10.patch` | Fixes a transition bug in Solid.js reactivity |
| `@openrouter/ai-sdk-provider@1.5.4.patch` | Fix for OpenRouter AI SDK |
| `@ai-sdk/xai@2.0.51.patch` | Fix for xAI SDK |

Patches are registered in root `package.json` under `"patchedDependencies"`.

---

## The Release Workflow In Detail

The file `.github/workflows/release.yml` defines what happens when a tag is pushed. It has **3 jobs**:

### Job 1: `build` (Build binaries)

```
Trigger: push a tag matching "v*" (e.g., v0.1.0, v0.2.0)
Runs on: ubuntu-latest
```

Steps:
1. Checks out the code (`actions/checkout@v4`)
2. Installs Bun 1.3.10 (`oven-sh/setup-bun@v2`)
3. Runs `bun install` (installs dependencies + applies patches)
4. Runs `bun run build` in `packages/opencode/` — this invokes `script/build.ts` which:
   - Fetches model definitions from `models.dev/api.json`
   - Loads database migration SQL files
   - Compiles 11 platform binaries using `Bun.build()` with compile mode
   - Runs a smoke test on the current-platform binary (`malibu --version`)
5. Uploads built binaries as GitHub Actions artifacts

The version comes from the tag via `MALIBU_VERSION: ${{ github.ref_name }}`.

### Job 2: `release` (Create GitHub Release)

```
Depends on: Job 1 (waits for build to finish)
Runs on: ubuntu-latest
```

Steps:
1. Downloads the built binaries from Job 1
2. Packages them into archives:
   - `.tar.gz` for Linux targets
   - `.zip` for macOS and Windows targets
3. Creates a GitHub Release page using `softprops/action-gh-release@v2`
   - Auto-generates release notes from commits since last tag
   - Attaches all `.tar.gz` and `.zip` archives as downloadable files

### Job 3: `publish-npm` (Publish to npm + registries)

```
Depends on: Job 1 (waits for build to finish)
Runs on: ubuntu-latest
Only runs for STABLE releases (tags WITHOUT a hyphen — v0.2.0 yes, v0.2.0-beta.1 no)
```

Steps (via `script/publish.ts`):
1. Publishes each platform binary as a separate npm package
2. Publishes the main `malibu-ai` package to npm
3. Builds and pushes Docker images to `ghcr.io/obinopaul/malibu`
4. Updates the AUR (Arch Linux User Repository) `malibu-bin` package
5. Updates the Homebrew tap at `obinopaul/homebrew-tap`

---

## The CI Workflow

The file `.github/workflows/ci.yml` runs on every push to `main` and on every pull request:

1. **Type Check** — runs `bun run typecheck` (Turbo runs `tsgo --noEmit` across all packages)
2. **Test** — runs `bun test --timeout 30000` in `packages/opencode/`

This catches type errors and test failures before they reach main.

---

## How Users Install Malibu

When someone runs:
```bash
curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash
```

The `install` script (at project root, ~475 lines) does:
1. Queries the GitHub API for the latest release: `https://api.github.com/repos/obinopaul/malibu/releases/latest`
2. Extracts the version number from `tag_name` (e.g., `v0.2.0` becomes `0.2.0`)
3. Falls back to reading `packages/opencode/package.json` version if no releases exist
4. Detects the user's OS and architecture (linux-x64, darwin-arm64, etc.)
5. Downloads the matching binary archive from the GitHub Release
6. Extracts it and installs the `malibu` binary to `~/.local/bin/`
7. Adds the bin directory to the user's PATH if needed

Install a specific version:
```bash
curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash -s -- --version 0.2.0
```

---

## How To Publish a New Release

### Step 1: Make your code changes

```bash
# Edit files, fix bugs, add features...
git add .
git commit -m "description of changes"
git push origin main
```

This pushes your code but does NOT create a release. CI will run typecheck + tests.

### Step 2: Update the version number

Edit `packages/opencode/package.json` and bump the `"version"` field:

```json
"version": "0.2.0"
```

**Version numbering (Semantic Versioning):**
- `0.1.0` -> `0.1.1` = **patch** (bug fixes, small changes)
- `0.1.0` -> `0.2.0` = **minor** (new features, backwards compatible)
- `0.9.0` -> `1.0.0` = **major** (breaking changes, first stable release)

Commit the version bump:
```bash
git add packages/opencode/package.json
git commit -m "bump version to 0.2.0"
git push origin main
```

### Step 3: Create and push a tag

```bash
git tag v0.2.0
git push origin v0.2.0
```

That's it. GitHub Actions takes over and automatically builds, packages, and publishes everything.

### Step 4: Verify

1. Go to `https://github.com/obinopaul/malibu/actions` to watch the workflow run
2. Once complete, check `https://github.com/obinopaul/malibu/releases` to see your release
3. Test the install script: `curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash`

### If the release fails

If the workflow fails (red X on Actions page):
1. Check the failed job's logs on GitHub Actions
2. Common causes:
   - **Missing file** (like `.github/TEAM_MEMBERS`) — create it and push
   - **Typecheck errors** — fix them and push
   - **Missing secrets** (like `NPM_TOKEN`) — add them in repo Settings
3. After fixing, delete the old tag and re-tag:
   ```bash
   git tag -d v0.2.0                    # delete local tag
   git push origin --delete v0.2.0      # delete remote tag
   git tag v0.2.0                       # create new tag on current commit
   git push origin v0.2.0              # push to trigger workflow again
   ```

---

## GitHub Secrets Required

For the full workflow to work, these secrets must be configured in GitHub repo settings (`Settings > Secrets and variables > Actions`):

| Secret | Required? | Purpose | How to Get It |
|--------|-----------|---------|---------------|
| `GITHUB_TOKEN` | Auto-provided | Used by `softprops/action-gh-release` to create releases and by publish script for Homebrew tap | Automatically available in GitHub Actions — no setup needed |
| `NPM_TOKEN` | For npm publishing | Authenticates `npm publish` to the npm registry | Go to npmjs.com > Access Tokens > Generate New Token (Automation type) |

Without `NPM_TOKEN`, Job 3 (publish-npm) will fail, but Jobs 1 and 2 will still work (binaries built + GitHub Release created).

---

## Quick Reference

| Action | Command |
|--------|---------|
| Push code (no release) | `git push origin main` |
| Create a stable release | `git tag v0.2.0 && git push origin v0.2.0` |
| Create a pre-release | `git tag v0.2.0-beta.1 && git push origin v0.2.0-beta.1` |
| List all tags | `git tag -l` |
| Delete a local tag | `git tag -d v0.2.0` |
| Delete a remote tag | `git push origin --delete v0.2.0` |
| Re-tag after a fix | `git tag -d v0.2.0 && git push origin --delete v0.2.0 && git tag v0.2.0 && git push origin v0.2.0` |
| See release workflow status | Visit github.com/obinopaul/malibu/actions |
| See all releases | Visit github.com/obinopaul/malibu/releases |
| Run typecheck locally | `bun typecheck` |
| Run tests locally | `cd packages/opencode && bun test` |
| Run build locally | `cd packages/opencode && MALIBU_VERSION=v0.2.0 bun run build` |

---

## Key Concepts

### Git Tags vs Git Commits

- A **commit** is a snapshot of your code at a point in time
- A **tag** is a named label you attach to a specific commit (like a bookmark)
- Tags are what trigger the release workflow — not commits, not pushes to main
- You can push 50 commits without triggering a release. Only a tag push triggers CD.

### Stable vs Pre-releases

- `v0.2.0` = **stable release** — published to npm, shown as "latest" on GitHub, updates Homebrew + AUR
- `v0.2.0-beta.1` = **pre-release** — the `-` in the tag name tells the workflow to skip npm/Homebrew/AUR publishing. Only the GitHub Release + binaries are created.

### The Build Targets

The build script compiles Malibu for 11 platform targets:

| Target | OS | Arch | Notes |
|--------|----|------|-------|
| `malibu-linux-x64` | Linux | x86_64 | Standard Linux |
| `malibu-linux-x64-baseline` | Linux | x86_64 | Without AVX2 (older CPUs) |
| `malibu-linux-arm64` | Linux | ARM64 | ARM servers, Raspberry Pi |
| `malibu-linux-x64-musl` | Linux | x86_64 | Alpine Linux (musl libc) |
| `malibu-linux-arm64-musl` | Linux | ARM64 | Alpine ARM |
| `malibu-linux-x64-baseline-musl` | Linux | x86_64 | Alpine, older CPUs |
| `malibu-darwin-arm64` | macOS | ARM64 | Apple Silicon (M1/M2/M3/M4) |
| `malibu-darwin-x64` | macOS | x86_64 | Intel Macs |
| `malibu-darwin-x64-baseline` | macOS | x86_64 | Intel Macs, older CPUs |
| `malibu-windows-x64` | Windows | x86_64 | Standard Windows |
| `malibu-windows-x64-baseline` | Windows | x86_64 | Older Windows CPUs |
| `malibu-windows-arm64` | Windows | ARM64 | Windows on ARM |

### Distribution Channels

Malibu is distributed through multiple channels:

| Channel | How Users Install | Updated By |
|---------|-------------------|-----------|
| **curl installer** | `curl -fsSL .../install \| bash` | Reads from GitHub Releases (always latest) |
| **npm** | `npm install -g malibu-ai` | `script/publish.ts` publishes on stable releases |
| **Homebrew** | `brew install obinopaul/tap/malibu` | `script/publish.ts` updates the tap repo |
| **AUR** | `yay -S malibu-bin` | `script/publish.ts` updates the PKGBUILD |
| **Docker** | `docker pull ghcr.io/obinopaul/malibu` | `script/publish.ts` pushes the image |
| **GitHub Release** | Download from Releases page | `release.yml` workflow creates it |

---

## Release History

| Version | Date | Notes |
|---------|------|-------|
| v0.1.0 | 2026-03-24 | First release |
