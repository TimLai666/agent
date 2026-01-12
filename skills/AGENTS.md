# SKILLS DIRECTORY GUIDE

**Generated:** 2026-01-12 17:20:00 (Asia/Taipei)
**Scope:** skills/ — modular plugin-style skill packages

## OVERVIEW
`skills/` contains independent skill packages. Each skill should be self-describing via a `SKILL.md` file in its root.

## KEY CONVENTIONS
- Every skill MUST include a `SKILL.md` describing: purpose, usage, commands, and any required assets or schemas.
- Prefer small, focused skill packages. Avoid large binaries in the root; use `skills/<name>/assets` if necessary.
- Avoid changing files under `skills/*/ooxml/schemas` unless you understand OOXML schema implications.

## WHERE TO LOOK
- For implementation patterns and examples, read `skills/*/SKILL.md` files.
- For binary assets (fonts, schema files), check `skills/*/assets` or `skills/*/ooxml/schemas`.

## COMMON TASKS
- Add a new skill: create folder under `skills/`, add implementation files and `SKILL.md`.
- Update skill docs: modify `SKILL.md` and include change summary in PR description.

## NOTES
- Some skills include generated or large assets; CI may fail if these change without corresponding CI adjustments.
