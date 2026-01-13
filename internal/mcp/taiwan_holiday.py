from internal.mcp.client_builder import McpClient

taiwan_holiday = McpClient(
    command="npx",
    args=["@bachstudio/taiwan-holiday-mcp@latest"],
)