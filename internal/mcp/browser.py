import platform
from internal.mcp.client_builder import McpClient
from pydantic_ai.mcp import MCPServerStdio

playwright = McpClient(
    command="npx",
    args=["@playwright/mcp@latest"],
    tool_prefix="playwright_",
)


chrome: MCPServerStdio
isWindows: bool = platform.system() == "Windows"
if isWindows == False:
    chrome = McpClient(
        command="npx",
        args=["-y", "chrome-devtools-mcp@latest"],
        tool_prefix="chrome_",
    )
else:
    chrome = McpClient(
        command="cmd",
        args=[
            "/c",
            "npx",
            "-y",
            "chrome-devtools-mcp@latest",
        ],
        env = { "SystemRoot":"C:\\Windows", "PROGRAMFILES":"C:\\Program Files" },
        tool_prefix="chrome_",
    )
print(chrome)