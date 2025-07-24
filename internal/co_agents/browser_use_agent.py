
from browser_use.llm import ChatOllama, ChatGoogle
from browser_use import Agent, AgentHistoryList, Controller
from typing import Any
import os
from pydantic import BaseModel

# llm = ChatOllama(model="llama3.2:3b", host=os.getenv("OLLAMA_BASE_URL"))
llm = ChatGoogle(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))


class BrowserUseCoAgentOutputFormat(BaseModel):
    """Output format for the agent."""
    answer: str
    related_links: list[str] | None = None


async def browser_use_agent(task: str, message_context: str) -> BrowserUseCoAgentOutputFormat:
    """Run the browser use agent."""

    agent = Agent(
        task=task,
        message_context=message_context,
        llm=llm,
        use_vision=True,
        use_thinking=True,
        use_vision_for_planner=True,
        controller=Controller(output_model=BrowserUseCoAgentOutputFormat),
    )
    history = await agent.run()
    result = history.final_result()
    return BrowserUseCoAgentOutputFormat.model_validate_json(result) if result else BrowserUseCoAgentOutputFormat(answer="No result found", related_links=None)
