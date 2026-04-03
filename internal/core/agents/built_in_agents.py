from internal.core.agents.agent_types import BuiltInAgentDefinition
from internal.core.prompts.verification_prompt import VERIFICATION_PROMPT
from internal.core.prompts.worker_prompt import WORKER_PROMPT

BUILT_IN_AGENTS: dict[str, BuiltInAgentDefinition] = {
    "general-purpose": BuiltInAgentDefinition(
        agentType="general-purpose",
        whenToUse="General task execution, research, edits, and command runs.",
        tools=None,
        disallowedTools=None,
        systemPrompt=WORKER_PROMPT,
    ),
    "verification": BuiltInAgentDefinition(
        agentType="verification",
        whenToUse="Independent verification of implementation work before completion.",
        tools=None,
        disallowedTools=["AgentTool", "FileEdit", "FileWrite", "NotebookEdit", "ExitPlanMode"],
        systemPrompt=VERIFICATION_PROMPT,
    ),
}
