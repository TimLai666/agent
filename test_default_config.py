"""測試默認配置功能"""
from internal.services.config_db import (
    get_agent_config, 
    set_agent_config, 
    delete_agent_config,
    AgentModelConfig,
    add_provider,
    ProviderConfig
)
from internal.services.agent_discovery import discover_agents

def test_default_config():
    print("=" * 60)
    print("測試默認配置功能")
    print("=" * 60)
    
    # 1. 發現所有 agents
    print("\n1. 發現 agents:")
    agents = discover_agents()
    print(f"   總共發現 {len(agents)} 個 agents")
    
    # 2. 添加一個測試提供者
    print("\n2. 添加測試提供者:")
    provider = ProviderConfig(
        provider_id="test-provider",
        provider_type="openai-compatible",
        name="測試提供者",
        base_url="http://localhost:8080",
        api_key="test-key"
    )
    add_provider(provider)
    print("   ✅ 測試提供者添加成功")
    
    # 3. 設置默認配置
    print("\n3. 設置默認配置:")
    default_config = AgentModelConfig(
        agent_name="default",
        provider_id="test-provider",
        model_name="test-model",
        temperature=0.7,
        inherit_from=None
    )
    set_agent_config(default_config)
    print("   ✅ 默認配置設置成功")
    
    # 4. 測試獲取默認配置
    print("\n4. 獲取默認配置:")
    config = get_agent_config("default", use_default=False)
    if config:
        print(f"   ✅ Provider: {config.provider_id}")
        print(f"   ✅ Model: {config.model_name}")
        print(f"   ✅ Temperature: {config.temperature}")
    else:
        print("   ❌ 無法獲取默認配置")
    
    # 5. 測試未配置的 agent 使用默認配置
    print("\n5. 測試未配置的 agent:")
    test_agent = "marketing-email-writer"  # 假設這個 agent 還沒有配置
    
    print(f"   獲取 {test_agent} 的配置 (不使用默認):")
    config = get_agent_config(test_agent, use_default=False)
    print(f"   結果: {config}")
    
    print(f"   獲取 {test_agent} 的配置 (使用默認):")
    config = get_agent_config(test_agent, use_default=True)
    if config:
        print(f"   ✅ Provider: {config.provider_id}")
        print(f"   ✅ Model: {config.model_name}")
        print(f"   ✅ Temperature: {config.temperature}")
    else:
        print("   ❌ 無法獲取配置")
    
    # 6. 清理測試數據
    print("\n6. 清理測試數據:")
    delete_agent_config("default")
    print("   ✅ 默認配置已刪除")
    
    print("\n" + "=" * 60)
    print("測試完成！")
    print("=" * 60)

if __name__ == "__main__":
    test_default_config()
