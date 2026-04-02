#!/usr/bin/env python3
"""
Migration helper script: migrate from environment variables to database config.
Edit this script with your current configuration, then run it.
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
    set_agent_config,
)


def migrate():
    """
    Migrate your configuration here.
    Edit the examples below to match your current setup.
    """
    
    # Example 1: Add OpenAI provider
    print("新增 OpenAI 提供者...")
    add_provider(ProviderConfig(
        provider_id="openai",
        provider_type="openai-compatible",
        name="OpenAI",
        base_url=None,  # Uses default: https://api.openai.com
        api_key="YOUR_OPENAI_API_KEY_HERE",  # ⚠️ Replace with your actual key
    ))
    print("✓ OpenAI 提供者已新增")
    
    # Example 2: Add Anthropic provider (uncomment and edit if you use Claude)
    # print("新增 Anthropic 提供者...")
    # add_provider(ProviderConfig(
    #     provider_id="anthropic",
    #     provider_type="openai-compatible",
    #     name="Anthropic Claude",
    #     base_url="https://api.anthropic.com",
    #     api_key="YOUR_ANTHROPIC_API_KEY_HERE",
    # ))
    # print("✓ Anthropic 提供者已新增")
    
    # Example 3: Add local Ollama provider (uncomment if you use Ollama)
    # print("新增 Ollama 提供者...")
    # add_provider(ProviderConfig(
    #     provider_id="ollama",
    #     provider_type="openai-compatible",
    #     name="Ollama Local",
    #     base_url="http://localhost:11434",
    #     api_key=None,  # No API key needed for local
    # ))
    # print("✓ Ollama 提供者已新增")
    
    # Example 4: Add GitHub Copilot provider (uncomment if you use Copilot)
    # print("新增 GitHub Copilot 提供者...")
    # add_provider(ProviderConfig(
    #     provider_id="github-copilot",
    #     provider_type="github-copilot",
    #     name="GitHub Copilot",
    #     github_token="YOUR_GITHUB_TOKEN_HERE",  # Get with: gh auth token
    # ))
    # print("✓ GitHub Copilot 提供者已新增")
    
    # Configure main agent
    print("\n設定 main agent...")
    set_agent_config(AgentModelConfig(
        agent_name="main",
        provider_id="openai",  # ⚠️ Change if you use a different provider
        model_name="gpt-4",    # ⚠️ Change to your model (e.g., claude-3-5-sonnet-20241022)
        temperature=0.5,       # ⚠️ Adjust as needed
    ))
    print("✓ main agent 已設定")
    
    # Configure additional agents as needed (example: marketing)
    # print("設定 marketing agent...")
    # set_agent_config(AgentModelConfig(
    #     agent_name="marketing",
    #     provider_id="anthropic",  # Or use same as main
    #     model_name="claude-3-5-sonnet-20241022",
    #     temperature=0.2,
    # ))
    # print("✓ marketing agent 已設定")
    
    # Add more agents as needed...
    
    print("\n" + "=" * 60)
    print("  遷移完成！")
    print("=" * 60)
    print("\n下一步:")
    print("  1. 測試配置: uv run main.py")
    print("  2. 查看配置: uv run main.py --config")
    print("  3. (選用) 備份並移除 .env 中的模型配置")


def verify_before_migration():
    """Verify that user has edited the script"""
    import re
    
    # Read this file
    with open(__file__, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if user has replaced placeholder keys
    if 'YOUR_OPENAI_API_KEY_HERE' in content or 'YOUR_ANTHROPIC_API_KEY_HERE' in content:
        print("⚠️  警告: 偵測到預設佔位符")
        print("\n請先編輯此腳本 (scripts/migrate_from_env.py)，")
        print("將佔位符替換為你的實際配置，然後再次執行。")
        print("\n需要替換的內容:")
        print("  - YOUR_OPENAI_API_KEY_HERE")
        print("  - provider_id (如果使用其他提供者)")
        print("  - model_name (你的模型名稱)")
        print("  - temperature (根據需要調整)")
        print("\n提示: 查看你的 .env 檔案了解現有配置")
        return False
    
    return True


def main():
    print("\n" + "=" * 60)
    print("  配置遷移腳本")
    print("=" * 60)
    
    if not verify_before_migration():
        return 1
    
    try:
        migrate()
        return 0
    except Exception as e:
        print(f"\n❌ 遷移失敗: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
