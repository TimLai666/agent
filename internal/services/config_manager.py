"""
Configuration manager for handling different model providers.
Supports OpenAI-compatible APIs and GitHub Copilot.
"""
from dataclasses import dataclass
from typing import Optional
import time
import httpx
from httpx import AsyncClient
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.logger import logger
from internal.services.config_db import (
    AgentModelConfig,
    ProviderConfig,
    get_agent_config,
    get_provider,
)


@dataclass
class ModelConfig:
    """Complete model configuration combining provider and agent settings"""
    name: str
    provider_type: str
    base_url: Optional[str]
    api_key: Optional[str]
    github_token: Optional[str]
    model_name: str
    temperature: float


def normalize_base_url(base_url: str | None) -> str | None:
    """Normalize base URL for OpenAI-compatible APIs"""
    if not base_url:
        return None
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3].rstrip("/")
    return base_url


def get_model_config(agent_name: str) -> Optional[ModelConfig]:
    """
    Get complete model configuration for an agent.
    Returns None if no configuration exists.
    """
    # Get agent configuration
    agent_config = get_agent_config(agent_name)
    if not agent_config:
        logger.warning(f"No configuration found for agent '{agent_name}'")
        return None
    
    # Get provider configuration
    provider_config = get_provider(agent_config.provider_id)
    if not provider_config:
        logger.error(f"Provider '{agent_config.provider_id}' not found for agent '{agent_name}'")
        return None
    
    return ModelConfig(
        name=agent_name,
        provider_type=provider_config.provider_type,
        base_url=provider_config.base_url,
        api_key=provider_config.api_key,
        github_token=provider_config.github_token,
        model_name=agent_config.model_name,
        temperature=agent_config.temperature,
    )


def create_model_from_config(
    config: ModelConfig,
    http_client: AsyncClient
) -> OpenAIChatModel:
    """
    Create a pydantic-ai model from configuration.
    Supports both OpenAI-compatible APIs and GitHub Copilot.
    """
    if config.provider_type == "openai-compatible":
        return _create_openai_compatible_model(config, http_client)
    elif config.provider_type == "github-copilot":
        return _create_github_copilot_model(config, http_client)
    else:
        raise ValueError(f"Unsupported provider type: {config.provider_type}")


def _create_openai_compatible_model(
    config: ModelConfig,
    http_client: AsyncClient
) -> OpenAIChatModel:
    """Create model for OpenAI-compatible API"""
    base_url = f"{config.base_url}/v1" if config.base_url else None
    
    if not config.api_key:
        logger.warning(f"No API key configured for {config.name}")
    
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=config.api_key,
        http_client=http_client,
    )
    
    if not config.model_name:
        logger.warning(f"{config.name} model name is empty.")
    
    logger.info(f"Creating OpenAI-compatible model for {config.name}: {config.model_name} @ {base_url or 'default'}")
    
    return OpenAIChatModel(model_name=config.model_name, provider=provider)


# Copilot token cache: {github_token: (copilot_token, expires_at)}
_copilot_token_cache: dict[str, tuple[str, float]] = {}


async def _get_copilot_token(github_token: str) -> str:
    """
    Exchange GitHub OAuth token for Copilot API token.
    Two-stage auth: GitHub OAuth -> Copilot token
    Token cached for ~10min, auto-refresh before expiry.
    """
    # Check cache first
    if github_token in _copilot_token_cache:
        copilot_token, expires_at = _copilot_token_cache[github_token]
        if time.time() < expires_at - 60:
            logger.debug("Using cached Copilot token")
            return copilot_token
    
    logger.info("Exchanging GitHub token for Copilot token...")
    
    token_endpoints = [
        "https://api.github.com/copilot_internal/v2/token",
    ]
    
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/json",
        "User-Agent": "GitHubCopilotChat/1.0",
        "Editor-Version": "vscode/1.85.0",
        "Editor-Plugin-Version": "copilot-chat/0.11.0",
    }
    
    async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
        last_error = None
        
        for endpoint in token_endpoints:
            try:
                logger.debug(f"Trying Copilot token endpoint: {endpoint}")
                response = await client.get(endpoint, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    copilot_token = data.get("token")
                    expires_at_str = data.get("expires_at")
                    
                    if copilot_token:
                        # Parse expiry time
                        try:
                            if isinstance(expires_at_str, (int, float)):
                                expires_at = float(expires_at_str)
                            else:
                                from datetime import datetime
                                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00')).timestamp()
                        except Exception:
                            expires_at = time.time() + 600
                        
                        # Cache the token
                        _copilot_token_cache[github_token] = (copilot_token, expires_at)
                        
                        logger.info(f"✓ Got Copilot token from {endpoint} (expires in {int(expires_at - time.time())}s)")
                        return copilot_token
                    else:
                        logger.warning(f"Response from {endpoint} missing 'token' field")
                        
                elif response.status_code == 401:
                    logger.error(f"GitHub token unauthorized at {endpoint} - check token validity")
                    last_error = Exception(f"Unauthorized: GitHub token may be invalid or expired")
                    
                elif response.status_code == 403:
                    logger.warning(f"{endpoint} returned 403 - trying next endpoint")
                    last_error = Exception(f"Forbidden: {response.text}")
                    
                else:
                    logger.warning(f"{endpoint} returned {response.status_code}: {response.text}")
                    last_error = Exception(f"HTTP {response.status_code}: {response.text}")
                    
            except Exception as e:
                logger.debug(f"Failed to get token from {endpoint}: {e}")
                last_error = e
                continue
    
    # All endpoints failed
    error_msg = f"Failed to exchange GitHub token for Copilot token. Last error: {last_error}"
    logger.error(error_msg)
    raise Exception(error_msg)


def _create_github_copilot_model(
    config: ModelConfig,
    http_client: AsyncClient
) -> OpenAIChatModel:
    """
    Create GitHub Copilot model with two-stage authentication.
    
    Uses custom HTTP interceptor to:
    1. Exchange GitHub token for Copilot token
    2. Inject Copilot token and required headers into requests
    
    Key headers:
    - Authorization: Bearer {copilot_token}
    - X-Initiator: agent (affects premium quota)
    """
    if not config.github_token:
        logger.error(f"No GitHub token configured for {config.name}")
        raise ValueError("GitHub token is required for Copilot")
    
    logger.info(f"Setting up GitHub Copilot model for {config.name}")
    
    github_copilot_base_url = "https://api.githubcopilot.com"
    
    # Create a custom HTTP client with interceptor to handle token exchange
    from httpx import AsyncClient as HTTPXClient, Request, Response
    import asyncio
    
    class CopilotTokenInterceptor(HTTPXClient):
        """HTTP client that auto-injects Copilot token and headers"""
        
        def __init__(self, github_token: str, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.github_token = github_token
            self._token_lock = asyncio.Lock()
        
        async def send(self, request: Request, *args, **kwargs) -> Response:
            # Get Copilot token
            async with self._token_lock:
                try:
                    copilot_token = await _get_copilot_token(self.github_token)
                except Exception as e:
                    logger.error(f"Failed to get Copilot token: {e}")
                    raise
            
            # Inject headers
            request.headers["Authorization"] = f"Bearer {copilot_token}"
            request.headers["X-Initiator"] = "agent"
            request.headers["User-Agent"] = "GitHubCopilotChat/1.0"
            request.headers["Editor-Version"] = "vscode/1.85.0"
            request.headers["Editor-Plugin-Version"] = "copilot-chat/0.11.0"
            
            logger.debug(f"Copilot API request: {request.method} {request.url}")
            
            # Send request and get response
            response = await super().send(request, *args, **kwargs)
            
            # Fix Copilot API response to be OpenAI-compatible
            # GitHub Copilot sometimes returns None for 'object' field
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    import json
                    response_data = response.json()
                    
                    # Fix missing or None 'object' field
                    if response_data.get("object") is None:
                        response_data["object"] = "chat.completion"
                        
                        # Reconstruct response with fixed data
                        from httpx import Response as HTTPXResponse
                        fixed_response = HTTPXResponse(
                            status_code=response.status_code,
                            headers=response.headers,
                            content=json.dumps(response_data).encode(),
                            request=response.request,
                        )
                        logger.debug("Fixed Copilot response 'object' field")
                        return fixed_response
                except Exception as e:
                    logger.debug(f"Could not fix response format: {e}")
            
            return response
    
    copilot_http_client = CopilotTokenInterceptor(
        github_token=config.github_token,
        timeout=60.0,
        verify=False
    )
    
    # Dummy api_key since interceptor handles auth
    provider = OpenAIProvider(
        base_url=github_copilot_base_url,
        api_key="dummy",
        http_client=copilot_http_client,
    )
    
    if not config.model_name:
        logger.warning(f"{config.name} model name is empty.")
    
    logger.info(f"GitHub Copilot ready: {config.model_name}")
    
    return OpenAIChatModel(model_name=config.model_name, provider=provider)


def create_model_for_agent(
    agent_name: str,
    http_client: AsyncClient,
) -> Optional[OpenAIChatModel]:
    """
    Create a model for a specific agent.
    
    Args:
        agent_name: Name of the agent (e.g., "main", "philosopher")
        http_client: HTTP client for API calls
    
    Returns:
        OpenAIChatModel instance or None if configuration not available
    """
    config = get_model_config(agent_name)
    
    if not config:
        logger.error(
            f"No configuration found for agent '{agent_name}'. "
            f"Please run 'python main.py --config' to set up the agent."
        )
        return None
    
    try:
        return create_model_from_config(config, http_client)
    except Exception as e:
        logger.error(f"Failed to create model for agent '{agent_name}': {e}")
        return None
