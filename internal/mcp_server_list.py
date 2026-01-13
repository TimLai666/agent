from pydantic_ai.mcp import MCPServerStdio
from internal.mcp.time import time
from internal.mcp.fetch import fetch
from internal.mcp.cook import cook
from internal.mcp.browser import browser
from internal.mcp.taiwan_holiday import taiwan_holiday

all_mcp_servers: list[MCPServerStdio] = [
    time, fetch, cook, browser, taiwan_holiday,
]
