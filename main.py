import argparse
import asyncio
import os
import sys
import warnings
from collections import deque
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication



from internal.agents import MainAgent
from internal.logger import logger
from internal.runtime.stream_printer import BACKLOG_SCALE, BASE_DELAY, MIN_FACTOR
from internal.runtime.system import run_cli
from internal.services.agent_factory import load_base_config
from internal.services.circle_ui import MainWindow, ConfirmDialog, CommandLineEdit
from internal.services.voice_manager import VoiceManager
from internal.cli import set_gui_confirm_handler
from internal.command_handler import CommandHandler
from internal.services import config_webui, config_cli

HISTORY_LIMIT = 30
COMMAND_PREFIX = "/"


class AgentRuntime(QThread):
    ready = Signal()
    chunk_ready = Signal(int, str)
    result_ready = Signal(int, str, list)
    error_occurred = Signal(int, str)
    tool_event = Signal(object)

    def __init__(self, base_config, env: dict[str, str]):
        super().__init__()
        self.base_config = base_config
        self.env = env
        self.loop: asyncio.AbstractEventLoop | None = None
        self.http_client: AsyncClient | None = None
        self.main_agent: MainAgent | None = None
        self.mcp_stack: AsyncExitStack | None = None
        self._ready_event: asyncio.Event | None = None
        self._current_future = None
        self._request_id = 0
        self._active_request_id = 0

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
            self.main_agent = MainAgent.create(self.base_config, self.env, self.http_client)
            self.main_agent.set_tool_event_callback(self._emit_tool_event)
            self.mcp_stack = AsyncExitStack()
            try:
                await self.mcp_stack.enter_async_context(
                    self.main_agent.agent.run_mcp_servers()
                )
                logger.info("MCP servers started in AgentRuntime")
            except Exception as exc:
                logger.warning(
                    "MCP servers failed to start in AgentRuntime; clearing toolsets and continuing.",
                    exc_info=exc,
                )
                # 清除已註冊的 MCP toolsets 以防止 agent 嘗試調用不可用的工具
                self.main_agent.agent._user_toolsets = []
                logger.info("Cleared MCP toolsets from agent to prevent tool call failures")
            self._ready_event.set()
            self.ready.emit()
        except Exception as e:
            logger.error(f"AgentRuntime init failed: {e}", exc_info=e)
            if self._ready_event:
                self._ready_event.set()
            self.error_occurred.emit(0, "Initialization failed. Check logs.")

    def _format_tool_line(self, event: dict) -> str:
        tool = str(event.get("tool") or "tool")
        args = event.get("args") or ()
        kwargs = event.get("kwargs") or {}
        stage = str(event.get("stage") or "")

        label = tool
        if isinstance(kwargs, dict):
            for key in ("command", "path", "url", "query"):
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    label = value.strip()
                    break
        if label == tool and args:
            try:
                first = args[0]
                if isinstance(first, str) and first.strip():
                    label = f"{tool} {first.strip()}"
            except Exception:
                pass

        if stage == "start":
            return f"[>] {label}"
        if stage == "end":
            return f"[OK] {label}"
        if stage == "error":
            error = str(event.get("error") or "")
            suffix = f": {error}" if error else ""
            return f"[ERR] {label}{suffix}"
        return f"[*] {label}"

    def _emit_tool_event(self, event: dict) -> None:
        try:
            line = self._format_tool_line(event)
        except Exception as exc:
            logger.debug(f"Tool event format failed: {exc}")
            return
        payload = {"request_id": self._active_request_id, "line": line}
        self.tool_event.emit(payload)

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
        request_id: int,
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
                if not chunk:
                    continue
                chunks.append(chunk)
                self.chunk_ready.emit(request_id, chunk)
                logger.debug(f"Received chunk: {len(chunk)} chars")

        # Support disabling or customizing the response timeout via AGENT_RESPONSE_TIMEOUT env var.
        # If unset, empty, or set to 'none'/'0'/'off', the agent will wait indefinitely for a response.
        timeout_str = os.getenv("AGENT_RESPONSE_TIMEOUT", "0").strip()
        if timeout_str and timeout_str.lower() not in ("none", "0", "off", "infinite"):
            try:
                timeout_val = int(timeout_str)
            except Exception:
                timeout_val = 120
        else:
            timeout_val = None

        if timeout_val is None:
            await collect()
        else:
            await asyncio.wait_for(collect(), timeout=timeout_val)
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
            self.error_occurred.emit(0, "Initialization failed. Check logs.")
            return None
        if self._current_future and not self._current_future.done():
            self._current_future.cancel()
        self._request_id += 1
        request_id = self._request_id
        self._active_request_id = request_id
        future = asyncio.run_coroutine_threadsafe(
            self._run_prompt(request_id, user_input, chat_history), self.loop
        )
        self._current_future = future

        def done_callback(fut):
            try:
                result, updated_history = fut.result()
                self.result_ready.emit(request_id, result, updated_history or [])
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"AgentRuntime run error: {e}", exc_info=e)
                self.error_occurred.emit(request_id, f"Error: {str(e)}")

        future.add_done_callback(done_callback)
        return request_id


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
        self._active_request_id = 0
        self._display_text = ""
        self._tool_log_lines: list[str] = []
        self._ui_collapsed = False
        self._waiting_response = False
        self._auto_expand_on_result = False
        self._idle_timeout_ms = 60000
        self._idle_timer = QTimer()
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        self._pending = deque()
        self._stream_buffer = ""
        self._stream_mode = "normal"
        self._typewriter_active = False
        self._typewriter_timer = QTimer()
        self._typewriter_timer.setSingleShot(True)
        self._typewriter_timer.timeout.connect(self._typewriter_tick)
        self._tags = (
            "<tool-execution>",
            "</tool-execution>",
            "<plan-suggestion>",
            "</plan-suggestion>",
            "<discussion>",
            "</discussion>",
        )
        self._max_tag_len = max(len(tag) for tag in self._tags)
        self._last_user_input = ""  # 記錄最後的用戶輸入（用於 /retry）
        self._last_assistant_reply = ""  # 記錄最後的助手回覆（用於 /last）
        self._gui_history: list[tuple[str, str]] = []  # GUI 對話歷史
        
        # UI 更新節流機制
        self._update_throttle_timer = QTimer()
        self._update_throttle_timer.setSingleShot(True)
        self._update_throttle_timer.timeout.connect(self._flush_display_update)
        self._pending_display_update = False
        self._throttle_interval = 50  # 最小更新間隔（毫秒）
        
        # 創建指令處理器（GUI 專用的輸出回調）
        self.command_handler: CommandHandler | None = None
        
        # 設置 GUI 確認處理器
        set_gui_confirm_handler(self._gui_confirm_handler)
        
        self.runtime = AgentRuntime(self.base_config, self.env)
        self.runtime.ready.connect(self.handle_runtime_ready)
        self.runtime.result_ready.connect(self.handle_result)
        self.runtime.chunk_ready.connect(self.handle_chunk)
        self.runtime.error_occurred.connect(self.handle_error)
        self.runtime.tool_event.connect(self.handle_tool_event)
        self.runtime.start()

        self.main_window = MainWindow()
        self.main_window.set_input_callback(self.process_input)
        self.main_window.collapse_state_changed.connect(self._on_collapse_state_changed)
        # 當使用者在輸入框輸入時，重置閒置計時
        try:
            self.main_window.typing.connect(self._reset_idle_timer)
        except Exception:
            pass
        self.main_window.show()

        self.main_window.update_speech_bubble("Initializing...")
        self.main_window.speech_bubble.show()

    def _gui_confirm_handler(self, message: str, default_choice: str) -> bool:
        """
        GUI 模式下的確認處理器（線程安全）
        這個方法會在 AgentRuntime 線程中被調用，
        但對話框會在主 GUI 線程中顯示
        """
        logger.info(f"_gui_confirm_handler called: {message[:50]}...")
        result = self.main_window.show_confirm_dialog(message, default_choice)
        logger.info(f"_gui_confirm_handler returning: {result}")
        return result

    def _reset_tool_log(self) -> None:
        self._tool_log_lines = []

    def _compose_display_text(self, base_text: str | None = None) -> str:
        text = self._display_text if base_text is None else base_text
        if not self._tool_log_lines:
            return text
        tool_block = ("<tool-execution>\n" + "\n".join(self._tool_log_lines) + "\n</tool-execution>")
        if text:
            return tool_block + "\n\n" + text
        return tool_block

    def handle_tool_event(self, payload: dict) -> None:
        request_id = payload.get("request_id")
        line = payload.get("line")
        if request_id != self._active_request_id or not line:
            return
        self._tool_log_lines.append(str(line).rstrip())
        if len(self._tool_log_lines) > 200:
            self._tool_log_lines = self._tool_log_lines[-200:]
        self._request_display_update()
        self._reset_idle_timer()

    def _reset_idle_timer(self) -> None:
        if self._ui_collapsed or self._waiting_response:
            return
        self._idle_timer.start(self._idle_timeout_ms)

    def _on_idle_timeout(self) -> None:
        if self._waiting_response or self._ui_collapsed:
            return
        self._collapse_ui()

    def _collapse_ui(self) -> None:
        if self._ui_collapsed:
            return
        self.main_window.collapse_to_edge()

    def _expand_ui(self) -> None:
        if not self._ui_collapsed:
            return
        self.main_window.expand_from_edge()

    def _on_collapse_state_changed(self, collapsed: bool) -> None:
        self._ui_collapsed = collapsed
        if collapsed:
            self._idle_timer.stop()
            if self._waiting_response:
                self._auto_expand_on_result = True
        else:
            self._auto_expand_on_result = False
            self._reset_idle_timer()

    def handle_runtime_ready(self):
        self.runtime_ready = True
        
        # 初始化指令處理器
        if self.runtime and self.runtime.main_agent:
            self.command_handler = CommandHandler(
                main_agent=self.runtime.main_agent,
                history=self._gui_history,
                output_callback=self._gui_output_callback,
                exit_callback=self.main_window.close,
                gui_window=self.main_window,  # 傳入 GUI 窗口以支持 webview
            )
        
        self.main_window.update_speech_bubble("AI ready. Double-click to show input.")
        QTimer.singleShot(500, self.show_input_container)
        self._reset_idle_timer()

    def handle_result(self, request_id, output, updated_history):
        if request_id != self._active_request_id:
            return
        logger.info(
            f"handle_result called with output: {output[:100] if output else 'None'}..."
        )
        if output and output not in self._display_text:
            self._display_text = f"{output}"
            self._last_assistant_reply = output  # 記錄助手回覆
            if self.command_handler:
                self.command_handler.update_last_reply(output)
            self._pending.clear()
            self._stream_buffer = ""
            self._stream_mode = "normal"
            self._typewriter_active = False
            self._typewriter_timer.stop()
            # 直接使用原始文字，讓 circle_ui 處理圖片
            final_text = self._compose_display_text()
            self.main_window.update_speech_bubble(final_text)
            # 停止動畫，表示 agent 已完成
            self.main_window.stop_agent_animation()
        logger.info(f"AI Response: {output[:100]}...")
        if updated_history:
            self.chat_history = updated_history
            # 更新 GUI 歷史
            if self._last_user_input:
                self._gui_history.append((self._last_user_input, output or ""))
                if len(self._gui_history) > HISTORY_LIMIT:
                    self._gui_history = self._gui_history[-HISTORY_LIMIT:]

        self._waiting_response = False
        if self._auto_expand_on_result:
            self._expand_ui()
        self._reset_idle_timer()


    def handle_chunk(self, request_id, chunk):
        if request_id != self._active_request_id:
            return
        if chunk:
            self._process_stream_chunk(chunk)

    def handle_error(self, request_id, error_message):
        if request_id not in (0, self._active_request_id):
            return
        self.main_window.update_speech_bubble(self._compose_display_text(f"Error: {error_message}"))
        # 停止動畫，即使發生錯誤
        self.main_window.stop_agent_animation()
        self._waiting_response = False
        if self._auto_expand_on_result:
            self._expand_ui()
        self._reset_idle_timer()
        logger.error(error_message)

    def _next_tag(self, text: str):
        earliest_idx = -1
        earliest_tag = ""
        for tag in self._tags:
            idx = text.find(tag)
            if idx == -1:
                continue
            if earliest_idx == -1 or idx < earliest_idx:
                earliest_idx = idx
                earliest_tag = tag
        if earliest_idx == -1:
            return None
        return earliest_idx, earliest_tag

    def _process_stream_chunk(self, chunk: str):
        self._stream_buffer += chunk
        updated = False
        while self._stream_buffer:
            found = self._next_tag(self._stream_buffer)
            if not found:
                # If buffer is longer than tag lookahead, emit the bulk and keep tail to preserve tags
                if len(self._stream_buffer) > self._max_tag_len - 1:
                    emit = self._stream_buffer[: -(self._max_tag_len - 1)]
                    self._stream_buffer = self._stream_buffer[
                        -(self._max_tag_len - 1) :
                    ]
                else:
                    emit = ""
                if emit:
                    if self._stream_mode == "normal":
                        self._pending.append(emit)
                    else:
                        self._display_text += emit
                        updated = True
                # If there is no emit because the buffer is still small, show a transient preview
                if not emit:
                    # Show partial preview (do not consume buffer) so UI doesn't appear stalled
                    try:
                        # Avoid committing preview if nothing to show
                        if self._stream_buffer:
                            self.main_window.update_speech_bubble(self._compose_display_text(self._display_text + self._stream_buffer))
                    except Exception:
                        pass
                    break
                continue

            idx, tag = found
            if idx > 0:
                prefix = self._stream_buffer[:idx]
                if self._stream_mode == "normal":
                    self._pending.append(prefix)
                else:
                    self._display_text += prefix
                    updated = True

            self._display_text += tag
            updated = True
            if tag in ("<tool-execution>", "<plan-suggestion>", "<discussion>"):
                self._stream_mode = "fast"
            else:
                self._stream_mode = "normal"
            self._stream_buffer = self._stream_buffer[idx + len(tag) :]

        if updated:
            # 使用節流更新
            self._request_display_update()
        self._reset_idle_timer()

        if self._pending and not self._typewriter_active:
            self._typewriter_active = True
            self._typewriter_tick()

    def _typewriter_tick(self):
        if not self._pending:
            self._typewriter_active = False
            return

        backlog_len = sum(len(s) for s in self._pending)
        left = self._pending[0]
        ch, rest = left[0], left[1:]
        if rest:
            self._pending[0] = rest
        else:
            self._pending.popleft()

        self._display_text += ch
        # 使用節流更新而非直接更新
        self._request_display_update()
        self._reset_idle_timer()

        speed_factor = 1.0 / (1.0 + (backlog_len / BACKLOG_SCALE))
        delay = max(BASE_DELAY * MIN_FACTOR, BASE_DELAY * speed_factor)
        self._typewriter_timer.start(int(delay * 1000))
    
    def _request_display_update(self):
        """請求顯示更新（節流）"""
        self._pending_display_update = True
        if not self._update_throttle_timer.isActive():
            self._flush_display_update()
            self._update_throttle_timer.start(self._throttle_interval)
    
    def _flush_display_update(self):
        """執行實際的顯示更新"""
        if self._pending_display_update:
            try:
                # 直接使用原始文字，讓 circle_ui 處理圖片
                display_text = self._compose_display_text()
                self.main_window.update_speech_bubble(display_text)
                self._pending_display_update = False
            except Exception as e:
                logger.error(f"Display update error: {e}")

    def _gui_output_callback(self, text: str):
        """GUI 輸出回調函數，用於指令處理器"""
        # 特殊指令：清空
        if text == "__clear__":
            self.main_window.update_speech_bubble("對話已清空")
            QTimer.singleShot(1000, lambda: self.main_window.update_speech_bubble(""))
        else:
            # Markdown 格式化輸出
            if not text.startswith("**"):
                # 如果不是 Markdown，轉換為 Markdown
                formatted = text.replace("\n", "\n\n")
            else:
                formatted = text
            # 直接使用原始文字，讓 circle_ui 處理圖片
            self.main_window.update_speech_bubble(self._compose_display_text(formatted))
        self._reset_idle_timer()

    def show_input_container(self):
        """Show input container."""
        self.main_window.show_input_container()

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
                self.main_window.update_speech_bubble(
                    "No speech recognized. Try again."
                )
                return

        if user_input:
            # 檢查是否為指令
            if user_input.startswith(COMMAND_PREFIX):
                if not self.command_handler:
                    self.main_window.update_speech_bubble("指令處理器尚未就緒")
                    return
                # 處理指令
                result = self.command_handler.handle(user_input)
                if result:
                    # 指令返回了要執行的提示（如 /retry）
                    user_input = result
                else:
                    # 指令已處理完畢
                    return
            
            # 記錄用戶輸入
            self._last_user_input = user_input
            if self.command_handler:
                self.command_handler.update_last_prompt(user_input)
            
            logger.info(f"Processing input: {user_input}")
            self.main_window.update_speech_bubble(f"You: {user_input}")

            # 啟動動畫並顯示 Thinking 狀態
            def start_thinking():
                self.main_window.update_speech_bubble(
                    f"You: {user_input}\n\nThinking..."
                )
                self.main_window.start_agent_animation()

            QTimer.singleShot(500, start_thinking)
            self._display_text = ""
            self._reset_tool_log()
            self._pending.clear()
            self._stream_buffer = ""
            self._stream_mode = "normal"
            self._typewriter_active = False
            self._typewriter_timer.stop()
            self._waiting_response = True
            self._idle_timer.stop()
            request_id = self.runtime.submit(user_input, self.chat_history)
            if request_id:
                self._active_request_id = request_id

    def run(self):
        """Run GUI application."""
        try:
            result = self.app.exec()
        finally:
            # 清理 GUI 確認處理器
            set_gui_confirm_handler(None)
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
    parser.add_argument(
        "--config",
        action="store_true",
        help="Open configuration menu (CLI) to manage providers and agent settings.",
    )
    parser.add_argument(
        "--config-web",
        action="store_true",
        help="Open configuration Web UI to manage providers and agent settings.",
    )
    args = parser.parse_args()

    try:
        # Ensure Web UI server is running in background (always on)
        try:
            config_webui.ensure_webui_running()
        except Exception:
            # best-effort; continue if web UI cannot start
            pass

        # Backwards-compatible flags: if user explicitly requested, run them.
        if args.config:
            config_cli.cmd_config_menu()
        elif args.config_web:
            # Open browser to config page
            try:
                import webbrowser

                url = config_webui.ensure_webui_running()
                webbrowser.open(url, new=2)
                print(f"Opened config web UI: {url}")
            except Exception:
                print("Config web UI available; open your browser to http://127.0.0.1:5000")
        elif args.gui:
            gui_app = GUIAgentApp()
            sys.exit(gui_app.run())
        else:
            prompt = " ".join(args.prompt) if args.prompt else None
            asyncio.run(run_cli(prompt_once=prompt, single_turn=args.once))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
