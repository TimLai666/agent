from internal.mcp.client_builder import McpClientSSE
from internal.logger import logger

def load_remote_mcp_from_url(url: str, prefix: str | None = None) -> list:
    """
    Creates an SSE MCP client connecting to the remote URL.
    
    Args:
        url: The remote SSE endpoint URL to connect to
        prefix: Optional prefix (usually the remote MCP id) to apply to tools
    
    Returns:
        A list containing a single MCPServerSSE client, or empty list on error
    """
    logger.info(f"Creating SSE MCP client for URL: {url} (prefix={prefix})")
    try:
        # Create SSE client with the provided prefix
        tool_prefix = f"{prefix}-" if prefix else None
        sse_client = McpClientSSE(
            url=url,
            tool_prefix=tool_prefix,
            timeout=60,  # 60 second timeout (pydantic-ai MCP timeout is in seconds)
        )
        logger.debug(f"Successfully created SSE MCP client for {url} (prefix={tool_prefix})")
        return [sse_client]
    except Exception as e:
        logger.error(f"Failed to create SSE MCP client for {url}: {e}")
        return []

