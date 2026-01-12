from pydantic_ai.mcp import MCPServerStdio

def McpClient(command, args, timeout=100) -> MCPServerStdio:
    return MCPServerStdio(
        command=command,
        args=args,
        timeout=timeout,
    )