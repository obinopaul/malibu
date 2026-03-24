# RELEASES

How Malibu's release system works and how to publish new versions.

## How It All Fits Together

Malibu uses **GitHub Actions** for CI/CD (Continuous Integration / Continuous Delivery). Here's the big picture:

```
You write code
    |
    v
git commit + git push          <-- pushes code to GitHub (no release happens)
    |
    v
git tag v0.2.0                 <-- creates a version tag locally
git push origin v0.2.0         <-- pushes the tag to GitHub
    |
    v
GitHub Actions detects the tag  <-- the "v*" pattern in release.yml triggers
    |
    v
Workflow runs automatically:
  1. Builds binaries for all platforms (Linux, macOS, Windows)
  2. Creates a GitHub Release with downloadable archives
  3. Publishes to npm (for stable releases only)
    |
    v
Users can now install via:
  curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash
```

## What Is CI/CD?

**CI (Continuous Integration)** = automatically testing/building your code when you push changes.

**CD (Continuous Delivery)** = automatically publishing/deploying your code when you're ready to release.

In Malibu's case:
- **CI** happens on every push (the pre-push hook runs `turbo typecheck`)
- **CD** happens when you push a git tag (GitHub Actions builds and publishes the release)

## The Release Workflow Explained

The file `.github/workflows/release.yml` defines what happens when a tag is pushed. It has **3 jobs**:

### Job 1: `build` (Build binaries)

```
Trigger: push a tag matching "v*" (e.g., v0.1.0, v0.2.0)
Runs on: ubuntu-latest
```

What it does:
1. Checks out the code
2. Installs Bun 1.3.10
3. Runs `bun install` to install dependencies
4. Runs `bun run build` in `packages/opencode/` to compile platform binaries
5. Uploads the built binaries as artifacts for the next jobs

The version number comes from the tag name via `MALIBU_VERSION: ${{ github.ref_name }}`.

### Job 2: `release` (Create GitHub Release)

```
Depends on: build (waits for it to finish)
Runs on: ubuntu-latest
```

What it does:
1. Downloads the built binaries from Job 1
2. Packages them into archives:
   - `.tar.gz` for Linux
   - `.zip` for macOS and Windows
3. Creates a GitHub Release page with auto-generated release notes
4. Attaches the archives as downloadable files

### Job 3: `publish-npm` (Publish to npm)

```
Depends on: build (waits for it to finish)
Runs on: ubuntu-latest
Only runs for stable releases (tags WITHOUT a hyphen, e.g., v0.2.0 but NOT v0.2.0-beta.1)
```

What it does:
1. Sets up Node.js and npm registry authentication
2. Downloads the built binaries
3. Runs `packages/opencode/script/publish.ts` to publish to npm

**Note:** This requires an `NPM_TOKEN` secret configured in GitHub repository settings.

## How Users Install Malibu

When someone runs:
```bash
curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash
```

The `install` script (in the project root) does the following:
1. Queries the GitHub API for the latest release: `https://api.github.com/repos/obinopaul/malibu/releases/latest`
2. Extracts the version number from the `tag_name` field (e.g., `v0.2.0` becomes `0.2.0`)
3. Detects the user's OS and architecture (linux-x64, darwin-arm64, etc.)
4. Downloads the matching binary archive from the GitHub Release
5. Extracts it and installs the `malibu` binary to `~/.local/bin/`
6. Adds the bin directory to the user's PATH if needed

Users can also install a specific version:
```bash
curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash -s -- --version 0.2.0
```

## How To Publish a New Release

### Step 1: Make your code changes

```bash
# Edit files, fix bugs, add features...
git add .
git commit -m "description of changes"
git push origin main
```

This pushes your code but does NOT create a release.

### Step 2: Update the version number

Edit `packages/opencode/package.json` and bump the `"version"` field:

```json
"version": "0.2.0"
```

**Version numbering convention (Semantic Versioning):**
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

That's it. GitHub Actions takes over from here and automatically:
- Builds the binaries
- Creates the GitHub Release page
- Publishes to npm

### Step 4: Verify

1. Go to `https://github.com/obinopaul/malibu/actions` to watch the workflow run
2. Once complete, check `https://github.com/obinopaul/malibu/releases` to see your release
3. Test the install script: `curl -fsSL https://raw.githubusercontent.com/obinopaul/malibu/main/install | bash`

## Quick Reference

| Action | Command |
|--------|---------|
| Push code (no release) | `git push origin main` |
| Create a release | `git tag v0.2.0 && git push origin v0.2.0` |
| Create a pre-release | `git tag v0.2.0-beta.1 && git push origin v0.2.0-beta.1` |
| List all tags | `git tag -l` |
| Delete a local tag | `git tag -d v0.2.0` |
| Delete a remote tag | `git push origin --delete v0.2.0` |
| See release workflow status | Visit github.com/obinopaul/malibu/actions |
| See all releases | Visit github.com/obinopaul/malibu/releases |

## Key Concepts

### Git Tags vs Git Commits

- A **commit** is a snapshot of your code at a point in time
- A **tag** is a label you attach to a specific commit (like a bookmark)
- Tags are what trigger the release workflow — not commits, not pushes to main

### Why Tags?

Tags give you control over *when* to release. You can push 50 commits to main without triggering a release. Only when you explicitly create and push a tag does a release happen.

### Stable vs Pre-releases

- `v0.2.0` = stable release (published to npm, shown as "latest" on GitHub)
- `v0.2.0-beta.1` = pre-release (the `-` in the tag name tells the workflow to skip npm publishing)

### GitHub Secrets Required

For the full workflow to work, these secrets must be configured in GitHub repo settings (`Settings > Secrets and variables > Actions`):

- `GITHUB_TOKEN` — automatically provided by GitHub Actions (no setup needed)
- `NPM_TOKEN` — required for npm publishing (get one from npmjs.com > Access Tokens)

## Release History

| Version | Date | Notes |
|---------|------|-------|
| v0.1.0 | 2026-03-24 | First release |
