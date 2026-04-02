"""
測試 GitHub OAuth 瀏覽器登入功能
"""

import sys
from pathlib import Path

# 將專案根目錄加入路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_oauth_module_import():
    """測試 OAuth 模組導入"""
    print("測試 1: OAuth 模組導入")
    try:
        from internal.services.github_oauth import authenticate_github, GitHubDeviceFlow
        print("  ✓ 模組導入成功")
        return True
    except ImportError as e:
        print(f"  ✗ 模組導入失敗: {e}")
        return False

def test_device_flow_class():
    """測試 Device Flow 類別"""
    print("\n測試 2: Device Flow 類別")
    try:
        from internal.services.github_oauth import GitHubDeviceFlow
        flow = GitHubDeviceFlow()
        print(f"  ✓ Device Flow 實例化成功")
        print(f"  ✓ Client ID: {flow.CLIENT_ID}")
        return True
    except Exception as e:
        print(f"  ✗ Device Flow 實例化失敗: {e}")
        return False

def test_cli_integration():
    """測試 CLI 整合"""
    print("\n測試 3: CLI 整合")
    try:
        from internal.services.config_cli import _browser_github_login
        print("  ✓ _browser_github_login 函數存在")
        return True
    except ImportError as e:
        print(f"  ✗ CLI 整合失敗: {e}")
        return False

def test_oauth_function_signature():
    """測試 OAuth 函數簽名"""
    print("\n測試 4: OAuth 函數簽名")
    try:
        from internal.services.github_oauth import authenticate_github
        import inspect
        
        sig = inspect.signature(authenticate_github)
        params = list(sig.parameters.keys())
        
        print(f"  ✓ 函數簽名: authenticate_github({', '.join(params)})")
        
        if 'use_device_flow' in params:
            print("  ✓ use_device_flow 參數存在")
            return True
        else:
            print("  ✗ use_device_flow 參數不存在")
            return False
    except Exception as e:
        print(f"  ✗ 函數簽名檢查失敗: {e}")
        return False

def interactive_test():
    """互動式測試（需要使用者確認）"""
    print("\n" + "="*60)
    print("互動式測試（可選）")
    print("="*60)
    
    response = input("\n要進行真實的瀏覽器登入測試嗎？(y/N): ").strip().lower()
    
    if response == 'y':
        print("\n開始真實測試...")
        try:
            from internal.services.github_oauth import authenticate_github
            
            print("\n這會打開瀏覽器進行 GitHub 認證。")
            print("請在瀏覽器中完成授權流程。\n")
            
            token = authenticate_github(use_device_flow=True)
            
            if token:
                print(f"\n✓ 認證成功！")
                print(f"  Token (前 20 字元): {token[:20]}...")
                print(f"  Token 長度: {len(token)}")
                return True
            else:
                print("\n✗ 認證失敗")
                return False
                
        except Exception as e:
            print(f"\n✗ 測試過程發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        print("  跳過互動式測試")
        return None

def main():
    """主測試函數"""
    print("="*60)
    print("GitHub OAuth 瀏覽器登入功能測試")
    print("="*60)
    
    results = []
    
    # 執行所有自動測試
    results.append(("OAuth 模組導入", test_oauth_module_import()))
    results.append(("Device Flow 類別", test_device_flow_class()))
    results.append(("CLI 整合", test_cli_integration()))
    results.append(("OAuth 函數簽名", test_oauth_function_signature()))
    
    # 顯示結果
    print("\n" + "="*60)
    print("測試結果摘要")
    print("="*60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} - {name}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"\n通過: {passed}/{total}")
    
    # 互動式測試
    interactive_result = interactive_test()
    
    if interactive_result is not None:
        if interactive_result:
            print("\n✓ 互動式測試通過")
        else:
            print("\n✗ 互動式測試失敗")
    
    print("\n" + "="*60)
    print("測試完成")
    print("="*60)
    
    # 返回是否所有測試都通過
    return all(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
