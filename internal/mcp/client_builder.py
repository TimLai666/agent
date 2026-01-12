from pydantic_ai.mcp import MCPServerStdio

def McpClient(command, args, env=None, timeout=100) -> MCPServerStdio:
    return MCPServerStdio(
        command=command,
        args=args,
        env=env,
        timeout=timeout,
    )