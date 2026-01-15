from pydantic_ai.mcp import MCPServerStdio
from internal.mcp.client_builder import McpClient
from internal.mcp.time import time
from internal.mcp.fetch import fetch
from internal.mcp.cook import cook
from internal.mcp.browser import browser
from internal.mcp.taiwan_holiday import taiwan_holiday
from internal.mcp.package_docs import package_docs
from internal.services.config_db import list_mcp_tools, list_remote_mcps, get_mcp_last_updated
from internal.mcp.remote_mcp_loader import load_remote_mcp_from_url
from internal.logger import logger


# Cache for MCP servers
_mcp_cache: list[MCPServerStdio] | None = None
_last_cache_timestamp: str | None = None


# Start with a function that returns the list of built-in MCP servers
def get_built_in_mcp_servers() -> list[MCPServerStdio]:
    """Returns a fresh list of built-in MCP servers."""
    return [
        time, fetch, cook, browser, taiwan_holiday,
        package_docs,
    ]


def _load_mcp_servers() -> list[MCPServerStdio]:
    """Internal function to load MCP servers from database."""
    all_servers = get_built_in_mcp_servers()

    try:
        custom_tools = list_mcp_tools()
        logger.debug(f"Found {len(custom_tools)} custom MCP tools in the database.")
        for tool_config in custom_tools:
            try:
                args = tool_config.args.split() if tool_config.args else []
                # Prefix tools coming from this MCP with the MCP's id to avoid name collisions
                tool_prefix = f"{tool_config.mcp_tool_id}_"
                custom_tool_client = McpClient(
                    command=tool_config.command,
                    args=args,
                    tool_prefix=tool_prefix,
                )
                all_servers.append(custom_tool_client)
                logger.debug(f"Successfully loaded custom MCP tool: '{tool_config.name}' (prefix={tool_prefix})")
            except Exception as e:
                logger.error(f"Failed to create McpClient for tool '{tool_config.name}': {e}")
    except Exception as e:
        logger.error(f"Failed to load custom MCP tools from database: {e}")

    try:
        remote_mcps = list_remote_mcps()
        logger.debug(f"Found {len(remote_mcps)} remote MCP configurations in the database.")
        for remote_config in remote_mcps:
            try:
                # Pass the remote MCP's id as prefix so tools loaded from this URL are namespaced
                remote_clients = load_remote_mcp_from_url(remote_config.url, prefix=remote_config.remote_mcp_id)
                for client in remote_clients:
                    all_servers.append(client)
                logger.debug(f"Successfully loaded {len(remote_clients)} remote MCP tools from URL: '{remote_config.url}' (mcp_id={remote_config.remote_mcp_id})")
            except Exception as e:
                logger.error(f"Failed to load remote MCP from URL '{remote_config.url}': {e}")
    except Exception as e:
        logger.error(f"Failed to load remote MCP configurations from database: {e}")

    return all_servers


def get_all_mcp_servers() -> list[MCPServerStdio]:
    """
    Load all MCP servers, including built-in and custom tools from the database.
    Uses caching to avoid unnecessary reloads - only refreshes when MCP settings change.
    """
    global _mcp_cache, _last_cache_timestamp

    # Check if settings have been updated
    current_timestamp = get_mcp_last_updated()

    # Use cache if available and settings haven't changed
    if _mcp_cache is not None and _last_cache_timestamp == current_timestamp:
        logger.debug("Using cached MCP servers (no changes detected)")
        return _mcp_cache

    # Settings changed or first load - reload from database
    logger.debug(f"Reloading MCP servers (timestamp changed: {_last_cache_timestamp} -> {current_timestamp})")
    _mcp_cache = _load_mcp_servers()
    _last_cache_timestamp = current_timestamp

    return _mcp_cache


def invalidate_mcp_cache():
    """Force reload of MCP servers on next get_all_mcp_servers() call."""
    global _mcp_cache, _last_cache_timestamp
    _mcp_cache = None
    _last_cache_timestamp = None
    logger.debug("MCP cache invalidated")
