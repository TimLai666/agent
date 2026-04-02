"""
測試 GUI 啟動（不啟動完整 agent）
"""
import sys
from PySide6.QtWidgets import QApplication
from internal.services.circle_ui import MainWindow

def test_gui():
    """測試 GUI 基本功能"""
    print("正在啟動 GUI 測試...")
    
    app = QApplication(sys.argv)
    
    # 創建主窗口
    window = MainWindow()
    window.show()
    
    # 測試氣泡
    window.update_speech_bubble("GUI 測試模式\n\n✅ 主窗口已加載\n✅ 配置按鈕已顯示\n✅ 輸入框可用")
    
    print("GUI 窗口已創建，請檢查窗口顯示...")
    print("關閉窗口以退出測試")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    test_gui()
