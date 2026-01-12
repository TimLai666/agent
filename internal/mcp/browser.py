from internal.mcp.client_builder import McpClient

browser = McpClient(
    command="npx",
    args=["pptr-mcp","--viewport=1280x720"],
)