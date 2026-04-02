from internal.mcp.client_builder import McpClient

playwright = McpClient(
    command="npx",
    args=["@playwright/mcp@latest"],
    tool_prefix="playwright_",
)