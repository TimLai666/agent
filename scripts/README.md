# Scripts 目錄

本目錄包含實用的腳本工具。

## 📝 腳本列表

### 🔑 GitHub 認證

#### `get_github_token.py`
從 GitHub CLI 獲取 access token。

**用途**：
- 測試 gh CLI 是否正常工作
- 手動獲取 token 用於其他用途

**使用方式**：
```bash
# 前提：已安裝並登入 gh CLI
python scripts/get_github_token.py
```

**輸出**：
```
GitHub Token: ghp_xxxxxxxxxxxxxxxxxxxx
```

**在代碼中使用**：
```python
from get_github_token import get_github_token

token = get_github_token(silent=True)  # silent=True 靜默模式
```

---

### 🔄 配置遷移

#### `migrate_from_env.py`
輔助腳本：從環境變數遷移到資料庫配置。

**用途**：
- 快速批量導入配置
- 自動化遷移過程

**使用方式**：
1. 編輯腳本，填入你的配置
2. 執行腳本

```bash
python scripts/migrate_from_env.py
```

**範例**：
```python
# 新增 OpenAI 提供者
add_provider(ProviderConfig(
    provider_id="openai",
    provider_type="openai-compatible",
    name="OpenAI",
    api_key="sk-..."
))

# 設定 main agent
set_agent_config(AgentModelConfig(
    agent_name="main",
    provider_id="openai",
    model_name="gpt-4",
    temperature=0.2
))
```

---

### 🧪 測試腳本

#### `test_config.py`
測試配置系統的完整性。

**用途**：
- 驗證資料庫操作
- 測試 CRUD 功能

**使用方式**：
```bash
python scripts/test_config.py
```

#### `test_github_oauth.py`
測試 GitHub OAuth 瀏覽器登入功能。

**用途**：
- 驗證 OAuth 模組是否正常
- 測試瀏覽器認證流程

**使用方式**：
```bash
python scripts/test_github_oauth.py

# 互動式測試（會打開瀏覽器）
python scripts/test_github_oauth.py
# 選擇 y 進行真實認證測試
```

---

## 📋 腳本使用指南

### 開發新腳本

新增腳本時請遵循以下規範：

1. **Shebang**：使用 `#!/usr/bin/env python3`
2. **Docstring**：在檔案開頭添加說明
3. **路徑處理**：使用 `pathlib.Path`
4. **專案根目錄**：
   ```python
   project_root = Path(__file__).parent.parent
   sys.path.insert(0, str(project_root))
   ```
5. **錯誤處理**：捕獲並顯示友善的錯誤訊息

### 測試腳本命名

- 測試腳本：`test_*.py`
- 工具腳本：`<功能名>.py`
- 遷移腳本：`migrate_*.py`

### 腳本分類

| 類型 | 命名 | 範例 |
|------|------|------|
| 工具 | `<tool_name>.py` | `get_github_token.py` |
| 測試 | `test_<feature>.py` | `test_config.py` |
| 遷移 | `migrate_<source>_to_<target>.py` | `migrate_from_env.py` |

---

## 🔗 相關資源

- [配置指南](../docs/CONFIG_GUIDE.md)
- [GitHub 瀏覽器登入](../docs/GITHUB_BROWSER_LOGIN.md)
- [遷移指南](../docs/MIGRATION_GUIDE.md)
