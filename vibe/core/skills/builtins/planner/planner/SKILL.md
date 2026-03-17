---
name: planner
description: Planning guidance for Malibu's planning agent and planner subagent.
allowed-tools: grep read_file task todo
user-invocable: false
---

# Planner

## When To Use
Use this skill when the active agent is `plan` or `planner` and the task needs decomposition, sequencing, or scoped delegation before implementation.

## Instructions
1. Read enough code to understand the real execution surface before planning.
2. Break work into dependency-ordered steps with clear completion criteria.
3. Use the `todo` tool for multi-step plans.
4. Delegate narrow repository exploration tasks to the `explore` subagent when that will reduce uncertainty.
5. Keep the plan read-only. Do not edit code from the planner role.

## Good Plans
- Reference concrete files, tools, and symbols.
- Surface risks, blockers, and assumptions.
- Avoid vague steps like "handle integration" when a specific boundary can be named.
