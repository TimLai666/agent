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


class AgentRuntime(QThread):
    ready = Signal()
    result_ready = Signal(str, list)
    error_occurred = Signal(str)

    def __init__(self, base_config, env: dict[str, str]):
        super().__init__()
        self.base_config = base_config
        self.env = env
        self.loop: asyncio.AbstractEventLoop | None = None
        self.http_client: AsyncClient | None = None
        self.philosopher: PhilosopherCoAgent | None = None
        self.main_agent: MainAgent | None = None
        self.mcp_stack: AsyncExitStack | None = None
        self._ready_event: asyncio.Event | None = None
        self._current_future = None

    def run(self):
        loop = asyncio.new_event_loop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        self._ready_event = asyncio.Event()
        loop.create_task(self._initialize())
        loop.run_forever()

        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        finally:
            loop.close()

    async def _initialize(self):
        try:
            self.http_client = AsyncClient(verify=False)
            self.philosopher = PhilosopherCoAgent.create(
                self.base_config, self.env, self.http_client
            )
            self.main_agent = MainAgent.create(
                self.base_config, self.env, self.http_client, self.philosopher
            )
            self.mcp_stack = AsyncExitStack()
            try:
                await self.mcp_stack.enter_async_context(
                    self.main_agent.agent.run_mcp_servers()
                )
                logger.info("MCP servers started in AgentRuntime")
            except Exception as exc:
                logger.warning(
                    "MCP servers failed to start in AgentRuntime; continuing.",
                    exc_info=exc,
                )
            self._ready_event.set()
            self.ready.emit()
        except Exception as e:
            logger.error(f"AgentRuntime init failed: {e}", exc_info=e)
            if self._ready_event:
                self._ready_event.set()
            self.error_occurred.emit("Initialization failed. Check logs.")

    async def _shutdown(self):
        if self.mcp_stack is not None:
            try:
                await self.mcp_stack.aclose()
                logger.info("MCP servers stopped")
            except Exception as exc:
                logger.error(f"Error closing MCP servers: {exc}")
        if self.http_client:
            await self.http_client.aclose()
            logger.info("HTTP client closed")
        if self.loop:
            self.loop.stop()

    def stop(self):
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)

    async def _run_prompt(
        self,
        user_input: str,
        chat_history: list[ModelRequest | ModelResponse] | None,
    ):
        if self._ready_event:
            await self._ready_event.wait()
        if not self.main_agent:
            raise RuntimeError("Main agent not initialized")

        chunks: list[str] = []
        async def collect():
            async for chunk in self.main_agent.run_stream(
                user_input, message_history=chat_history
            ):
                chunks.append(chunk)
                logger.debug(f"Received chunk: {len(chunk)} chars")

        await asyncio.wait_for(collect(), timeout=120)
        result_text = "".join(chunks).strip()
        updated_history = None
        if hasattr(self.main_agent, "_last_messages"):
            updated_history = (
                self.main_agent._last_messages[-HISTORY_LIMIT:]
                if self.main_agent._last_messages is not None
                else None
            )
        return result_text, updated_history

    def submit(
        self,
        user_input: str,
        chat_history: list[ModelRequest | ModelResponse] | None,
    ):
        if not self.loop:
            self.error_occurred.emit("Initialization failed. Check logs.")
            return
        if self._current_future and not self._current_future.done():
            self._current_future.cancel()
        future = asyncio.run_coroutine_threadsafe(
            self._run_prompt(user_input, chat_history), self.loop
        )
        self._current_future = future

        def done_callback(fut):
            try:
                result, updated_history = fut.result()
                self.result_ready.emit(result, updated_history or [])
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"AgentRuntime run error: {e}", exc_info=e)
                self.error_occurred.emit(f"Error: {str(e)}")

        future.add_done_callback(done_callback)


class GUIAgentApp:
    def __init__(self):
        load_dotenv()
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning)

        self.app = QApplication(sys.argv)
        self.env = dict(os.environ)
        self.base_config = load_base_config(self.env)
        self.voice_manager = VoiceManager()
        self.chat_history: list[ModelRequest | ModelResponse] | None = None
        self.runtime_ready = False
        self.runtime = AgentRuntime(self.base_config, self.env)
        self.runtime.ready.connect(self.handle_runtime_ready)
        self.runtime.result_ready.connect(self.handle_result)
        self.runtime.error_occurred.connect(self.handle_error)
        self.runtime.start()

        self.main_window = MainWindow()
        self.main_window.set_input_callback(self.process_input)
        self.main_window.show()

        self.main_window.speech_bubble.setText("Initializing...")
        self.main_window.speech_bubble.show()

    def handle_runtime_ready(self):
        self.runtime_ready = True
        self.main_window.update_speech_bubble(
            "AI ready. Double-click to show input."
        )
        QTimer.singleShot(500, self.show_input_container)

    def handle_result(self, output, updated_history):
        logger.info(
            f"handle_result called with output: {output[:100] if output else 'None'}..."
        )
        self.main_window.update_speech_bubble(f"AI: {output}")
        logger.info(f"AI Response: {output[:100]}...")
        if updated_history:
            self.chat_history = updated_history

    def handle_error(self, error_message):
        self.main_window.update_speech_bubble(f"Error: {error_message}")
        logger.error(error_message)

    def show_input_container(self):
        """Show input container."""
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
        """Handle user input (text or speech)."""
        if not self.runtime_ready:
            self.main_window.update_speech_bubble("Initializing... Please wait.")
            logger.warning("Runtime not ready yet")
            return

        if user_input is None:
            self.main_window.update_speech_bubble("Listening...")
            user_input = self.voice_manager.recognize_speech()
            if user_input:
                logger.info(f"Speech recognized: {user_input}")
            else:
                self.main_window.update_speech_bubble("No speech recognized. Try again.")
                return

        if user_input:
            logger.info(f"Processing input: {user_input}")
            self.main_window.update_speech_bubble(f"You: {user_input}")
            QTimer.singleShot(
                500, lambda: self.main_window.update_speech_bubble("Thinking...")
            )
            self.runtime.submit(user_input, self.chat_history)

    def run(self):
        """Run GUI application."""
        result = self.app.exec()
        self.runtime.stop()
        self.runtime.wait(3000)
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
