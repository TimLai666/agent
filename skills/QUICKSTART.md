# Skills Quick Start Guide

## What are Skills?

Skills are modular packages that teach the agent specialized knowledge and workflows. They automatically activate when relevant to user requests.

## Using Existing Skills

Skills activate automatically! Just ask naturally:

- **Code Review**: "Can you review this code?"
- **Debugging**: "I have a bug, help me debug"
- **Skills Info**: "Tell me about skills"

The agent will automatically load relevant skills and apply their guidance.

## Creating Your First Skill

### 1. Create Directory

```bash
mkdir skills/my-awesome-skill
cd skills/my-awesome-skill
```

### 2. Create SKILL.md

```markdown
---
name: my-awesome-skill
description: What this skill does and when to use it. Be specific!
---

# My Awesome Skill

## What This Does

Explain the purpose clearly.

## When to Use

- Condition 1
- Condition 2

## How to Use

1. Step 1
2. Step 2

## Examples

Show concrete examples here.
```

### 3. Test Your Skill

```bash
python -c "
from internal.skills_loader import load_skill_registry

registry = load_skill_registry()
print('Available skills:', registry.list_names())

# Test if your skill matches
prompt = 'your test prompt here'
skills = registry.find_relevant_skills(prompt)
print('Matched skills:', [s.name for s in skills])
"
```

## Tips for Good Skills

### ✅ DO

- Write clear, specific descriptions
- Use imperative language ("Do this", not "You should do this")
- Include concrete examples
- Keep focused on one task
- List when to use the skill

### ❌ DON'T

- Make descriptions too vague
- Try to cover too many topics
- Exceed 500 lines without good reason
- Forget the description field (critical!)

## Skill Description Guidelines

The description is **CRITICAL** for skill activation. It must clearly state:

1. What the skill does
2. When it should be used
3. Key terms that should trigger it

**Good Description:**
```yaml
description: Provides systematic code review guidance. Use when the user asks to review code, check code quality, find bugs, or improve code structure.
```

**Bad Description:**
```yaml
description: A helpful skill for coding.
```

## File Structure

```
skills/
├── README.md                      # Documentation
├── QUICKSTART.md                  # This file
├── your-skill-name/
│   ├── SKILL.md                   # Required
│   ├── scripts/                   # Optional
│   ├── references/                # Optional
│   └── assets/                    # Optional
```

## Checking Loaded Skills

```python
from internal.skills_loader import load_skill_registry

registry = load_skill_registry()

# List all skills
for skill in registry.list_summaries():
    print(f"{skill['name']}: {skill['description']}")

# Get specific skill
skill = registry.get_skill('code-review')
if skill:
    print(skill.content)
```

## Troubleshooting

### Skill Not Loading

1. Check `SKILL.md` exists in skill directory
2. Verify YAML frontmatter has closing `---`
3. Ensure `name` and `description` fields exist
4. Check logs for loading errors

### Skill Not Activating

1. Make description more specific
2. Add keywords that match user prompts
3. Test with `find_relevant_skills()`
4. Check if score meets threshold (0.1)

### Multiple Skills Activate

This is normal! Up to 3 relevant skills can activate simultaneously. The agent will use guidance from all activated skills.

## Examples by Use Case

### Code Task Skills
- code-review
- debugging-assistant
- testing-guide
- refactoring-helper

### Writing Skills
- documentation-writer
- commit-message-generator
- technical-writer

### Analysis Skills
- performance-analyzer
- security-auditor
- complexity-reviewer

## Next Steps

1. ✅ Read existing skills for examples
2. ✅ Create a simple skill for a task you do often
3. ✅ Test it with various prompts
4. ✅ Refine based on results
5. ✅ Share useful skills with your team!

## More Information

- Full Documentation: `docs/SKILLS_SYSTEM.md`
- Skills Directory: `skills/README.md`
- Example Skills: Browse `skills/*/SKILL.md`
