from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Optional

from pydantic_ai import Agent

if TYPE_CHECKING:
    from internal.co_agents.philosopher import PhilosopherCoAgent
    from internal.skills_loader import SkillRegistry

from internal.logger import logger


class SubAgent(ABC):
    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: "PhilosopherCoAgent" | None = None,
        skills: Optional["SkillRegistry"] = None,
    ) -> None:
        self.agent = agent
        self._philosopher = philosopher
        self._skills = skills

    def _apply_skills(self, prompt: str) -> str:
        """Apply relevant skills to the prompt (shared with MainAgent logic)."""
        if not self._skills or self._skills.is_empty():
            return prompt

        # Find relevant skills
        relevant_skills = self._skills.find_relevant_skills(prompt, max_skills=3)

        if not relevant_skills:
            return prompt

        # Build skills context
        skills_context = self._skills.build_skills_context(relevant_skills)

        if skills_context:
            logger.info(
                "[SubAgent] Activated skills: %s",
                ", ".join([skill.name for skill in relevant_skills])
            )
            # Prepend skills context
            prompt = f"{skills_context}\n\n---\n\n{prompt}"

        return prompt

    async def run(self, prompt: str) -> str:
        # Apply skills if available
        if self._skills:
            prompt = self._apply_skills(prompt)

        result = await self.agent.run(prompt)
        return result.output

    async def run_stream(self, prompt: str):
        """Stream output from the underlying agent."""
        # Apply skills if available
        if self._skills:
            prompt = self._apply_skills(prompt)

        async with self.agent.run_stream(user_prompt=prompt) as result:
            async for chunk in result.stream_text(delta=True):
                if not chunk:
                    continue
                yield chunk

    async def ask_philosopher(self, question: str) -> str:
        if not self._philosopher:
            raise RuntimeError("Philosopher co-agent is not available.")
        return await self._philosopher.run(question)
