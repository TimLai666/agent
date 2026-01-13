# INTERNAL MODULES — AGENTS GUIDE

**Generated:** 2026-01-12 17:20:00 (Asia/Taipei)
**Scope:** internal/ — core runtime: agents, sub_agents, co_agents, tools

## OVERVIEW
Houses the runtime implementations, subagent definitions, coordinating agents, and shared tools. Changes here affect agent registration and runtime behavior.

## QUICK NAV
- `internal/agents/` — agent runtime implementations (where agents are defined)
- `internal/sub_agents/` — per-domain subagents (marketing, testing, design, studio-operations). Each subfolder may include a SKILL.md used for auto-registration.
- `internal/co_agents/` — coordinating agents that orchestrate other agents
- `internal/tools/` — shared runtime utilities and connectors

## IMPORTANT RULES
- Avoid renaming or moving `internal/sub_agents` folders — registration relies on path and naming conventions.
- Prefer adding new subagents under `internal/sub_agents/<domain>` with a SKILL.md describing usage and commands.

## COMMON TASKS
- Add a new subagent: create `internal/sub_agents/<name>/SKILL.md` and a module implementing the agent. Follow existing SKILL.md examples.
- Update runtime tools: write tests and update `internal/tools/*` references across agents.

## WHERE TO LOOK
- Registration patterns: search for `auto_register`, `discover_subagents`, or explicit imports in `internal/agents` and `internal/co_agents`.
- Tests: look in `internal/tests` or repo-wide tests referencing `internal` modules.

## CONTACT
- Maintainers: see CONTRIBUTORS or Git history for frequent committers in `internal/` (use `git log -- internal/ | head`).
