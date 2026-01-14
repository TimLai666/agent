from internal.mcp.client_builder import McpClient

browser = McpClient(
    command="npx",
    args=["@playwright/mcp@latest"],
    tool_prefix="playwright-",
)