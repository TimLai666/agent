from internal.mcp.client_builder import McpClient

time = McpClient(
    command="uvx",
    args=["mcp-server-time"],
)