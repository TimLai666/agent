"""示範如何使用新的 system prompts 載入機制。"""

from internal.prompts import (
    SYSTEM_PROMPT,  # 原本的 SYSTEM_PROMPT.md
    get_system_prompt,  # 取得特定的 system prompt
    get_system_prompt_processed,  # 取得並處理變量的 system prompt
    build_combined_system_prompt,  # 組合多個 system prompts
    list_available_system_prompts,  # 列出所有可用的 system prompts
)


def example_1_use_original_system_prompt():
    """範例 1：使用原本的 SYSTEM_PROMPT（不變）。"""
    print("=== 範例 1: 使用原本的 SYSTEM_PROMPT ===")
    print(SYSTEM_PROMPT[:200])  # 顯示前 200 字元
    print("...")
    print()


def example_2_get_specific_system_prompt():
    """範例 2：取得特定的 system prompt。"""
    print("=== 範例 2: 取得特定的 system prompt ===")

    # 取得 explore agent 的 prompt
    explore_prompt = get_system_prompt("agent_prompt_explore")
    print(f"Explore prompt 長度: {len(explore_prompt)} 字元")
    print(f"前 200 字元: {explore_prompt[:200]}")
    print("...")
    print()


def example_3_process_variables():
    """範例 3：處理變量替換。"""
    print("=== 範例 3: 處理變量替換 ===")

    # 取得並處理變量
    bash_tool_desc = get_system_prompt_processed("tool_description_bash")
    print(f"Bash tool description 長度: {len(bash_tool_desc)} 字元")
    print(f"前 300 字元: {bash_tool_desc[:300]}")
    print("...")
    print()


def example_4_combine_prompts():
    """範例 4：組合多個 system prompts。"""
    print("=== 範例 4: 組合多個 system prompts ===")

    # 組合基礎 prompt 和額外的 tool descriptions
    combined = build_combined_system_prompt(
        additional_prompts=[
            "tool_description_bash",
            "tool_description_grep",
        ]
    )
    print(f"組合後的 prompt 長度: {len(combined)} 字元")
    print()


def example_5_list_available():
    """範例 5：列出所有可用的 system prompts。"""
    print("=== 範例 5: 列出所有可用的 system prompts ===")

    available = list_available_system_prompts()
    print(f"總共有 {len(available)} 個 system prompts")
    print("前 10 個:")
    for name in available[:10]:
        print(f"  - {name}")
    print("...")
    print()


def example_6_custom_variables():
    """範例 6：使用自定義變量。"""
    print("=== 範例 6: 使用自定義變量 ===")

    # 使用自定義變量替換
    custom_vars = {
        "PROJECT_NAME": "我的專案",
        "VERSION": "2.0.0",
    }

    prompt = get_system_prompt_processed(
        "tool_description_bash",
        variables=custom_vars
    )
    print(f"使用自定義變量後的長度: {len(prompt)} 字元")
    print()


if __name__ == "__main__":
    example_1_use_original_system_prompt()
    example_2_get_specific_system_prompt()
    example_3_process_variables()
    example_4_combine_prompts()
    example_5_list_available()
    example_6_custom_variables()
