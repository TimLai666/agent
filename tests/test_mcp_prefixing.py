import os
from internal.services import config_db
from internal.mcp_server_list import get_all_mcp_servers
from internal.mcp.client_builder import McpClient
import internal.mcp.remote_mcp_loader as loader


def test_local_and_remote_mcp_prefixing(tmp_path, monkeypatch):
    original_db_path = config_db.DB_PATH
    try:
        # Use isolated DB
        config_db.DB_PATH = tmp_path / "config.db"
        config_db.init_database()

        # Add a local/custom MCP tool
        local_tool = config_db.McpToolConfig(
            mcp_tool_id="local1",
            name="Local One",
            command="/bin/echo",
            args="hello",
        )
        assert config_db.add_mcp_tool(local_tool)

        # Add a remote MCP entry
        remote_cfg = config_db.RemoteMcpConfig(
            remote_mcp_id="rem1",
            name="Remote One",
            url="https://example.com/mcp.json",
        )
        assert config_db.add_remote_mcp(remote_cfg)

        # Monkeypatch loader to simulate returning a client and capture prefix
        def fake_load(url, prefix=None):
            # return a client that has the tool_prefix set based on prefix arg
            return [McpClient(command="/bin/echo", args=[], tool_prefix=(f"{prefix}-" if prefix else None))]

        monkeypatch.setattr(loader, "load_remote_mcp_from_url", fake_load)

        servers = get_all_mcp_servers()

        prefixes = [getattr(s, 'tool_prefix', None) for s in servers if getattr(s, 'tool_prefix', None)]

        # Expect at least one local prefix and one remote prefix
        assert any(p and p.startswith('local1') for p in prefixes), f"No local prefix found in {prefixes}"
        assert any(p and p.startswith('rem1') for p in prefixes), f"No remote prefix found in {prefixes}"

    finally:
        config_db.DB_PATH = original_db_path
