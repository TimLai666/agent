"""Skills as tools - Claude Code compatible implementation."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from internal.skills_loader import SkillRegistry

from internal.logger import logger


def register_skill_tool(agent: "Agent", skills: "SkillRegistry") -> None:
    """Register the use_skill tool with dynamic description.

    This follows Claude Code's implementation where skills are activated
    through tool calling rather than automatic injection.

    Args:
        agent: The pydantic_ai Agent to register the tool on
        skills: SkillRegistry containing all available skills
    """
    if not skills or skills.is_empty():
        logger.info("No skills available - skipping use_skill tool registration")
        return

    # Build dynamic tool description with all available skills
    skills_list = []
    for skill_name in skills.list_names():
        skill = skills.get_skill(skill_name)
        if skill:
            skills_list.append(f"  - {skill.name}: {skill.description}")

    skills_desc = "\n".join(skills_list) if skills_list else "  (No skills loaded)"

    # Register the tool with dynamic description
    @agent.tool_plain
    def use_skill(skill_name: str) -> str:
        f"""Activate a skill to guide your response with specialized knowledge and methodology.

Skills provide expert domain knowledge, best practices, and systematic approaches.
Call this tool BEFORE processing requests that match a skill's domain.

Available skills:
{skills_desc}

Args:
    skill_name: Name of the skill to activate (e.g., "python-tutorial", "code-review")

Returns:
    The skill's guidance content that you should follow
"""
        # Get the skill
        skill = skills.get_skill(skill_name)

        if not skill:
            available = ", ".join(skills.list_names())
            return f"❌ Skill '{skill_name}' not found.\n\nAvailable skills: {available}"

        # Log activation
        logger.info(f"[Tool] Activated skill: {skill.name}")

        # Return skill content with priority reminder
        return f"""# Active Skill: {skill.name}

**IMPORTANT**: Use the following guidance to inform your response.
This skill provides expert knowledge and best practices for this domain.

---

{skill.content}

---

**Remember**: Follow the skill's guidance and methodology above."""

    logger.info(f"Registered use_skill tool with {len(skills.list_names())} available skill(s)")
