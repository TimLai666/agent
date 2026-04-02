import os
from internal.services import config_db


def test_remote_mcp_crud(tmp_path):
    # Use an isolated database for the test
    original_db_path = config_db.DB_PATH
    try:
        config_db.DB_PATH = tmp_path / "config.db"
        config_db.init_database()

        cfg = config_db.RemoteMcpConfig(
            remote_mcp_id="test-remote-1",
            name="Test Remote",
            url="https://example.com/mcp.json",
        )

        assert config_db.add_remote_mcp(cfg) is True

        mcps = config_db.list_remote_mcps()
        assert any(m.remote_mcp_id == "test-remote-1" for m in mcps)

        assert config_db.delete_remote_mcp("test-remote-1") is True

        mcps_after = config_db.list_remote_mcps()
        assert not any(m.remote_mcp_id == "test-remote-1" for m in mcps_after)

    finally:
        # Restore DB_PATH
        config_db.DB_PATH = original_db_path
        # Cleanup if any file was created
        try:
            if (tmp_path / "config.db").exists():
                (tmp_path / "config.db").unlink()
        except Exception:
            pass
