"""
測試 GUI 輸出框的彩色動畫外框
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from internal.services.circle_ui import MainWindow

def test_animation():
    """測試動畫效果"""
    print("正在啟動動畫測試...")

    app = QApplication(sys.argv)

    # 創建主窗口
    window = MainWindow()
    window.show()

    # 初始訊息
    window.update_speech_bubble("AI Assistant 已就緒\n\n即將開始測試動畫效果...")

    # 3 秒後啟動動畫
    def start_animation_test():
        window.update_speech_bubble("思考中...\n\n彩色外框動畫應該正在運行")
        window.start_agent_animation()
        print("✓ 動畫已啟動")

        # 5 秒後停止動畫
        QTimer.singleShot(5000, stop_animation_test)

    def stop_animation_test():
        window.update_speech_bubble("測試完成！\n\n動畫已停止\n\n外框應該消失了")
        window.stop_agent_animation()
        print("✓ 動畫已停止")

        # 再過 2 秒重新開始測試
        QTimer.singleShot(2000, start_animation_test)

    QTimer.singleShot(3000, start_animation_test)

    print("GUI 窗口已創建，請觀察以下測試：")
    print("1. 3秒後會啟動彩色外框動畫")
    print("2. 動畫會持續 5 秒")
    print("3. 5秒後動畫停止")
    print("4. 然後會循環重複")
    print("\n關閉窗口以退出測試")

    sys.exit(app.exec())

if __name__ == "__main__":
    test_animation()
