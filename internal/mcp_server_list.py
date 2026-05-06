import shlex

from pydantic_ai.mcp import MCPServerStdio
from internal.mcp.client_builder import McpClient
from internal.services.config_db import list_mcp_tools, list_remote_mcps, get_mcp_last_updated
from internal.mcp.remote_mcp_loader import load_remote_mcp_from_url
from internal.logger import logger


# Cache timestamp only — full server list is intentionally rebuilt every call;
# see get_all_mcp_servers() for why instances are not cached.
_last_cache_timestamp: str | None = None


# Start with a function that returns the list of built-in MCP servers
def get_built_in_mcp_servers() -> list[MCPServerStdio]:
    """Build *fresh* instances of the built-in MCP servers on every call.

    Each MCPServerStdio holds a subprocess and an AsyncExitStack-managed
    transport. Sharing one instance across multiple `run_mcp_servers()`
    lifetimes (different MainAgent/session contexts) is unsafe: the closed
    transport cannot be re-entered, and two concurrent sessions cannot
    share one stdio subprocess.
    """
    return [
        McpClient(command="uvx", args=["mcp-server-fetch"]),
        McpClient(
            command="npx",
            args=["@playwright/mcp@latest"],
            tool_prefix="playwright_",
        ),
        McpClient(command="npx", args=["@bachstudio/taiwan-holiday-mcp@latest"]),
        McpClient(command="npx", args=["-y", "computer-use-mcp"]),
    ]


def _load_mcp_servers() -> list[MCPServerStdio]:
    """Internal function to load MCP servers from database."""
    all_servers = get_built_in_mcp_servers()

    try:
        custom_tools = list_mcp_tools()
        logger.debug(f"Found {len(custom_tools)} custom MCP tools in the database.")
        for tool_config in custom_tools:
            try:
                try:
                    args = shlex.split(tool_config.args) if tool_config.args else []
                except ValueError as parse_err:
                    logger.warning(
                        "Failed to shlex-split args for tool '%s' (%s); falling back to whitespace split.",
                        tool_config.name,
                        parse_err,
                    )
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

    NOTE: This intentionally returns *fresh* MCPServerStdio/MCPServerSSE
    instances on every call. Caching the same server instances across multiple
    MainAgent / run_mcp_servers() lifetimes is unsafe — once a server's
    AsyncExitStack-managed transport closes, that instance cannot be re-entered
    in a new context, and two concurrent sessions cannot share one stdio
    subprocess. We only keep `_last_cache_timestamp` for diagnostic logging.
    """
    global _last_cache_timestamp

    current_timestamp = get_mcp_last_updated()
    if _last_cache_timestamp != current_timestamp:
        logger.debug(
            "MCP settings timestamp changed: %s -> %s",
            _last_cache_timestamp,
            current_timestamp,
        )
        _last_cache_timestamp = current_timestamp

    return _load_mcp_servers()


