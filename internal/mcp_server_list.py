from pydantic_ai.mcp import MCPServerStdio
from internal.mcp.client_builder import McpClient
from internal.mcp.time import time
from internal.mcp.fetch import fetch
from internal.mcp.cook import cook
from internal.mcp.browser import browser
from internal.mcp.taiwan_holiday import taiwan_holiday
from internal.services.config_db import list_mcp_tools, list_remote_mcps
from internal.mcp.remote_mcp_loader import load_remote_mcp_from_url
from internal.logger import logger


# Start with a function that returns the list of built-in MCP servers
def get_built_in_mcp_servers() -> list[MCPServerStdio]:
    """Returns a fresh list of built-in MCP servers."""
    return [
        time, fetch, cook, browser, taiwan_holiday,
    ]

def get_all_mcp_servers() -> list[MCPServerStdio]:
    """
    Load all MCP servers, including built-in and custom tools from the database.
    This function ensures the list is always up-to-date.
    """
    all_servers = get_built_in_mcp_servers()
    
    try:
        custom_tools = list_mcp_tools()
        logger.debug(f"Found {len(custom_tools)} custom MCP tools in the database.")
        for tool_config in custom_tools:
            try:
                args = tool_config.args.split() if tool_config.args else []
                # Prefix tools coming from this MCP with the MCP's id to avoid name collisions
                tool_prefix = f"{tool_config.mcp_tool_id}-"
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
