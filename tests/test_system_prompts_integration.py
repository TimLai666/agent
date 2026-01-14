"""測試 system prompts 整合功能。"""

import sys
from pathlib import Path

# 添加專案根目錄到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from internal.prompts import (
    SYSTEM_PROMPT,
    get_system_prompt,
    get_system_prompt_processed,
    build_combined_system_prompt,
    list_available_system_prompts,
)


def test_original_system_prompt():
    """測試原本的 SYSTEM_PROMPT 是否正常載入。"""
    print("=" * 60)
    print("測試 1: 原本的 SYSTEM_PROMPT")
    print("=" * 60)

    assert SYSTEM_PROMPT, "SYSTEM_PROMPT 不應該為空"
    assert "SYSTEM — HARD CONSTRAINTS" in SYSTEM_PROMPT or "Language:" in SYSTEM_PROMPT

    print(f"✓ SYSTEM_PROMPT 長度: {len(SYSTEM_PROMPT)} 字元")
    print(f"✓ 前 100 字元: {SYSTEM_PROMPT[:100]}")
    print()


def test_get_system_prompt():
    """測試取得特定的 system prompt。"""
    print("=" * 60)
    print("測試 2: 取得特定的 system prompt")
    print("=" * 60)

    # 測試取得 explore prompt
    explore = get_system_prompt("agent_prompt_explore")
    assert explore, "應該能取得 explore prompt"
    print(f"✓ 成功取得 agent_prompt_explore ({len(explore)} 字元)")

    # 測試使用完整 key
    explore2 = get_system_prompt("system_prompts.agent_prompt_explore")
    assert explore == explore2, "兩種方式應該取得相同內容"
    print(f"✓ 完整 key 也能正常工作")

    # 測試不存在的 prompt
    missing = get_system_prompt("non_existent_prompt", default="DEFAULT")
    assert missing == "DEFAULT", "應該返回預設值"
    print(f"✓ 不存在的 prompt 正確返回預設值")
    print()


def test_variable_processing():
    """測試變量處理功能。"""
    print("=" * 60)
    print("測試 3: 變量處理")
    print("=" * 60)

    # 取得原始 prompt（包含變量）
    raw = get_system_prompt("tool_description_bash")

    # 取得處理後的 prompt
    processed = get_system_prompt_processed("tool_description_bash")

    assert raw != processed or "${" not in raw, "變量應該被處理"

    # 檢查是否有變量被替換
    if "${BASH_TOOL_NAME}" in raw:
        assert "Bash" in processed, "變量應該被替換為 'Bash'"
        print(f"✓ 變量 ${{BASH_TOOL_NAME}} 成功替換為 'Bash'")

    print(f"✓ 原始長度: {len(raw)} 字元")
    print(f"✓ 處理後長度: {len(processed)} 字元")
    print()


def test_combine_prompts():
    """測試組合多個 prompts。"""
    print("=" * 60)
    print("測試 4: 組合多個 prompts")
    print("=" * 60)

    # 組合基礎 prompt 和額外的 prompts
    combined = build_combined_system_prompt(
        additional_prompts=[
            "tool_description_bash",
            "agent_prompt_explore",
        ]
    )

    assert combined, "組合後的 prompt 不應該為空"
    assert len(combined) > len(SYSTEM_PROMPT), "組合後應該比基礎 prompt 長"

    # 檢查分隔符
    assert "---" in combined, "應該包含分隔符"

    print(f"✓ 成功組合 prompts")
    print(f"✓ 基礎 prompt 長度: {len(SYSTEM_PROMPT)} 字元")
    print(f"✓ 組合後長度: {len(combined)} 字元")
    print(f"✓ 增加了: {len(combined) - len(SYSTEM_PROMPT)} 字元")
    print()


def test_list_available():
    """測試列出可用的 prompts。"""
    print("=" * 60)
    print("測試 5: 列出可用的 prompts")
    print("=" * 60)

    available = list_available_system_prompts()

    assert isinstance(available, list), "應該返回列表"
    assert len(available) > 0, "應該至少有一些 prompts"

    print(f"✓ 找到 {len(available)} 個 system prompts")
    print(f"✓ 前 10 個:")
    for name in available[:10]:
        print(f"  - {name}")

    if len(available) > 10:
        print(f"  ... 還有 {len(available) - 10} 個")

    print()


def test_custom_variables():
    """測試自定義變量。"""
    print("=" * 60)
    print("測試 6: 自定義變量")
    print("=" * 60)

    # 創建一個包含變量的測試 prompt
    test_prompt_name = "tool_description_bash"

    # 使用自定義變量
    custom_vars = {
        "BASH_TOOL_NAME": "CustomBash",
        "READ_TOOL_NAME": "CustomRead",
    }

    processed = get_system_prompt_processed(test_prompt_name, variables=custom_vars)

    # 檢查自定義變量是否生效
    if "CustomBash" in processed:
        print(f"✓ 自定義變量 'CustomBash' 成功應用")
    else:
        print(f"⚠ 此 prompt 可能不包含 BASH_TOOL_NAME 變量")

    print(f"✓ 處理後長度: {len(processed)} 字元")
    print()


def run_all_tests():
    """執行所有測試。"""
    print("\n" + "=" * 60)
    print("System Prompts 整合測試")
    print("=" * 60 + "\n")

    try:
        test_original_system_prompt()
        test_get_system_prompt()
        test_variable_processing()
        test_combine_prompts()
        test_list_available()
        test_custom_variables()

        print("=" * 60)
        print("✓ 所有測試通過！")
        print("=" * 60)
        return True

    except AssertionError as e:
        print("\n" + "=" * 60)
        print(f"✗ 測試失敗: {e}")
        print("=" * 60)
        return False
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"✗ 發生錯誤: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
