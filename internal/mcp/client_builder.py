from pydantic_ai.mcp import MCPServerStdio, MCPServerSSE

def McpClient(command, args, env=None, tool_prefix=None, timeout=1000) -> MCPServerStdio:
    return MCPServerStdio(
        command=command,
        args=args,
        env=env,
        timeout=timeout,
        tool_prefix=tool_prefix,
    )
    
def McpClientSSE(url, tool_prefix=None, timeout=1000) -> MCPServerSSE:
    return MCPServerSSE(
        url=url,
        timeout=timeout,
        tool_prefix=tool_prefix,
    )