# Skills Directory

This directory contains skills that extend the agent's capabilities with specialized knowledge and workflows.

## What are Skills?

Skills are modular packages that teach the agent how to complete specific tasks in a repeatable way. Each skill is a folder containing a `SKILL.md` file with:

- **YAML frontmatter**: Metadata including name and description
- **Markdown content**: Instructions and guidelines for using the skill

## Skill Structure

Every skill must have a `SKILL.md` file with this structure:

```markdown
---
name: my-skill-name
description: A clear description of what this skill does and when to use it
---

# My Skill Name

[Instructions that the agent will follow when this skill is active]

## When to Use

- Use case 1
- Use case 2

## Guidelines

1. Guideline 1
2. Guideline 2

## Examples

Example content...
```

## Required Fields

- **name**: Unique identifier (lowercase, use hyphens for spaces)
- **description**: Complete description of the skill's purpose and when it should be activated (critical for relevance matching)

## How Skills Work

1. **Automatic Activation**: When a user prompt matches a skill's description, the skill is automatically loaded
2. **Context Injection**: The skill's content is prepended to the prompt
3. **Progressive Disclosure**: Skills are lightweight metadata until activated
4. **Multiple Skills**: Up to 3 relevant skills can be activated simultaneously

## Creating a New Skill

1. Create a new directory in `skills/`:
   ```bash
   mkdir skills/my-new-skill
   ```

2. Create a `SKILL.md` file:
   ```bash
   cd skills/my-new-skill
   touch SKILL.md
   ```

3. Add frontmatter and content:
   ```yaml
   ---
   name: my-new-skill
   description: What this skill does and when Claude should use it
   ---

   # My New Skill

   [Your instructions here]
   ```

4. Test the skill by using prompts that match the description

## Best Practices

- **Clear Descriptions**: The description field is critical. Be comprehensive about what the skill does and when it should be used.
- **Specific Focus**: Each skill should focus on a specific, repeatable task
- **Concise Instructions**: Keep skills under 500 lines when possible
- **Use Examples**: Include concrete examples where helpful
- **Imperative Language**: Use direct, actionable language in instructions

## Example Skills

- **example-skill**: Demonstrates the skills system (located in `skills/example-skill/`)

## Advanced Features

### Bundled Resources

Skills can include additional files:
- `scripts/`: Executable code
- `references/`: Documentation loaded as needed
- `assets/`: Templates and output files

### Skill Discovery

Skills are automatically discovered and loaded at agent startup. The relevance matching uses keyword-based scoring to find the most appropriate skills for each prompt.

## Troubleshooting

- **Skill not activating**: Check that the description clearly describes when the skill should be used
- **Wrong skill activating**: Make descriptions more specific to avoid false matches
- **Too many skills**: Limit skills to well-defined, distinct tasks

## References

Based on the [Anthropic Skills](https://github.com/anthropics/skills) repository and [Claude Code](https://github.com/anthropics/claude-code) plugins system.
