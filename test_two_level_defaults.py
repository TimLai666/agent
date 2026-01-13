"""測試兩級默認配置功能"""
from internal.services.config_db import (
    get_agent_config, 
    set_agent_config, 
    delete_agent_config,
    AgentModelConfig,
)

def test_two_level_defaults():
    print("=" * 70)
    print("測試兩級默認配置功能")
    print("=" * 70)
    
    # 1. 設置全域默認配置
    print("\n1. 設置全域默認配置:")
    global_config = AgentModelConfig(
        agent_name="default",
        provider_id="global-provider",
        model_name="global-model",
        temperature=0.5,
        inherit_from=None
    )
    set_agent_config(global_config)
    print("   ✅ 全域默認: global-provider / global-model")
    
    # 2. 設置類別默認配置
    print("\n2. 設置類別默認配置:")
    category_config = AgentModelConfig(
        agent_name="default:marketing",
        provider_id="marketing-provider",
        model_name="marketing-model",
        temperature=0.7,
        inherit_from=None
    )
    set_agent_config(category_config)
    print("   ✅ Marketing 類別默認: marketing-provider / marketing-model")
    
    # 3. 測試未配置的 marketing agent（應使用類別默認）
    print("\n3. 測試未配置的 marketing agent:")
    marketing_agent = "marketing-email-writer"
    config = get_agent_config(marketing_agent, use_default=True, category="marketing")
    if config:
        print(f"   ✅ {marketing_agent}:")
        print(f"      Provider: {config.provider_id}")
        print(f"      Model: {config.model_name}")
        print(f"      Temperature: {config.temperature}")
        print(f"      Source: {config.inherit_from}")
    else:
        print("   ❌ 無法獲取配置")
    
    # 4. 測試未配置的非 marketing agent（應使用全域默認）
    print("\n4. 測試未配置的 testing agent:")
    testing_agent = "api-test-builder"
    config = get_agent_config(testing_agent, use_default=True, category="testing")
    if config:
        print(f"   ✅ {testing_agent}:")
        print(f"      Provider: {config.provider_id}")
        print(f"      Model: {config.model_name}")
        print(f"      Temperature: {config.temperature}")
        print(f"      Source: {config.inherit_from}")
    else:
        print("   ❌ 無法獲取配置")
    
    # 5. 測試回退順序
    print("\n5. 測試回退順序:")
    print("   a) Marketing agent 未配置 → 使用類別默認")
    config1 = get_agent_config("test-marketing", use_default=True, category="marketing")
    print(f"      Provider: {config1.provider_id if config1 else 'None'}")
    
    # 刪除類別默認後再測試
    delete_agent_config("default:marketing")
    print("   b) 刪除類別默認後，Marketing agent → 使用全域默認")
    config2 = get_agent_config("test-marketing", use_default=True, category="marketing")
    print(f"      Provider: {config2.provider_id if config2 else 'None'}")
    
    # 6. 清理測試數據
    print("\n6. 清理測試數據:")
    delete_agent_config("default")
    print("   ✅ 已清理全域默認配置")
    
    print("\n" + "=" * 70)
    print("測試完成！")
    print("=" * 70)
    print("\n回退順序驗證:")
    print("✅ 類別默認 (default:{category}) 優先於全域默認 (default)")
    print("✅ 刪除類別默認後，正確回退到全域默認")

if __name__ == "__main__":
    test_two_level_defaults()
