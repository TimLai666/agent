from internal.mcp.client_builder import McpClient

computer_use = McpClient(
    command="npx",
    args=["-y", "computer-use-mcp"],
)
