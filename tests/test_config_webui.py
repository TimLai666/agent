from internal.services import config_db, config_webui


def test_provider_update_keeps_existing_api_key_when_field_is_omitted(tmp_path):
    original_db_path = config_db.DB_PATH
    try:
        config_db.DB_PATH = tmp_path / "config.db"
        config_db.init_database()

        assert config_db.add_provider(
            config_db.ProviderConfig(
                provider_id="openai",
                provider_type="openai-compatible",
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                api_key="sk-existing",
            )
        )

        client = config_webui.app.test_client()
        response = client.post(
            "/api/providers",
            json={
                "provider_id": "openai",
                "provider_type": "openai-compatible",
                "name": "OpenAI Renamed",
                "base_url": "https://api.openai.com/v1",
            },
        )

        assert response.status_code == 200
        updated = config_db.get_provider("openai")
        assert updated is not None
        assert updated.name == "OpenAI Renamed"
        assert updated.api_key == "sk-existing"
    finally:
        config_db.DB_PATH = original_db_path


def test_provider_type_switch_keeps_existing_api_key_when_not_reentered(tmp_path):
    original_db_path = config_db.DB_PATH
    try:
        config_db.DB_PATH = tmp_path / "config.db"
        config_db.init_database()

        assert config_db.add_provider(
            config_db.ProviderConfig(
                provider_id="shared-provider",
                provider_type="openai-compatible",
                name="Shared Provider",
                base_url="https://example.com/v1",
                api_key="sk-existing",
            )
        )

        client = config_webui.app.test_client()
        response = client.post(
            "/api/providers",
            json={
                "provider_id": "shared-provider",
                "provider_type": "github-copilot",
                "name": "Shared Provider",
                "github_token": "ghp-new-token",
            },
        )

        assert response.status_code == 200
        updated = config_db.get_provider("shared-provider")
        assert updated is not None
        assert updated.provider_type == "github-copilot"
        assert updated.github_token == "ghp-new-token"
        assert updated.api_key == "sk-existing"
    finally:
        config_db.DB_PATH = original_db_path
