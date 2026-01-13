# SUB_AGENTS (internal/sub_agents) — AGENTS GUIDE

**Generated:** 2026-01-12 17:20:00 (Asia/Taipei)
**Scope:** internal/sub_agents/ — per-domain subagents (marketing, testing, design, studio-operations)

## OVERVIEW
Subagents implement domain-specific workflows and are auto-registered by the main runtime. Each domain folder often contains a `SKILL.md` describing its behavior.

## QUICK NAV
- `internal/sub_agents/marketing/` — marketing-focused automation
- `internal/sub_agents/testing/` — testing utilities and runners
- `internal/sub_agents/design/` — design helpers and assets
- `internal/sub_agents/studio-operations/` — operational scripts for studio tasks

## IMPORTANT RULES
- Keep each subagent focused and documented with `SKILL.md`.
- Do not rename directories without coordinating with maintainers; auto-registration may break.

## WHERE TO LOOK
- For examples, open any `internal/sub_agents/*/SKILL.md` and follow conventions used across existing subagents.

## NOTES
- Subagents are intended to be small and composable. If a subagent grows large, consider promoting it to `skills/`.
