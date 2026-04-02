#!/usr/bin/env python3
"""
Test script for the configuration system.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from internal.services.config_db import (
    AgentModelConfig,
    ProviderConfig,
    add_provider,
    delete_agent_config,
    delete_provider,
    get_agent_config,
    get_provider,
    list_agent_configs,
    list_providers,
    set_agent_config,
)


def print_header(text: str):
    """Print a header"""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def test_provider_operations():
    """Test provider CRUD operations"""
    print_header("測試提供者操作")
    
    # Add OpenAI provider
    print("1. 新增 OpenAI 提供者...")
    openai_provider = ProviderConfig(
        provider_id="test-openai",
        provider_type="openai-compatible",
        name="Test OpenAI",
        base_url="https://api.openai.com",
        api_key="test-key-123",
    )
    assert add_provider(openai_provider)
    print("✓ 成功")
    
    # Add GitHub Copilot provider
    print("2. 新增 GitHub Copilot 提供者...")
    copilot_provider = ProviderConfig(
        provider_id="test-copilot",
        provider_type="github-copilot",
        name="Test GitHub Copilot",
        github_token="ghp_test123",
    )
    assert add_provider(copilot_provider)
    print("✓ 成功")
    
    # List providers
    print("3. 列出所有提供者...")
    providers = list_providers()
    assert len(providers) >= 2
    for p in providers:
        if p.provider_id.startswith("test-"):
            print(f"   - {p.provider_id}: {p.name} ({p.provider_type})")
    print("✓ 成功")
    
    # Get provider
    print("4. 取得特定提供者...")
    provider = get_provider("test-openai")
    assert provider is not None
    assert provider.name == "Test OpenAI"
    print(f"   - 找到: {provider.name}")
    print("✓ 成功")


def test_agent_operations():
    """Test agent configuration operations"""
    print_header("測試 Agent 配置操作")
    
    # Set agent config
    print("1. 設定 main agent...")
    main_config = AgentModelConfig(
        agent_name="test-main",
        provider_id="test-openai",
        model_name="gpt-4",
        temperature=0.5,
    )
    assert set_agent_config(main_config)
    print("✓ 成功")
    
    # Set another agent
    print("2. 設定 marketing agent...")
    marketing_config = AgentModelConfig(
        agent_name="test-marketing",
        provider_id="test-copilot",
        model_name="gpt-3.5-turbo",
        temperature=0.3,
    )
    assert set_agent_config(marketing_config)
    print("✓ 成功")
    
    # List agent configs
    print("3. 列出所有 agent 配置...")
    configs = list_agent_configs()
    assert len(configs) >= 2
    for c in configs:
        if c.agent_name.startswith("test-"):
            print(f"   - {c.agent_name}: {c.model_name} @ {c.provider_id}")
    print("✓ 成功")
    
    # Get agent config
    print("4. 取得特定 agent 配置...")
    config = get_agent_config("test-main")
    assert config is not None
    assert config.model_name == "gpt-4"
    print(f"   - 找到: {config.agent_name} -> {config.model_name}")
    print("✓ 成功")


def test_config_manager():
    """Test config manager"""
    print_header("測試配置管理器")
    
    from internal.services.config_manager import get_model_config
    
    print("1. 取得 agent 的完整配置...")
    model_config = get_model_config("test-main")
    assert model_config is not None
    assert model_config.provider_type == "openai-compatible"
    assert model_config.model_name == "gpt-4"
    assert model_config.base_url == "https://api.openai.com"
    print(f"   - Agent: {model_config.name}")
    print(f"   - Provider: {model_config.provider_type}")
    print(f"   - Model: {model_config.model_name}")
    print(f"   - Base URL: {model_config.base_url}")
    print("✓ 成功")


def cleanup():
    """Clean up test data"""
    print_header("清理測試資料")
    
    print("1. 刪除測試 agent 配置...")
    delete_agent_config("test-main")
    delete_agent_config("test-marketing")
    print("✓ 成功")
    
    print("2. 刪除測試提供者...")
    delete_provider("test-openai")
    delete_provider("test-copilot")
    print("✓ 成功")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  Agent 配置系統測試")
    print("=" * 60)
    
    try:
        test_provider_operations()
        test_agent_operations()
        test_config_manager()
        
        print_header("所有測試通過 ✓")
        
    except AssertionError as e:
        print(f"\n❌ 測試失敗: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cleanup()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
