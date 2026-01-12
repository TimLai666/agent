import argparse
import asyncio
import os
import sys
import warnings
from contextlib import AsyncExitStack
from httpx import AsyncClient

from dotenv import load_dotenv
from pydantic_ai.messages import ModelRequest, ModelResponse
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread, Signal, QTimer

try:
    from opencc import OpenCC
except ImportError:
    from opencc import OpenCC as OpenCCImpl

    OpenCC = OpenCCImpl

from internal.runtime.system import run_cli
from internal.agents import MainAgent
from internal.co_agents import PhilosopherCoAgent
from internal.logger import logger
from internal.services.agent_factory import load_base_config
from internal.services.voice_manager import VoiceManager
from internal.services.circle_ui import MainWindow

HISTORY_LIMIT = 30


class AIWorker(QThread):
    result_ready = Signal(str)
    history_updated = Signal(list)
    error_occurred = Signal(str)
    started = Signal()

    def __init__(
        self,
        main_agent: MainAgent,
        user_input: str,
        chat_history: list[ModelRequest | ModelResponse] | None,
    ):
        super().__init__()
        self.main_agent = main_agent
        self.user_input = user_input
        self.chat_history = chat_history

    def run(self):
        """運行異步 AI 處理"""
        logger.info("AI Worker thread started")
        self.started.emit()

        # 創建臨時事件循環（不與主循環共享，避免衝突）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def process():
            result_text = ""
            try:
                async for chunk in self.main_agent.run_stream(
                    self.user_input, message_history=self.chat_history
                ):
                    result_text += chunk
                    logger.debug(f"Received chunk: {len(chunk)} chars")
            except Exception as e:
                logger.error(f"Error during run_stream: {e}", exc_info=e)
                raise

            # 簡化 - 不使用 OpenCC，直接返回結果
            result_text = result_text.strip()
            logger.info(f"Result length: {len(result_text)}")

            updated_history = None
            if hasattr(self.main_agent, "_last_messages"):
                updated_history = (
                    self.main_agent._last_messages[-HISTORY_LIMIT:]
                    if self.main_agent._last_messages is not None
                    else None
                )

            return result_text, updated_history

        result, updated_history = None, None
        try:
            # 添加超時機制（120秒）
            result, updated_history = loop.run_until_complete(
                asyncio.wait_for(process(), timeout=120)
            )
            logger.info(
                f"AI Worker completed, result length: {len(result) if result else 0}"
            )
            self.result_ready.emit(result)
            if updated_history:
                logger.info(f"History updated, messages: {len(updated_history)}")
                self.history_updated.emit(updated_history)
        except asyncio.TimeoutError:
            logger.error("AI Worker timeout after 120 seconds")
            self.error_occurred.emit("請求超時，請重試")
        except Exception as e:
            logger.error(f"AI Worker error: {e}", exc_info=e)
            self.error_occurred.emit(f"錯誤: {str(e)}")
        finally:
            # 等待所有任務完成
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            finally:
                loop.close()
                logger.info("AI Worker thread finished")


class GUIAgentApp:
    def __init__(self):
        load_dotenv()
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning)

        self.app = QApplication(sys.argv)
        self.env = dict(os.environ)
        self.base_config = load_base_config(self.env)
        self.voice_manager = VoiceManager()
        self.http_client = AsyncClient(verify=False)

        self.philosopher: PhilosopherCoAgent | None = None
        self.main_agent: MainAgent | None = None
        self.chat_history: list[ModelRequest | ModelResponse] | None = None
        self.current_worker: AIWorker | None = None
        self.mcp_stack: AsyncExitStack | None = None
        self.mcp_started = False
        self.event_loop: asyncio.AbstractEventLoop | None = None

        self.main_window = MainWindow()
        self.main_window.set_input_callback(self.process_input)
        self.main_window.show()

        self.main_window.speech_bubble.setText("初始化中，請稍候...")
        self.main_window.speech_bubble.show()

    async def initialize_agents(self):
        """初始化 AI 代理"""
        self.philosopher = PhilosopherCoAgent.create(
            self.base_config, self.env, self.http_client
        )
        self.main_agent = MainAgent.create(
            self.base_config, self.env, self.http_client, self.philosopher
        )

        # 保存主應用的 AsyncExitStack 以管理 MCP 服務器
        self.mcp_stack = AsyncExitStack()

        # 啟動 MCP 服務器
        try:
            mcp_context_manager = self.main_agent.agent.run_mcp_servers()
            await self.mcp_stack.enter_async_context(mcp_context_manager)
            logger.info("MCP servers started successfully")
            self.mcp_started = True
        except Exception as exc:
            logger.warning(
                "MCP browser tools failed to start; continuing without them.",
                exc_info=exc,
            )
            self.mcp_started = False

    def handle_result(self, output):
        """處理 AI 輸出結果"""
        logger.info(
            f"handle_result called with output: {output[:100] if output else 'None'}..."
        )
        self.main_window.update_speech_bubble(f"AI: {output}")
        logger.info(f"AI Response: {output[:100]}...")

        if self.current_worker:
            self.current_worker.quit()
            self.current_worker.wait()
            self.current_worker = None

    def handle_history_update(self, updated_history):
        """處理聊天歷史更新"""
        self.chat_history = updated_history

    def handle_error(self, error_message):
        """處理錯誤"""
        self.main_window.update_speech_bubble(f"發生錯誤: {error_message}")
        logger.error(error_message)

        if self.current_worker:
            self.current_worker.quit()
            self.current_worker.wait()
            self.current_worker = None

    def show_input_container(self):
        """顯示輸入容器"""
        input_width = min(self.main_window.width() - 40, 500)
        input_height = 45
        self.main_window.input_container.setGeometry(
            (self.main_window.width() - input_width) // 2,
            self.main_window.height() - input_height - 20,
            input_width,
            input_height,
        )
        self.main_window.input_container.show()

    def process_input(self, user_input: str | None = None):
        """處理用戶輸入（文字或語音）"""
        if self.main_agent is None:
            self.main_window.update_speech_bubble("代理尚未初始化完成，請稍候...")
            logger.warning("Main agent not initialized")
            return

        if user_input is None:
            self.main_window.update_speech_bubble("正在聽取語音...")
            user_input = self.voice_manager.recognize_speech()
            if user_input:
                logger.info(f"語音識別: {user_input}")
            else:
                self.main_window.update_speech_bubble("無法識別語音，請重試")
                return

        if user_input and self.main_agent:
            logger.info(f"Processing input: {user_input}")
            self.main_window.update_speech_bubble(f"你: {user_input}")
            QTimer.singleShot(
                500, lambda: self.main_window.update_speech_bubble("正在思考...")
            )

            if self.current_worker and self.current_worker.isRunning():
                self.current_worker.quit()
                self.current_worker.wait()

            # 創建 AIWorker
            self.current_worker = AIWorker(
                self.main_agent, user_input, self.chat_history
            )
            logger.info("Connecting signals...")
            self.current_worker.result_ready.connect(self.handle_result)
            self.current_worker.history_updated.connect(self.handle_history_update)
            self.current_worker.error_occurred.connect(self.handle_error)
            self.current_worker.started.connect(
                lambda: logger.info("Worker started signal received")
            )
            self.current_worker.finished.connect(lambda: logger.info("Worker finished"))
            logger.info("Starting worker thread...")
            self.current_worker.start()
            logger.info("Worker start() called")

    async def cleanup(self):
        """清理資源"""
        # 清理 MCP 服務器（如果已啟動）
        if self.mcp_stack is not None:
            try:
                await self.mcp_stack.aclose()
                logger.info("MCP servers stopped")
            except Exception as exc:
                logger.error(f"Error closing MCP servers: {exc}")
        elif not self.mcp_started:
            logger.info("MCP servers were disabled")

        # 關閉 HTTP 客戶端
        if self.http_client:
            await self.http_client.aclose()
            logger.info("HTTP client closed")

    def run(self):
        """運行應用程序"""

        # 創建並設置共享的事件循環
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.event_loop = loop

        def init_and_start():
            try:
                loop.run_until_complete(self.initialize_agents())
                logger.info("Agents initialized successfully")

                self.main_window.update_speech_bubble("AI 助手已就緒！雙擊開啟輸入框")
                QTimer.singleShot(500, self.show_input_container)
            except Exception as e:
                logger.error(f"Initialization error: {e}")
                self.main_window.update_speech_bubble("初始化失敗，請查看日誌")

        QTimer.singleShot(100, init_and_start)

        result = self.app.exec()

        # 清理資源
        try:
            loop.run_until_complete(self.cleanup())
        finally:
            loop.close()

        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run agent CLI or GUI.")
    parser.add_argument(
        "--prompt",
        nargs="+",
        help="Run once with the provided prompt.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read a single input (or speech) then exit.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the GUI version.",
    )
    args = parser.parse_args()

    try:
        if args.gui:
            gui_app = GUIAgentApp()
            sys.exit(gui_app.run())
        else:
            prompt = " ".join(args.prompt) if args.prompt else None
            asyncio.run(run_cli(prompt_once=prompt, single_turn=args.once))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
