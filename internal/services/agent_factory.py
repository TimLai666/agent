from dataclasses import dataclass

from httpx import AsyncClient
from pydantic_ai.models.openai import OpenAIChatModel

from internal.logger import logger
from internal.services.config_manager import create_model_for_agent


@dataclass
class AgentConfig:
    """
    Legacy config structure - kept for compatibility with existing code.
    New code should use config_manager directly.
    """
    name: str
    base_url: str | None
    api_key: str | None
    model_name: str
    temperature: float


def create_openai_model(config: AgentConfig, http_client: AsyncClient) -> OpenAIChatModel:
    """
    Create OpenAI model from AgentConfig.
    Loads configuration from database only.
    
    Raises:
        ValueError: If no configuration found for the agent.
    """
    model = create_model_for_agent(config.name, http_client)
    if not model:
        logger.error(
            f"No configuration found for agent '{config.name}'. "
            f"Please run 'python main.py --config' to set up the agent."
        )
        raise ValueError(
            f"Agent '{config.name}' is not configured. "
            f"Run 'python main.py --config' to configure it."
        )
    return model


def load_agent_config_chain(prefixes: list[str], defaults: AgentConfig) -> AgentConfig:
    """
    Returns the default config - actual configuration is loaded from database.
    This function is kept for API compatibility.
    """
    # Return base config with the last prefix name
    return AgentConfig(
        name=prefixes[-1].lower() if prefixes else defaults.name,
        base_url=defaults.base_url,
        api_key=defaults.api_key,
        model_name=defaults.model_name,
        temperature=defaults.temperature,
    )


def load_base_config() -> AgentConfig:
    """
    Returns a placeholder base config.
    Actual configuration is loaded from database.
    This function is kept for API compatibility.
    """
    return AgentConfig(
        name="base",
        base_url=None,
        api_key=None,
        model_name="",
        temperature=0.2,
    )
