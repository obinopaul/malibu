---
name: code-explorer
description: Deep codebase exploration guidance for Malibu's read-only explore subagent.
allowed-tools: grep read_file
user-invocable: false
---

# Code Explorer

## When To Use
Use this skill when the active agent is the `explore` subagent and the task requires broad codebase understanding, call-chain tracing, or architecture discovery without making changes.

## Instructions
1. Start with targeted search to find the relevant entrypoints, symbols, and files.
2. Read only the files needed to build a defensible answer.
3. Prefer structural output first: flows, file trees, tables, or grouped findings.
4. Cite exact files and symbols so the caller can verify quickly.
5. Stay read-only. If the request turns into implementation, hand the work back to the caller clearly.

## Response Contract
- Summarize the architecture or answer directly.
- Include the most relevant files and why they matter.
- Note uncertainties instead of guessing.
