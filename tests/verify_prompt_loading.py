"""驗證只載入 SYSTEM_PROMPT.md 和 system-prompts/ 資料夾。"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from internal.prompts import (
    SYSTEM_PROMPT,
    list_available_system_prompts,
    build_combined_system_prompt,
    _PROMPTS,
)


def verify_prompt_sources():
    """驗證 prompt 來源。"""
    print("=" * 70)
    print("驗證 System Prompt 載入來源")
    print("=" * 70)

    # 1. 檢查所有載入的 prompts
    all_keys = list(_PROMPTS.keys())
    print(f"\n總共載入了 {len(all_keys)} 個 prompt 檔案")

    # 2. 分類檢查
    root_prompts = [k for k in all_keys if not k.startswith("system_prompts.")]
    system_prompts = [k for k in all_keys if k.startswith("system_prompts.")]

    print(f"\n根目錄 prompts（{len(root_prompts)} 個）：")
    for key in root_prompts:
        print(f"  - {key}")

    print(f"\nsystem-prompts/ 子目錄（{len(system_prompts)} 個）：")
    for key in system_prompts[:5]:
        print(f"  - {key}")
    if len(system_prompts) > 5:
        print(f"  ... 還有 {len(system_prompts) - 5} 個")

    # 3. 驗證 list_available_system_prompts() 只返回 system-prompts/
    available = list_available_system_prompts()
    print(f"\n[OK] list_available_system_prompts() 返回 {len(available)} 個 prompts")
    print("前 5 個：")
    for name in available[:5]:
        print(f"  - {name}")

    # 4. 驗證不包含根目錄的其他檔案
    root_files_to_exclude = ["MAIN_AGENT_PROMPT", "SKILLS_PRIORITY"]
    print(f"\n檢查是否排除了根目錄的其他檔案：")
    for file in root_files_to_exclude:
        # 移除 .md 後綴，轉大寫
        if file not in available:
            print(f"  [OK] {file} 未被包含（正確）")
        else:
            print(f"  [ERROR] {file} 被包含了（錯誤！）")

    # 5. 驗證組合後的 system prompt
    print(f"\n檢查組合後的 system prompt：")
    combined = build_combined_system_prompt(
        base_prompt=SYSTEM_PROMPT,
        additional_prompts=available,
    )

    print(f"  - 基礎 SYSTEM_PROMPT: {len(SYSTEM_PROMPT):,} 字元")
    print(f"  - 組合後總長度: {len(combined):,} 字元")
    print(f"  - 包含 {len(available)} 個額外 prompts")

    # 6. 確認基礎 prompt 來源
    print(f"\n基礎 SYSTEM_PROMPT 來自：")
    if "SYSTEM_PROMPT" in _PROMPTS:
        print(f"  [OK] prompts/SYSTEM_PROMPT.md")
    else:
        print(f"  [ERROR] 找不到 SYSTEM_PROMPT")

    print("\n" + "=" * 70)
    print("[OK] 驗證完成")
    print("=" * 70)

    return True


def show_loading_flow():
    """顯示載入流程。"""
    print("\n" + "=" * 70)
    print("System Prompt 載入流程")
    print("=" * 70)

    print("""
1. 基礎 Prompt
   來源：prompts/SYSTEM_PROMPT.md
   內容：系統約束、語言設定、安全政策等

2. 額外 Prompts（自動載入）
   來源：prompts/system-prompts/*.md
   內容：工具描述、agent 指導、範例等
   數量：66+ 個檔案

3. 不包括
   [X] prompts/MAIN_AGENT_PROMPT.md（這個在 instructions 中）
   [X] prompts/SKILLS_PRIORITY.md（這個在 instructions 中）

4. 組合方式
   SYSTEM_PROMPT.md
   ---
   system-prompts/agent-prompt-xxx.md
   ---
   system-prompts/tool-description-xxx.md
   ---
   ...
    """)

    print("=" * 70)


if __name__ == "__main__":
    try:
        verify_prompt_sources()
        show_loading_flow()
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] 驗證失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
