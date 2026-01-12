from internal.mcp.client_builder import McpClient

cook = McpClient(
    command="npx",
    args=["-y","howtocook-mcp"],
)