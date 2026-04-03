"""測試自動載入所有 system prompts 功能。"""

import sys
from pathlib import Path

# 添加專案根目錄到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from internal.prompts import (
    SYSTEM_PROMPT,
    list_available_system_prompts,
    build_combined_system_prompt,
)


def test_auto_load_all_prompts():
    """測試自動載入所有 system prompts。"""
    print("=" * 60)
    print("測試：自動載入所有 system prompts")
    print("=" * 60)

    # 1. 取得所有可用的 prompts
    all_prompts = list_available_system_prompts()
    print(f"\n✓ 找到 {len(all_prompts)} 個 system prompts")

    # 2. 組合所有 prompts
    combined = build_combined_system_prompt(
        base_prompt=SYSTEM_PROMPT,
        additional_prompts=all_prompts,
        separator="\n\n---\n\n",
    )

    # 3. 檢查結果
    base_length = len(SYSTEM_PROMPT)
    combined_length = len(combined)
    added_length = combined_length - base_length

    print(f"\n基礎 SYSTEM_PROMPT 長度: {base_length:,} 字元")
    print(f"組合後總長度: {combined_length:,} 字元")
    print(f"增加了: {added_length:,} 字元")
    print(f"增加比例: {(added_length / base_length * 100):.1f}%")

    # 4. 檢查是否包含分隔符
    separator_count = combined.count("---")
    print(f"\n✓ 包含 {separator_count} 個分隔符")

    # 5. 顯示前 10 個載入的 prompts
    print(f"\n前 10 個載入的 prompts:")
    for i, name in enumerate(all_prompts[:10], 1):
        print(f"  {i}. {name}")

    if len(all_prompts) > 10:
        print(f"  ... 還有 {len(all_prompts) - 10} 個")

    # 6. 檢查某些關鍵的 prompts 是否被載入
    key_prompts = [
        "tool-description-bash",
        "agent-prompt-explore",
        "system-prompt-command-usage-practice",
    ]

    print(f"\n檢查關鍵 prompts 是否載入:")
    for prompt in key_prompts:
        if prompt in all_prompts:
            print(f"  ✓ {prompt}")
        else:
            print(f"  ✗ {prompt} (未找到)")

    print("\n" + "=" * 60)
    print("✓ 測試完成")
    print("=" * 60)

    return True


def show_prompt_sample():
    """顯示組合後的 prompt 樣本。"""
    print("\n" + "=" * 60)
    print("組合後的 System Prompt 樣本")
    print("=" * 60)

    all_prompts = list_available_system_prompts()
    combined = build_combined_system_prompt(
        base_prompt=SYSTEM_PROMPT,
        additional_prompts=all_prompts[:5],  # 只取前 5 個做範例
        separator="\n\n---\n\n",
    )

    # 顯示前 1000 字元
    print("\n前 1000 字元：")
    print("-" * 60)
    print(combined[:1000])
    print("...")
    print("-" * 60)

    # 顯示最後 500 字元
    print("\n最後 500 字元：")
    print("-" * 60)
    print("...")
    print(combined[-500:])
    print("-" * 60)


if __name__ == "__main__":
    try:
        test_auto_load_all_prompts()

        # 詢問是否顯示樣本
        response = input("\n是否顯示組合後的 prompt 樣本？(y/N): ")
        if response.lower() == "y":
            show_prompt_sample()

        sys.exit(0)
    except Exception as e:
        print(f"\n✗ 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
