from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.logger import logger


@dataclass
class AgentConfig:
    name: str
    base_url: str | None
    api_key: str | None
    model_name: str
    temperature: float


def normalize_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3].rstrip("/")
    return base_url


def create_openai_model(config: AgentConfig, http_client: AsyncClient) -> OpenAIModel:
    base_url = f"{config.base_url}/v1" if config.base_url else None
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=config.api_key,
        http_client=http_client,
    )
    if not config.model_name:
        logger.warning(f"{config.name} model name is empty.")
    return OpenAIModel(model_name=config.model_name, provider=provider)


def load_agent_config(
    prefix: str, defaults: AgentConfig, env: dict[str, str]
) -> AgentConfig:
    base_url = normalize_base_url(
        _get_env_value(env, prefix, "OPENAI_BASE_URL", defaults.base_url)
    )
    api_key = _get_env_value(env, prefix, "OPENAI_API_KEY", defaults.api_key)
    model_name = _get_env_value(env, prefix, "MODEL_NAME", defaults.model_name)
    temperature = _get_env_float(env, prefix, "MODEL_TEMPERATURE", defaults.temperature)
    return AgentConfig(
        name=prefix.lower(),
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
    )


def load_agent_config_chain(
    prefixes: list[str], defaults: AgentConfig, env: dict[str, str]
) -> AgentConfig:
    config = defaults
    for prefix in prefixes:
        config = load_agent_config(prefix, config, env)
    return config


def load_base_config(env: dict[str, str]) -> AgentConfig:
    base_temperature = 0.2
    if env.get("MODEL_TEMPERATURE"):
        try:
            base_temperature = float(env["MODEL_TEMPERATURE"])
        except ValueError:
            logger.warning(
                f"Invalid MODEL_TEMPERATURE '{env['MODEL_TEMPERATURE']}', using default {base_temperature}."
            )
    return AgentConfig(
        name="base",
        base_url=normalize_base_url(env.get("OPENAI_BASE_URL")),
        api_key=env.get("OPENAI_API_KEY"),
        model_name=env.get("MODEL_NAME") or "",
        temperature=base_temperature,
    )


def _get_env_value(env: dict[str, str], prefix: str, key: str, default: Any) -> Any:
    prefixed_key = f"{prefix}_{key}"
    if prefixed_key in env and env[prefixed_key]:
        return env[prefixed_key]
    return default


def _get_env_float(env: dict[str, str], prefix: str, key: str, default: float) -> float:
    raw = _get_env_value(env, prefix, key, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"Invalid {prefix}_{key} '{raw}', using default {default}.")
        return default
