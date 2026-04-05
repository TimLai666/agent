# 06 — Plugin 系統架構分析

## 概覽

Claude Code 擁有完整的 Plugin 系統，允許安裝第三方插件擴展功能。系統分為兩類：**Built-in Plugins**（內建插件）和**Marketplace Plugins**（從 GitHub 下載的插件）。

架構位置：`src/plugins/`

---

## 兩類插件

### Built-in Plugins

來源：`src/plugins/builtinPlugins.ts`

- 隨 CLI 出廠附帶
- 在 `/plugin` UI 中顯示為「Built-in」區段
- 使用者可啟用/停用（持久化到 user settings）
- Plugin ID 格式：`{name}@builtin`
- 可提供：skills、hooks、MCP servers

```typescript
interface BuiltinPluginDefinition {
  name: string
  description: string
  version: string
  defaultEnabled?: boolean
  isAvailable?: () => boolean  // 動態可用性檢查
  skills?: BundledSkillDefinition[]
  hooks?: HooksConfig
  mcpServers?: MCPServerConfig[]
}
```

**啟用邏輯**：用戶設定 > 插件預設值 > `true`（預設啟用）

### Marketplace Plugins

- 從 GitHub repository 下載安裝
- 分為內部市場（Ant 員工）和官方市場（外部用戶）

| 用戶類型 | 市場名稱 | Repository |
|---------|---------|-----------|
| ant（內部） | `claude-code-marketplace` | `anthropics/claude-code-marketplace` |
| external（外部） | 官方市場名稱 | `anthropics/claude-plugins-official` |

---

## Plugin ID 命名規則

- Built-in：`{name}@builtin`
- Marketplace：`{name}@{marketplaceName}`

例：
- `thinkback@builtin`（內建 thinkback）
- `thinkback@claude-code-marketplace`（從市場安裝的 thinkback）

---

## Thinkback 插件（特殊案例）

`thinkback` 是一個橫跨兩種機制的插件：

### 作為 Command（`/think-back`）
來源：`src/commands/thinkback/index.ts`

```typescript
const thinkback = {
  type: 'local-jsx',
  name: 'think-back',
  description: 'Your 2025 Claude Code Year in Review',
  isEnabled: () => checkStatsigFeatureGate_CACHED_MAY_BE_STALE('tengu_thinkback'),
  load: () => import('./thinkback.js'),
}
```

### 作為 Marketplace Plugin
- 從市場安裝後，提供 skill 目錄和動畫播放器
- `year_in_review.js` + `player.js` 為核心資料與播放器

### Thinkback-play Command
`/thinkback-play` 直接播放已安裝的 thinkback 動畫（無需重新生成）

---

## Plugin 技術組成

每個插件可包含：

| 元件 | 說明 |
|------|------|
| `skills` | 提供的 slash commands（`/command-name`） |
| `hooks` | 生命週期 hooks（pre/post tool 使用等） |
| `mcpServers` | 提供的 MCP server 配置 |

---

## Skills 如何整合

來源：`src/plugins/builtinPlugins.ts`（`skillDefinitionToCommand`）

Built-in plugin 的 skill 會被轉換為 `Command` 對象，其中：
- `source: 'bundled'`（非 `'builtin'`）：讓 skills 出現在 Skill tool 列表中、正確記錄 analytics 名稱、豁免 prompt 截斷
- `isHidden: !(userInvocable ?? true)`：可設定是否對使用者可見

---

## 插件可用性檢查

```typescript
if (definition.isAvailable && !definition.isAvailable()) {
  continue  // 跳過不可用的插件
}
```

例如：語音模式插件在非 claude.ai OAuth 環境下 `isAvailable()` 返回 `false`。

---

## Plugin 操作 Analytics

| 事件 | 說明 |
|------|------|
| `tengu_plugin_list_command` | 列出插件 |
| `tengu_plugin_install_command` | 安裝插件 |
| `tengu_plugin_uninstall_command` | 卸載插件 |
| `tengu_plugin_enable_command` | 啟用插件 |
| `tengu_plugin_disable_command` | 停用插件 |
| `tengu_plugin_update_command` | 更新插件 |
| `tengu_marketplace_added` | 添加市場 |
| `tengu_marketplace_removed` | 移除市場 |

---

## bundled/ 目錄

`src/plugins/bundled/` — 隨 CLI 打包的 bundled skills（非市場插件）。這些是出廠就附帶的技能，不需要從市場安裝。

---

## 設計分析

1. **雙軌制**：Built-in（內建）vs Marketplace（市場）分離，內建插件無需網路
2. **ID 命名空間**：`@builtin` 後綴明確區分來源，防止市場插件偽裝成內建插件
3. **Skills 的 source 設定**：刻意使用 `'bundled'` 而非 `'builtin'`，確保在 Skill tool 列表中正確顯示
4. **可用性與啟用分離**：`isAvailable()`（環境不滿足就完全隱藏）vs 用戶啟用設定（在 UI 中可切換）
