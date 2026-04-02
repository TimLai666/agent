"""
CLI commands for managing agent configurations.
"""
import sys
from pathlib import Path
from typing import Optional

from internal.logger import logger
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
    """Print a header line"""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_provider(provider: ProviderConfig):
    """Print provider information"""
    print(f"\n  ID: {provider.provider_id}")
    print(f"  名稱: {provider.name}")
    print(f"  類型: {provider.provider_type}")
    if provider.provider_type == "openai-compatible":
        print(f"  Base URL: {provider.base_url or '(預設)'}")
        print(f"  API Key: {'*' * 8 if provider.api_key else '(未設定)'}")
    elif provider.provider_type == "github-copilot":
        print(f"  GitHub Token: {'*' * 8 if provider.github_token else '(未設定)'}")


def print_agent_config(config: AgentModelConfig):
    """Print agent configuration"""
    print(f"\n  Agent: {config.agent_name}")
    print(f"  提供者: {config.provider_id}")
    print(f"  模型: {config.model_name}")
    print(f"  Temperature: {config.temperature}")


def cmd_config_list_providers():
    """List all configured providers"""
    print_header("已設定的提供者")
    providers = list_providers()
    
    if not providers:
        print("\n  (尚無設定)")
        return
    
    for provider in providers:
        print_provider(provider)


def cmd_config_add_openai_provider():
    """Add an OpenAI-compatible provider"""
    print_header("新增 OpenAI 相容 API 提供者")
    
    provider_id = input("提供者 ID (例如: openai, anthropic): ").strip()
    if not provider_id:
        print("錯誤: 提供者 ID 不可為空")
        return
    
    name = input("顯示名稱: ").strip()
    if not name:
        name = provider_id
    
    base_url = input("Base URL (按 Enter 使用預設 OpenAI): ").strip() or None
    api_key = input("API Key: ").strip() or None
    
    config = ProviderConfig(
        provider_id=provider_id,
        provider_type="openai-compatible",
        name=name,
        base_url=base_url,
        api_key=api_key,
    )
    
    if add_provider(config):
        print(f"✓ 成功新增提供者: {provider_id}")
    else:
        print(f"✗ 新增失敗")


def cmd_config_add_github_copilot_provider():
    """Add a GitHub Copilot provider"""
    print_header("新增 GitHub Copilot 提供者")
    
    provider_id = input("提供者 ID (例如: github-copilot): ").strip()
    if not provider_id:
        print("錯誤: 提供者 ID 不可為空")
        return
    
    name = input("顯示名稱: ").strip()
    if not name:
        name = provider_id
    
    # Ask user if they want to auto-fetch token
    print("\n取得 GitHub Token 方式:")
    print("  1. 瀏覽器登入 (推薦，無需安裝 gh CLI)")
    print("  2. 自動取得 (使用 gh CLI)")
    print("  3. 手動輸入")
    choice = input("\n選擇 (1/2/3, 預設 1): ").strip() or "1"
    
    github_token = None
    
    if choice == "1":
        print("\n正在啟動瀏覽器認證...")
        github_token = _browser_github_login()
        
        if github_token:
            print(f"✓ 成功取得 Token: {github_token[:20]}...")
    elif choice == "2":
        print("\n正在嘗試自動取得 GitHub Token...")
        github_token = _auto_get_github_token()
        
        if github_token:
            print(f"✓ 成功取得 Token: {github_token[:20]}...")
            confirm = input("\n使用此 Token? (Y/n): ").strip().upper()
            if confirm == "N":
                github_token = None
    
    if not github_token:
        github_token = input("\n請手動輸入 GitHub Token: ").strip() or None
    
    config = ProviderConfig(
        provider_id=provider_id,
        provider_type="github-copilot",
        name=name,
        github_token=github_token,
    )
    
    if add_provider(config):
        print(f"✓ 成功新增提供者: {provider_id}")
    else:
        print(f"✗ 新增失敗")


def _auto_get_github_token() -> Optional[str]:
    """
    Automatically get GitHub token using gh CLI.
    Returns None if failed.
    """
    try:
        # Import get_github_token function from scripts
        script_dir = Path(__file__).parent.parent.parent / "scripts"
        sys.path.insert(0, str(script_dir))
        
        try:
            from get_github_token import get_github_token
            # Call with silent=True to suppress error messages in CLI flow
            token = get_github_token(silent=True)
            return token
        finally:
            # Remove script_dir from path
            if str(script_dir) in sys.path:
                sys.path.remove(str(script_dir))
    
    except ImportError as e:
        print(f"⚠️  無法導入 get_github_token 模組")
        return None
    except Exception as e:
        print(f"⚠️  取得 token 時發生錯誤: {e}")
        return None


def _browser_github_login() -> Optional[str]:
    """
    Authenticate with GitHub using browser OAuth flow (Device Flow).
    Returns access token if successful, None otherwise.
    """
    try:
        from .github_oauth import authenticate_github
        
        # Use Device Flow (recommended for desktop applications)
        token = authenticate_github(use_device_flow=True)
        return token
        
    except ImportError:
        print("⚠️  無法導入 github_oauth 模組")
        print("    請確保 internal/services/github_oauth.py 存在")
        return None
    except Exception as e:
        print(f"⚠️  瀏覽器認證時發生錯誤: {e}")
        return None


def cmd_config_delete_provider():
    """Delete a provider"""
    print_header("刪除提供者")
    
    providers = list_providers()
    if not providers:
        print("\n  (尚無設定)")
        return
    
    print("\n可用的提供者:")
    for i, provider in enumerate(providers, 1):
        print(f"  {i}. {provider.provider_id} ({provider.name})")
    
    choice = input("\n選擇要刪除的提供者編號 (或輸入 ID): ").strip()
    
    # Try as number first
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(providers):
            provider_id = providers[idx].provider_id
        else:
            print("錯誤: 無效的編號")
            return
    except ValueError:
        provider_id = choice
    
    if delete_provider(provider_id):
        print(f"✓ 成功刪除提供者: {provider_id}")
    else:
        print(f"✗ 刪除失敗")


def cmd_config_list_agents():
    """List all agent configurations"""
    print_header("Agent 設定")
    configs = list_agent_configs()
    
    if not configs:
        print("\n  (尚無設定)")
        return
    
    for config in configs:
        print_agent_config(config)


def cmd_config_set_agent():
    """Configure a specific agent"""
    print_header("設定 Agent")
    
    # List available providers
    providers = list_providers()
    if not providers:
        print("\n錯誤: 請先新增至少一個提供者")
        return
    
    print("\n可用的提供者:")
    for i, provider in enumerate(providers, 1):
        print(f"  {i}. {provider.provider_id} ({provider.name})")
    
    # Get agent name
    agent_name = input("\nAgent 名稱 (例如: main, marketing, function-call): ").strip()
    if not agent_name:
        print("錯誤: Agent 名稱不可為空")
        return
    
    # Get provider
    choice = input("選擇提供者編號 (或輸入 ID): ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(providers):
            provider_id = providers[idx].provider_id
        else:
            print("錯誤: 無效的編號")
            return
    except ValueError:
        provider_id = choice
        if not get_provider(provider_id):
            print(f"錯誤: 提供者 '{provider_id}' 不存在")
            return
    
    # Get model name
    model_name = input("模型名稱 (例如: gpt-4, claude-3-5-sonnet-20241022): ").strip()
    if not model_name:
        print("錯誤: 模型名稱不可為空")
        return
    
    # Get temperature
    temp_str = input("Temperature (預設 0.2): ").strip()
    try:
        temperature = float(temp_str) if temp_str else 0.2
    except ValueError:
        print("錯誤: Temperature 必須是數字")
        return
    
    config = AgentModelConfig(
        agent_name=agent_name,
        provider_id=provider_id,
        model_name=model_name,
        temperature=temperature,
    )
    
    if set_agent_config(config):
        print(f"✓ 成功設定 Agent: {agent_name}")
    else:
        print(f"✗ 設定失敗")


def cmd_config_delete_agent():
    """Delete agent configuration"""
    print_header("刪除 Agent 設定")
    
    configs = list_agent_configs()
    if not configs:
        print("\n  (尚無設定)")
        return
    
    print("\n已設定的 Agents:")
    for i, config in enumerate(configs, 1):
        print(f"  {i}. {config.agent_name} ({config.model_name})")
    
    choice = input("\n選擇要刪除的 Agent 編號 (或輸入名稱): ").strip()
    
    # Try as number first
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(configs):
            agent_name = configs[idx].agent_name
        else:
            print("錯誤: 無效的編號")
            return
    except ValueError:
        agent_name = choice
    
    if delete_agent_config(agent_name):
        print(f"✓ 成功刪除 Agent 設定: {agent_name}")
    else:
        print(f"✗ 刪除失敗")


def cmd_config_menu():
    """Display configuration menu"""
    while True:
        print_header("Agent 設定管理")
        print("""
  1. 列出所有提供者
  2. 新增 OpenAI 相容 API 提供者
  3. 新增 GitHub Copilot 提供者
  4. 刪除提供者
  5. 列出所有 Agent 設定
  6. 設定 Agent
  7. 刪除 Agent 設定
  0. 返回
        """)
        
        choice = input("選擇操作: ").strip()
        
        if choice == "1":
            cmd_config_list_providers()
        elif choice == "2":
            cmd_config_add_openai_provider()
        elif choice == "3":
            cmd_config_add_github_copilot_provider()
        elif choice == "4":
            cmd_config_delete_provider()
        elif choice == "5":
            cmd_config_list_agents()
        elif choice == "6":
            cmd_config_set_agent()
        elif choice == "7":
            cmd_config_delete_agent()
        elif choice == "0":
            break
        else:
            print("無效的選擇")
        
        input("\n按 Enter 繼續...")


if __name__ == "__main__":
    cmd_config_menu()
