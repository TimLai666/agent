import os
from typing import Any

from browser_use import Agent, AgentHistoryList, Controller
from browser_use.llm import ChatGoogle, ChatOllama
from browser_use.llm.openai.like import ChatOpenAI
from pydantic import BaseModel

# llm = ChatOllama(model="llama3.2:3b", host=os.getenv("OLLAMA_BASE_URL"))


class BrowserUseCoAgentOutputFormat(BaseModel):
    """Output format for the agent."""

    answer: str
    related_links: list[str] | None = None


async def browser_use_agent(
    task: str,
    message_context: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> BrowserUseCoAgentOutputFormat:
    """Run the browser use agent."""
    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
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
    return (
        BrowserUseCoAgentOutputFormat.model_validate_json(result)
        if result
        else BrowserUseCoAgentOutputFormat(answer="No result found", related_links=None)
    )
