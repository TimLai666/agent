from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from dotenv import load_dotenv
import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread, Signal, QTimer

from opencc import OpenCC

from internal.prompts import SYSTEM_PROMPT
from internal.tools.tools import add_all_tools
from internal.services.voice_manager import VoiceManager
from internal.services.circle_ui import MainWindow

class AIWorker(QThread):
    result_ready = Signal(str)
    history_updated = Signal(list)
    
    def __init__(self, agent, user_input, chat_history):
        super().__init__()
        self.agent = agent
        self.user_input = user_input
        self.chat_history = chat_history
        
    def run(self):
        result = self.agent.run_sync(
            user_prompt=self.user_input, 
            message_history=self.chat_history
        )
        # 將結果轉換為繁體中文
        cc = OpenCC('s2twp')
        self.result_ready.emit(cc.convert(result.output.strip()))
        # 發送更新後的聊天歷史
        updated_history = result.all_messages()[-30:]
        self.history_updated.emit(updated_history)

def main() -> None:
    load_dotenv()
    
    # 創建 QApplication
    app = QApplication(sys.argv)
    
    mainWindow = MainWindow()
    mainWindow.show()
    # 語音輸入功能測試於主程式
    # voice_manager = VoiceManager()
    # recognized_text = voice_manager.real_time_speech_recognition()
    # print(f"識別結果: {recognized_text}")  # 輸出識別結果
    # voice_manager.close()  # 清理資源

    ollama_model = OpenAIModel(
        model_name='qwen3:14b', provider=OpenAIProvider(base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1')
    )
    agent: Agent[None, str] = Agent(
        model=ollama_model,
        system_prompt=SYSTEM_PROMPT,
    )

    add_all_tools(agent)

    chat_history: list[ModelRequest | ModelResponse] | None = None
    current_worker = None  # 保存當前工作線程的引用
    
    def handle_result(output):
        mainWindow.update_speech_bubble(output)
        print(output)
        # 清理完成的線程
        if current_worker:
            current_worker.quit()
            current_worker.wait()
    
    def handle_history_update(updated_history):
        nonlocal chat_history
        chat_history = updated_history
    
    def process_input():
        nonlocal current_worker
        
        # 如果有正在運行的線程，等待它完成
        if current_worker and current_worker.isRunning():
            current_worker.quit()
            current_worker.wait()
        
        user_input = input("請輸入文字: ")
        if user_input:
            current_worker = AIWorker(agent, user_input, chat_history)
            current_worker.result_ready.connect(handle_result)
            current_worker.history_updated.connect(handle_history_update)
            current_worker.finished.connect(lambda: QTimer.singleShot(100, process_input))
            current_worker.start()
    
    # 開始處理輸入
    process_input()
    
    # 啟動Qt事件循環
    app.exec()

if __name__ == "__main__":
    main()
