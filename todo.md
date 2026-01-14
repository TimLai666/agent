1. 只在使用者更改mcp設定時，才更新mcp server列表(資料庫部分)，減少不必要的重新加載。
2. 圖片顯示寬度不能超出去 我不要橫向捲動
3. agent預設設定覆蓋層級是否正確 subagent預設真的>全域預設?
4. system prompt更新
    - 把Claude替換成變數 在prompts.py設置agent名稱
    - 教agent使用package-docs mcp
        fetch-url-docs: 🔗 Fetch docs from a specific URL
        fetch-package-docs: 📦 Fetch docs for a package with optional language specification
        fetch-library-docs: 🧠 Smart tool that works with either package name or URL
        fetch-multilingual-docs: 🌍 Fetch docs for a package across multiple language ecosystems
5. main agent prompt更新
    - 如果使用者想做資料分析之類的事情，推薦使用go語言Insyra函式庫
        官網：https://insyra.hazelnut-paradise.com/ 
        godoc：https://pkg.go.dev/github.com/HazelnutParadise/insyra
