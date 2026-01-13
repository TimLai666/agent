# Skills Script Execution 優化

## 🎯 問題

Agent 能激活 skills 並看到指導內容，但不知道如何執行 skill 中的 scripts。

**具體表現：**
- ✅ Agent 會調用 `use_skill` tool
- ✅ Agent 會閱讀 skill 內容
- ❌ Agent 不知道有哪些 scripts 可用
- ❌ Agent 不知道 scripts 的路徑
- ❌ Agent 不會執行這些 scripts

## 🔍 根本原因

1. **System prompt 缺少明確指示** - 沒有告訴 agent 如何執行 skill 中的 scripts
2. **use_skill 返回內容不完整** - 只返回 SKILL.md 內容，沒有列出可用資源（scripts/references/assets）
3. **缺少執行工作流程** - Agent 不知道標準流程是什麼

## ✅ 解決方案

### 1. 更新 SYSTEM_PROMPT.md

**檔案：** `prompts/SYSTEM_PROMPT.md`

**新增章節：** `## SKILLS EXECUTION`

```markdown
## SKILLS EXECUTION

When you activate a skill using the `use_skill` tool, you MUST follow its instructions completely:

### Executing Scripts
If a skill provides scripts (in `scripts/` directory):
1. **READ the script first** - Use Read tool to examine the script
2. **UNDERSTAND parameters** - Check what arguments the script needs
3. **EXECUTE using Bash** - Run the script with correct arguments
4. **USE ABSOLUTE PATHS** - Always use the full path provided by the skill

Example workflow:
```text
1. use_skill("pdf") → Returns skill with script paths
2. Read(script_path) → Understand what it does
3. Bash("python {script_path} input.pdf output.pdf") → Execute it
```

### Reading References
If a skill mentions reference files (e.g., "Read docx-js.md"):
1. **Use the provided path** - Skill tells you the exact location
2. **Read ENTIRE file** - When skill says "READ ENTIRE FILE", do NOT use offset/limit
3. **Follow the instructions** - Reference files contain critical methodology

### Using Assets
If a skill provides assets (templates, images, etc.):
- Use the asset paths provided by the skill
- Copy/modify assets as instructed

**CRITICAL**: Skills are NOT just guidance - they contain executable code and resources you MUST use.
```

**關鍵點：**
- ✅ 明確的執行流程（Read → Understand → Execute）
- ✅ 強調使用絕對路徑
- ✅ 具體例子展示如何使用
- ✅ 強調 skills 包含可執行代碼

### 2. 修改 use_skill 返回內容

**檔案：** `internal/tools/skill_tools.py`

**改動：** 在返回內容中添加 "Bundled Resources" 章節

```python
# Build resources section if available
resources_section = ""
if skill.resources.has_resources():
    resources_info = []

    # Add scripts
    if skill.resources.scripts:
        resources_info.append("\n### Available Scripts")
        resources_info.append("\nThese scripts are ready to execute...")
        for script_name, script_path in skill.resources.scripts.items():
            resources_info.append(f"- `{script_name}`: `{script_path}`")

    # Add references
    if skill.resources.references:
        resources_info.append("\n### Reference Files")
        resources_info.append("\nThese files contain detailed documentation...")
        for ref_name, ref_path in skill.resources.references.items():
            resources_info.append(f"- `{ref_name}`: `{ref_path}`")

    # Add assets
    if skill.resources.assets:
        resources_info.append("\n### Available Assets")
        for asset_name, asset_path in skill.resources.assets.items():
            resources_info.append(f"- `{asset_name}`: `{asset_path}`")

    resources_section = "\n\n## Bundled Resources\n" + "\n".join(resources_info)
```

**返回格式：**

```markdown
# Active Skill: pdf

**IMPORTANT**: This skill provides expert guidance AND executable resources.
Follow the instructions below and USE the provided scripts/references.

---

[SKILL.md content here]

## Bundled Resources

### Available Scripts

These scripts are ready to execute. Use Read tool to examine them first, then run with Bash:

- `check_bounding_boxes.py`: `C:\Users\...\skills\pdf\scripts\check_bounding_boxes.py`
- `fill_pdf_form.py`: `C:\Users\...\skills\pdf\scripts\fill_pdf_form.py`
- [... more scripts ...]

### Reference Files

These files contain detailed documentation. Use Read tool to access them:

- `reference.md`: `C:\Users\...\skills\pdf\reference.md`

---

**Remember**:
1. Follow the skill's methodology exactly
2. Use Read tool to examine scripts before executing
3. Execute scripts using Bash with the absolute paths provided above
4. Read reference files completely when instructed (no offset/limit)
```

## 📊 效果

### 之前 ❌

```
用戶：幫我填寫這個 PDF 表單

Agent：
1. 調用 use_skill("pdf")
2. 看到 SKILL.md 內容
3. 理解需要填寫表單
4. ❌ 不知道有 fill_pdf_form.py script
5. ❌ 嘗試用通用方法處理（可能失敗）
```

### 之後 ✅

```
用戶：幫我填寫這個 PDF 表單

Agent：
1. 調用 use_skill("pdf")
2. 看到 SKILL.md 內容
3. ✅ 看到 "Available Scripts" 章節
4. ✅ 看到 fill_pdf_form.py 的完整路徑
5. ✅ Read(script_path) 檢查參數
6. ✅ Bash("python C:\...\fill_pdf_form.py input.pdf output.pdf")
7. ✅ 成功執行！
```

## 🎯 覆蓋的 Skills

這個優化對所有包含資源的 skills 都有效：

**包含 Scripts 的 Skills：**
- `pdf` - 8 個 Python scripts（表單填寫、提取、轉換等）
- `docx` - 文檔處理 scripts
- `pptx` - 簡報處理 scripts
- `skill-creator` - Skill 創建工具
- `mcp-builder` - MCP 服務器構建工具
- `web-artifacts-builder` - Web artifact 構建工具
- `webapp-testing` - Web 應用測試工具

**包含 References 的 Skills：**
- 所有有 `references/` 目錄的 skills
- 包含詳細文檔、API 參考等

**包含 Assets 的 Skills：**
- 模板文件
- 圖片資源
- 配置文件

## 🚀 測試驗證

```python
# 測試 pdf skill 資源顯示
from internal.skills_loader import load_skill_registry

skills = load_skill_registry()
pdf_skill = skills.get_skill('pdf')

print(f"Scripts: {len(pdf_skill.resources.scripts)}")
# Output: Scripts: 8

print("Available scripts:")
for name, path in pdf_skill.resources.scripts.items():
    print(f"  - {name}: {path}")
# Output:
#   - check_bounding_boxes.py: C:\Users\...\check_bounding_boxes.py
#   - fill_pdf_form.py: C:\Users\...\fill_pdf_form.py
#   - ...
```

## 📝 技術細節

### SkillResources 結構

```python
@dataclass
class SkillResources:
    scripts: dict[str, Path] = field(default_factory=dict)
    references: dict[str, Path] = field(default_factory=dict)
    assets: dict[str, Path] = field(default_factory=dict)

    def has_resources(self) -> bool:
        return bool(self.scripts or self.references or self.assets)
```

### 資源加載

Skills 在加載時會自動掃描：
- `skills/{skill_name}/scripts/` → `skill.resources.scripts`
- `skills/{skill_name}/references/` → `skill.resources.references`
- `skills/{skill_name}/assets/` → `skill.resources.assets`

所有路徑都是**絕對路徑**，可以直接在 Bash 命令中使用。

### Progressive Disclosure

Skills 系統使用 progressive disclosure：
1. **啟動時** - 只載入 metadata（name + description）
2. **use_skill 調用時** - 載入 SKILL.md 內容
3. **執行時** - Agent 根據需要讀取 scripts/references

這樣可以：
- ✅ 快速啟動（不需要載入所有 skill 內容）
- ✅ 按需載入（只載入使用的 skills）
- ✅ 完整訪問（所有資源都可用）

## 🎉 總結

完成了完整的 skills execution 支持：

✅ **System Prompt** - 明確告訴 agent 如何執行 scripts
✅ **use_skill Tool** - 返回完整的資源列表（scripts/references/assets）
✅ **絕對路徑** - Agent 可以直接使用，無需猜測位置
✅ **清晰流程** - Read → Understand → Execute
✅ **覆蓋所有類型** - Scripts, References, Assets

現在 agent 可以：
1. 激活 skills
2. 看到可用資源
3. 讀取並理解 scripts
4. 正確執行它們
5. 使用 reference 文件
6. 訪問 assets

Skills 不再只是「指導文檔」，而是真正的「可執行專業工具包」。
