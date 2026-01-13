"""
測試配置 WebView 功能
"""
import sys
from PySide6.QtWidgets import QApplication
from internal.services.circle_ui import ConfigWebViewWindow
from internal.services import config_webui

def test_webview():
    """測試 WebView 窗口"""
    app = QApplication(sys.argv)
    
    # 啟動配置 Web UI 服務器
    url = config_webui.ensure_webui_running()
    print(f"Config Web UI running at: {url}")
    
    # 創建 WebView 窗口
    window = ConfigWebViewWindow(url)
    window.show()
    
    print("WebView window created successfully!")
    print("Press Ctrl+C or close the window to exit.")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    test_webview()
