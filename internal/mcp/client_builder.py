from pathlib import Path
from pydantic_ai.mcp import MCPServerStdio, MCPServerSSE

def McpClient(command, args, env=None, tool_prefix=None, timeout=120, cwd=None) -> MCPServerStdio:
    """Create an MCP client with optional working directory.

    Args:
        command: The command to run
        args: Command arguments
        env: Environment variables
        tool_prefix: Tool name prefix
        timeout: Connection timeout in seconds (default 120s)
        cwd: Working directory for the MCP server process (defaults to sandbox dir)
    """
    # 如果沒有指定 cwd，預設使用沙盒目錄，避免 MCP 產生的文件出現在真實 CWD
    from internal.paths import TIM_AGENT_SANDBOX_DIR
    work_dir = cwd or TIM_AGENT_SANDBOX_DIR
    
    return MCPServerStdio(
        command=command,
        args=args,
        env=env,
        timeout=timeout,
        tool_prefix=tool_prefix,
        cwd=str(work_dir),
    )

def McpClientSSE(url, tool_prefix=None, timeout=120) -> MCPServerSSE:
    """Create an SSE MCP client. timeout is in seconds (default 120s)."""
    return MCPServerSSE(
        url=url,
        timeout=timeout,
        tool_prefix=tool_prefix,
    )