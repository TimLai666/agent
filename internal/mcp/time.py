from pydantic_ai.mcp import MCPServerStdio

time = MCPServerStdio(
    command="uvx",
    args=["mcp-server-time"],
)