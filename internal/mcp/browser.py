from internal.mcp.client_builder import McpClient

playwright = McpClient(
    command="npx",
    args=["@playwright/mcp@latest"],
    tool_prefix="playwright_",
)

chrome = McpClient(
    command="npx",
    args=["-y", "chrome-devtools-mcp@latest"],
    tool_prefix="chrome_",
)