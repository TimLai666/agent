---
name: example-skill
description: An example skill demonstrating the skills system. Use this when the user asks about skills or wants to see a skill example.
---

# Example Skill

This is an example skill that demonstrates how the skills system works.

## What This Skill Does

This skill provides guidance on:
- Understanding the skills system architecture
- Creating new skills
- Using skills effectively

## When to Use

Use this skill when:
- The user asks about the skills system
- The user wants to create a new skill
- The user needs an example of how skills work

## Guidelines

1. **Be Clear**: Skill descriptions should clearly indicate when they should be activated
2. **Be Concise**: Keep skills focused on specific tasks
3. **Be Helpful**: Provide actionable instructions
4. **Use Examples**: Show concrete examples when possible

## Skill Structure

Every skill must have:
- A `SKILL.md` file with YAML frontmatter
- A `name` field (unique identifier)
- A `description` field (tells Claude when to use it)
- Markdown content with instructions

Example frontmatter:
```yaml
---
name: my-skill
description: What this skill does and when to use it
---
```

## Creating New Skills

To create a new skill:

1. Create a new directory in `skills/`
2. Add a `SKILL.md` file
3. Write clear frontmatter with name and description
4. Add your instructions in markdown
5. Test the skill to ensure it activates correctly

## Best Practices

- Keep descriptions comprehensive but concise
- Use imperative language in instructions
- Include examples where helpful
- Focus on specific, repeatable tasks
- Keep skills under 500 lines when possible
