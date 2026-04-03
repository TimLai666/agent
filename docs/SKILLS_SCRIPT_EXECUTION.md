# Skills 資源執行說明（現行）

## Bundled Resources 類型

每個 skill 可選擇提供：

1. `scripts/`
2. `references/`
3. `assets/`

載入時會建立資源索引，位置在 `SkillResources`。

## Agent 如何拿到路徑

當 agent 呼叫 `use_skill("skill-name")` 後，回傳內容會包含：

1. skill 指導內容
2. 若有資源，附上 `Bundled Resources` 區塊
3. 每個資源的檔名與路徑

因此 agent 在啟用 skill 後，可以知道 scripts/references/assets 的實際路徑。

## 執行建議流程

1. `use_skill(...)`
2. 先讀腳本或參考檔
3. 再依需求執行命令

## 注意事項

1. skill 本身不會直接執行腳本；執行仍需透過工具或終端命令。
2. 只有存在的資源會出現在 `Bundled Resources`。

3. 讀取並理解 scripts
4. 正確執行它們
5. 使用 reference 文件
6. 訪問 assets

Skills 不再只是「指導文檔」，而是真正的「可執行專業工具包」。
