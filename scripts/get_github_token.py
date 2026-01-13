#!/usr/bin/env python3
"""
Helper script to get GitHub token for Copilot authentication.
"""
import subprocess
import sys


def get_github_token(silent: bool = False):
    """
    Get GitHub token using gh CLI
    
    Args:
        silent: If True, suppress error messages (useful when called as module)
    
    Returns:
        Token string or None if failed
    """
    def print_if_not_silent(msg):
        if not silent:
            print(msg)
    
    try:
        # Check if gh CLI is installed
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print_if_not_silent("❌ GitHub CLI (gh) 未安裝")
            print_if_not_silent("\n請先安裝 GitHub CLI:")
            print_if_not_silent("  Windows: winget install GitHub.cli")
            print_if_not_silent("           (安裝後需重新啟動 PowerShell)")
            print_if_not_silent("  macOS:   brew install gh")
            print_if_not_silent("  Linux:   https://github.com/cli/cli#installation")
            return None
        
        # Get token
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print_if_not_silent("❌ 無法取得 GitHub token")
            print_if_not_silent("\n請先登入 GitHub CLI:")
            print_if_not_silent("  gh auth login")
            return None
        
        token = result.stdout.strip()
        if not token:
            print_if_not_silent("❌ Token 為空")
            return None
        
        return token
    
    except FileNotFoundError:
        print_if_not_silent("❌ 找不到 gh 命令")
        print_if_not_silent("\n請先安裝 GitHub CLI:")
        print_if_not_silent("  https://github.com/cli/cli#installation")
        print_if_not_silent("\n⚠️  Windows 用戶: 安裝後需重新啟動 PowerShell")
        return None
    except Exception as e:
        print_if_not_silent(f"❌ 錯誤: {e}")
        return None


def main():
    print("=" * 60)
    print("  GitHub Copilot Token 取得工具")
    print("=" * 60)
    
    token = get_github_token()
    
    if token:
        print(f"\n✓ 成功取得 GitHub Token:")
        print(f"\n{token}\n")
        print("請將此 token 複製並在配置介面中使用。")
        print("\n使用方式:")
        print("  1. 執行: python main.py --config")
        print("  2. 選擇「新增 GitHub Copilot 提供者」")
        print("  3. 貼上上面的 token")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
