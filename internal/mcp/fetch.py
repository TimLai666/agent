from internal.mcp.client_builder import McpClient

fetch = McpClient(
    command="uvx",
    args=["mcp-server-fetch"],
)