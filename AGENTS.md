# PROJECT KNOWLEDGE BASE

**Generated:** 2026-01-12 17:20:00 (Asia/Taipei)
**Repo:** agent

## OVERVIEW
Lightweight AI agent framework and collection of "skills" for day-to-day automation. Python-first project with many standalone skill packages under /skills and internal subagents under /internal.

## QUICK START
# Install dependencies
uv sync

# Run main agent (development)
uv run main.py

## STRUCTURE (non-obvious)
```
./
├── main.py                 # Project entrypoint (local CLI agent runner)
├── internal/               # Core runtime: agents, sub_agents, services, tools
│   ├── agents/             # Agent runtime implementations
│   ├── sub_agents/         # Per-domain subagents (marketing, testing, design...)
│   ├── co_agents/          # Coordinating agents
│   └── tools/              # Shared runtime tools
├── skills/                 # Packaged skills (each with SKILL.md) - treat as plugins
├── prompts/                # Prompt library and templates
├── docs/                   # Documentation (developer-facing)
├── pyproject.toml          # Python project metadata
└── .venv/                  # Local virtualenv (ignored)
```

## WHERE TO LOOK (task -> location)
- Development / Run: main.py (root) and `uv` CLI
- Add a new skill: create folder under `skills/` with SKILL.md and scripts
- Agent runtime internals: `internal/agents` and `internal/tools`
- Subagents: `internal/sub_agents/*` (see per-subdir SKILL.md for usage)

## CONVENTIONS (deviations from standard)
- `skills/*` directories contain a SKILL.md that documents usage and commands; prefer SKILL.md as the primary developer guide for a skill.
- Per-subagent folders under `internal/sub_agents` are treated as first-class units and may contain their own SKILL.md files.
- Use `uv` (uv tool) for dependency management and task running instead of pip/pnpm directly.

## ANTI-PATTERNS (explicit project rules)
- NEVER commit secrets or API keys into repo (.env used for local dev)
- DO NOT modify files in `skills/*/ooxml/schemas` unless you understand OOXML schema implications
- AVOID changing `internal/sub_agents/*` layout without coordinating with maintainers (risk: breaks auto-registration)

## COMMANDS
```bash
# Sync environment
uv sync

# Run agent
uv run main.py

# Run tests (project-wide)
# See individual skill SKILL.md for skill-specific test commands
```

## NOTES & GOTCHAS
- Many skills include binary assets (fonts, schemas); avoid large PRs that change them without CI prechecks.
- `internal/sub_agents` contains subfolders for several domains (marketing, testing, design, studio-operations). Check SKILL.md in each subfolder before editing.

## FURTHER READING / EXAMPLES
- See `skills/*/SKILL.md` for per-skill developer instructions (templates are consistent)
- AGENTS.md examples: Sentry (hierarchical), AgentStack (monorepo frontmatter), Transformers (domain-specific guidance)
