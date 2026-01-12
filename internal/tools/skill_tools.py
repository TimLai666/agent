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

    # Build the tool description (must be done before function definition)
    tool_description = f"""ACTIVATE A SKILL for expert guidance on specialized tasks.

*** CRITICAL: You MUST use this tool when the user's request matches ANY skill below. ***

Skills provide expert knowledge, proven methodologies, and best practices that will
significantly improve your response quality. Always check if a skill is relevant BEFORE
responding to the user.

AVAILABLE SKILLS:
{skills_desc}

WHEN TO USE:
1. Read the skill descriptions above carefully
2. If the user's request matches a skill's domain, call this tool FIRST
3. Get the skill's guidance BEFORE formulating your response
4. Follow the skill's methodology exactly

EXAMPLES:
- User asks about Python -> use_skill("python-tutorial")
- User asks to review code -> use_skill("code-review")
- User reports a bug -> use_skill("debugging-assistant")
- User asks about tools -> use_skill("tool-usage-guide")
- User wants to learn programming -> use_skill("python-tutorial")
- User asks how to debug -> use_skill("debugging-assistant")

Args:
    skill_name: Exact name of the skill to activate (must match one from the list above)

Returns:
    Expert guidance and methodology you MUST follow in your response
"""

    # Register the tool with dynamic description
    @agent.tool_plain(description=tool_description)
    def use_skill(skill_name: str) -> str:
        # Get the skill
        skill = skills.get_skill(skill_name)

        if not skill:
            available = ", ".join(skills.list_names())
            return f"❌ Skill '{skill_name}' not found.\n\nAvailable skills: {available}"

        # Log activation
        logger.info(f"[Tool] Activated skill: {skill.name}")

        # Build resources section if available
        resources_section = ""
        if skill.resources.has_resources():
            resources_info = []

            # Add scripts
            if skill.resources.scripts:
                resources_info.append("\n### Available Scripts")
                resources_info.append("\nThese scripts are ready to execute. Use Read tool to examine them first, then run with Bash:\n")
                for script_name, script_path in skill.resources.scripts.items():
                    resources_info.append(f"- `{script_name}`: `{script_path}`")

            # Add references
            if skill.resources.references:
                resources_info.append("\n### Reference Files")
                resources_info.append("\nThese files contain detailed documentation. Use Read tool to access them:\n")
                for ref_name, ref_path in skill.resources.references.items():
                    resources_info.append(f"- `{ref_name}`: `{ref_path}`")

            # Add assets
            if skill.resources.assets:
                resources_info.append("\n### Available Assets")
                resources_info.append("\nThese are templates, images, or other resources:\n")
                for asset_name, asset_path in skill.resources.assets.items():
                    resources_info.append(f"- `{asset_name}`: `{asset_path}`")

            if resources_info:
                resources_section = "\n\n## Bundled Resources\n" + "\n".join(resources_info) + "\n"

        # Return skill content with priority reminder and resources
        return f"""# Active Skill: {skill.name}

**IMPORTANT**: This skill provides expert guidance AND executable resources.
Follow the instructions below and USE the provided scripts/references.

---

{skill.content}{resources_section}

---

**Remember**:
1. Follow the skill's methodology exactly
2. Use Read tool to examine scripts before executing
3. Execute scripts using Bash with the absolute paths provided above
4. Read reference files completely when instructed (no offset/limit)"""

    logger.info(f"Registered use_skill tool with {len(skills.list_names())} available skill(s)")
