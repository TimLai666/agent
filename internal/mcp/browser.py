from internal.mcp.client_builder import McpClient
import shutil
import os

# 自動取得系統中的 Chrome 可執行檔路徑
chrome_path = None

for cmd in ["google-chrome", "chrome", "chromium", "chromium-browser"]:
    path = shutil.which(cmd)
    if path:
        chrome_path = path
        break
    path = shutil.which(cmd + ".exe")  # Windows 可執行檔
    if path:
        chrome_path = path
        break

if not chrome_path:
    # 嘗試使用常見的安裝路徑（僅限 Windows）
    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            chrome_path = path
            break
if not chrome_path:
    print("Warning: Chrome executable not found in system PATH. The browser MCP server may not function correctly.")

browser = McpClient(
    command="npx",
    args=["pptr-mcp","--viewport=1280x720"],
    env={"CHROME_PATH": chrome_path} if chrome_path else None,
)