# Skills System Documentation

## Overview

The Skills system is inspired by [Claude Code](https://github.com/anthropics/claude-code) and provides a modular way to extend the agent's capabilities with specialized knowledge and workflows.

## Architecture

### Components

1. **SkillSpec**: Data class representing a loaded skill
   - `name`: Unique identifier
   - `description`: When to use this skill
   - `content`: Markdown instructions
   - `path`: File location

2. **SkillRegistry**: Manages loaded skills
   - Loads skills from `skills/` directory
   - Finds relevant skills for prompts
   - Builds context from activated skills

3. **Integration**: Skills are integrated into MainAgent
   - Automatically loaded at startup
   - Activated based on prompt relevance
   - Context prepended to user prompts

### File Structure

```
skills/
├── README.md                    # Skills documentation
├── example-skill/
│   └── SKILL.md                # Example skill
├── code-review/
│   └── SKILL.md                # Code review skill
└── debugging-assistant/
    └── SKILL.md                # Debugging skill
```

## How It Works

### 1. Skill Loading

Skills are automatically discovered at agent startup:

```python
from internal.skills_loader import load_skill_registry

skills = load_skill_registry()
# Loads all SKILL.md files from skills/
```

### 2. Relevance Matching

When a user prompt arrives, the system finds relevant skills:

```python
relevant_skills = skills.find_relevant_skills(prompt, max_skills=3)
```

**Matching Algorithm:**
- Extracts keywords from prompt and skill descriptions
- Filters common stop words ('the', 'a', 'is', etc.)
- Calculates Jaccard similarity
- Boosts scores for key technical words
- Returns top matches above threshold (0.1)

### 3. Context Injection

Relevant skills are prepended to the prompt:

```
# Active Skills

## code-review

[Skill content here...]

---

[User's original prompt]
```

## Creating Skills

### Basic Skill Template

```markdown
---
name: my-skill
description: Clear description of what this skill does and when to use it
---

# My Skill

Instructions that the agent will follow...

## When to Use

- Use case 1
- Use case 2

## Guidelines

1. Guideline 1
2. Guideline 2
```

### Required Fields

- **name**: Lowercase, use hyphens (e.g., `code-review`)
- **description**: Critical for matching - be specific and comprehensive

### Best Practices

1. **Clear Descriptions**: The description is critical for activation
2. **Focused Scope**: Each skill should handle specific tasks
3. **Actionable Content**: Use imperative language
4. **Concise**: Keep under 500 lines when possible
5. **Examples**: Include concrete examples

## Example Skills

### Code Review Skill

Provides systematic code review guidance:
- Correctness & logic checks
- Security review
- Performance analysis
- Readability assessment

**Activates on:** "review code", "check code quality", "find bugs"

### Debugging Assistant Skill

Systematic debugging methodology:
- Problem understanding
- Issue isolation
- Hypothesis testing
- Fix verification

**Activates on:** "bug", "error", "not working", "debug"

### Example Skill

Demonstrates the skills system itself:
- Shows skill structure
- Explains creation process
- Best practices

**Activates on:** "skills system", "create skill", "skill example"

## Implementation Details

### SkillRegistry Methods

```python
class SkillRegistry:
    def is_empty() -> bool
        """Check if any skills are loaded"""

    def list_specs() -> list[SkillSpec]
        """Get all loaded skills"""

    def get_skill(name: str) -> SkillSpec | None
        """Get specific skill by name"""

    def find_relevant_skills(
        prompt: str,
        max_skills: int = 3,
        min_score: float = 0.1
    ) -> list[SkillSpec]
        """Find skills relevant to prompt"""

    def build_skills_context(skills: list[SkillSpec]) -> str
        """Build markdown context from skills"""
```

### Integration with MainAgent

In `MainAgent.create()`:
```python
if skills is None:
    try:
        skills = load_skill_registry()
    except Exception:
        logger.exception("Failed to load skills")
        skills = SkillRegistry({})
```

In `MainAgent.run()` and `MainAgent.run_stream()`:
```python
# Apply relevant skills to the prompt
prompt = self._apply_skills(prompt)
```

### Relevance Scoring

The scoring algorithm:

1. **Tokenization**: Extract words from prompt and description
2. **Stop Word Filtering**: Remove common words
3. **Jaccard Similarity**: `score = |A ∩ B| / |A ∪ B|`
4. **Keyword Boosting**: Increase score for technical terms
5. **Threshold Filtering**: Only return scores > 0.1

## Testing

### Manual Testing

```bash
python -c "
from internal.skills_loader import load_skill_registry

registry = load_skill_registry()
print(f'Loaded {len(registry.list_names())} skills')

# Test relevance matching
prompt = 'Can you review my code?'
skills = registry.find_relevant_skills(prompt)
print(f'Matched: {[s.name for s in skills]}')
"
```

### Integration Testing

The skills system integrates seamlessly with the main agent. When users ask questions that match skill descriptions, the relevant skills are automatically activated and their content is injected into the context.

## Future Enhancements

Potential improvements:

1. **Embedding-based Matching**: Use semantic similarity instead of keyword matching
2. **User Feedback**: Learn from which skills are helpful
3. **Skill Composition**: Combine multiple skills intelligently
4. **Dynamic Loading**: Hot-reload skills without restart
5. **Skill Analytics**: Track activation frequency and effectiveness
6. **LLM-based Relevance**: Ask LLM to score skill relevance

## References

- [Claude Code Plugins](https://github.com/anthropics/claude-code/tree/main/plugins)
- [Anthropic Skills Repository](https://github.com/anthropics/skills)
- [Claude Code Documentation](https://code.claude.com/docs/en/skills)

## Files Modified

- `internal/skills_loader.py` - Core skills system
- `internal/agents/main_agent.py` - Integration with main agent
- `skills/` - Skills directory with examples
