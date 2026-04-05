import argparse
import asyncio
import concurrent.futures
import html as _html_module
import sys
import warnings
from collections import deque
from contextlib import AsyncExitStack
from pathlib import Path

from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication



from internal.agents import MainAgent
from internal.logger import logger
from internal.memory import MemoryManager
from internal.runtime.stream_printer import BACKLOG_SCALE, BASE_DELAY, MIN_FACTOR
from internal.runtime.system import run_cli
from internal.services.agent_factory import load_base_config
from internal.services.circle_ui import MainWindow, ChatWindow, ChoiceDialog, ConfirmDialog, CommandLineEdit
from internal.services.voice_manager import VoiceManager
from internal.services.config_db import (
    list_agent_configs,
    list_mcp_tools,
    list_providers,
    list_remote_mcps,
)
from internal.cli import set_gui_confirm_handler, set_gui_question_handler
from internal.command_handler import CommandHandler
from internal.services import config_webui, config_cli
from internal.compaction import (
    CompactCoordinator,
    ConversationState,
    MAX_CONTEXT_TOKENS,
    recalc_total_tokens,
)

COMMAND_PREFIX = "/"
GUI_CHUNK_EMIT_SIZE = 2000


class AgentRuntime(QThread):
    ready = Signal()
    chunk_ready = Signal(int, str)
    result_ready = Signal(int, str, list)
    error_occurred = Signal(int, str)
    tool_event = Signal(object)
    compaction_event = Signal(bool)   # True = started, False = finished
    compact_result = Signal(object)   # (changed, before, after, messages) or Exception

    def __init__(self, base_config, skill_root_dirs: list[Path] | None = None):
        super().__init__()
        self.base_config = base_config
        self.skill_root_dirs = list(skill_root_dirs or [])
        self.loop: asyncio.AbstractEventLoop | None = None
        self.http_client: AsyncClient | None = None
        self.main_agent: MainAgent | None = None
        self.mcp_stack: AsyncExitStack | None = None
        self._ready_event: asyncio.Event | None = None
        self._current_future = None
        self._request_id = 0
        self._active_request_id = 0
        self._conversation_state = ConversationState(fullMessages=[])
        self._compact_coordinator: CompactCoordinator | None = None

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
            try:
                config_webui.register_skills_reload_handler(None)
            except Exception:
                pass
            loop.close()

    @staticmethod
    def _summarize_exception(exc: Exception) -> str:
        """Extract a concise root-cause message from nested exception groups."""
        current: BaseException | None = exc
        visited: set[int] = set()

        while current is not None and id(current) not in visited:
            visited.add(id(current))
            nested = getattr(current, "exceptions", None)
            if isinstance(nested, (list, tuple)) and nested:
                current = nested[0]
                continue
            if getattr(current, "__cause__", None) is not None:
                current = current.__cause__
                continue
            if getattr(current, "__context__", None) is not None:
                current = current.__context__
                continue
            break

        if current is None:
            return "Unknown error"
        return f"{type(current).__name__}: {current}"

    async def _initialize(self):
        try:
            self.http_client = AsyncClient(verify=False)
            self.main_agent = MainAgent.create(
                self.base_config,
                self.http_client,
                skill_root_dirs=self.skill_root_dirs,
                memory_manager=MemoryManager(),
            )

            def _reload_skills_from_webui() -> dict[str, object]:
                if self.main_agent is None:
                    return {"success": False, "message": "Agent 尚未就緒"}
                from internal.skills_loader import load_skill_registry

                root_dirs = getattr(self.main_agent, "skill_root_dirs", None)
                self.main_agent.skills = load_skill_registry(root_dirs=root_dirs)
                count = len(self.main_agent.skills.list_names())
                return {
                    "success": True,
                    "count": count,
                    "message": f"Skills 已自動重新載入（{count} 個）",
                }

            config_webui.register_skills_reload_handler(_reload_skills_from_webui)

            self.main_agent.set_tool_event_callback(self._emit_tool_event)
            self._compact_coordinator = CompactCoordinator(runner=self.main_agent.run_compaction_subagent)
            self.mcp_stack = AsyncExitStack()
            try:
                await self.mcp_stack.enter_async_context(
                    self.main_agent.agent.run_mcp_servers()
                )
                logger.info("MCP servers started in AgentRuntime")
            except Exception as exc:
                reason = self._summarize_exception(exc)
                logger.warning(
                    "MCP servers failed to start in AgentRuntime; continuing without them. Root cause: %s",
                    reason,
                )
                # 清除已註冊的 MCP toolsets 以防止 agent 嘗試調用不可用的工具
                self.main_agent.agent._user_toolsets = []
                logger.info("Cleared MCP toolsets from agent to prevent tool call failures")
            if self._ready_event:
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
        is_skill_call = tool == "use_skill"
        explicit_skill_name = str(event.get("skill_name") or "").strip()

        def _trim(value: str, limit: int = 80) -> str:
            value = value.strip()
            if len(value) <= limit:
                return value
            return value[: limit - 3] + "..."

        detail = ""
        if tool == "use_skill":
            skill_name = ""
            if isinstance(kwargs, dict):
                raw = kwargs.get("skill_name")
                if isinstance(raw, str):
                    skill_name = raw.strip()
            if not skill_name and explicit_skill_name:
                skill_name = explicit_skill_name
            if not skill_name and args:
                first = args[0]
                if isinstance(first, str):
                    skill_name = first.strip()
            if skill_name:
                detail = f"skill={_trim(skill_name)}"
        elif isinstance(kwargs, dict):
            for key in ("command", "path", "url", "query"):
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    detail = f"{key}={_trim(value)}"
                    break

        if not detail and args:
            try:
                first = args[0]
                if isinstance(first, str) and first.strip():
                    detail = f"arg={_trim(first)}"
            except Exception:
                pass

        label = tool if not detail else f"{tool} ({detail})"

        if is_skill_call:
            if stage == "skill-activated":
                return f"[SKILL] {label}"
            # Suppress use_skill start/end/error lines to keep only one [SKILL] hint.
            return ""

        if stage == "start":
            return f"[>] {label}"
        if stage == "end":
            return "[OK]"
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
        if not line:
            return
        payload = {"request_id": self._active_request_id, "line": line}
        self.tool_event.emit(payload)

    def _emit_todo_event(self, snapshot: str) -> None:
        payload = {"request_id": self._active_request_id, "todo_text": snapshot}
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
            async for chunk in self.main_agent.coordinator_handle_user_turn_stream(
                user_input,
                message_history=chat_history,
                on_todo_update=self._emit_todo_event,
            ):
                if not chunk:
                    continue
                if len(chunk) <= GUI_CHUNK_EMIT_SIZE:
                    chunks.append(chunk)
                    self.chunk_ready.emit(request_id, chunk)
                    logger.debug(f"Received chunk: {len(chunk)} chars")
                    continue

                for i in range(0, len(chunk), GUI_CHUNK_EMIT_SIZE):
                    part = chunk[i : i + GUI_CHUNK_EMIT_SIZE]
                    chunks.append(part)
                    self.chunk_ready.emit(request_id, part)
                logger.debug(
                    "Received oversized chunk: %s chars (split into %s parts)",
                    len(chunk),
                    (len(chunk) + GUI_CHUNK_EMIT_SIZE - 1) // GUI_CHUNK_EMIT_SIZE,
                )

        timeout_val = None

        if timeout_val is None:
            await collect()
        else:
            await asyncio.wait_for(collect(), timeout=timeout_val)
        result_text = "".join(chunks).strip()
        updated_history = None
        if hasattr(self.main_agent, "_last_messages"):
            messages = self.main_agent._last_messages if self.main_agent._last_messages is not None else []
            self._conversation_state.fullMessages = messages
            self._conversation_state.totalTokens = recalc_total_tokens(messages)
            if self._compact_coordinator is not None:
                tokens_before = self._conversation_state.totalTokens
                self.compaction_event.emit(True)
                self._conversation_state = await self._compact_coordinator.maybeCompact(self._conversation_state)
                if self._conversation_state.totalTokens < tokens_before:
                    # tokens decreased → compaction actually ran
                    self.compaction_event.emit(False)
                else:
                    self.compaction_event.emit(False)
            updated_history = self._conversation_state.fullMessages
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
            except (asyncio.CancelledError, concurrent.futures.CancelledError):
                logger.debug("AgentRuntime request %s was cancelled", request_id)
                pass
            except Exception as e:
                logger.error(f"AgentRuntime run error: {e}", exc_info=e)
                self.error_occurred.emit(request_id, f"Error: {str(e)}")

        future.add_done_callback(done_callback)
        return request_id

    async def _force_compact(self):
        if self._ready_event:
            await self._ready_event.wait()
        if not self.main_agent:
            raise RuntimeError("Main agent not initialized")

        base_messages = (
            self._conversation_state.fullMessages
            or getattr(self.main_agent, "_last_messages", None)
            or []
        )
        if not base_messages:
            return False, 0, 0, []

        self._conversation_state.fullMessages = list(base_messages)
        before_count = len(self._conversation_state.fullMessages)
        self._conversation_state.totalTokens = max(
            recalc_total_tokens(self._conversation_state.fullMessages),
            MAX_CONTEXT_TOKENS,
        )
        if self._compact_coordinator is not None:
            self._conversation_state = await self._compact_coordinator.maybeCompact(self._conversation_state)
        after_messages = self._conversation_state.fullMessages
        after_count = len(after_messages)
        changed = after_count < before_count
        return changed, before_count, after_count, after_messages

    def force_compact(self, done_callback=None):
        """Schedule _force_compact on the asyncio loop without blocking the caller.

        done_callback(changed, before, after, updated_history) is called from a
        background thread when compaction finishes — wire it through a Qt signal
        if you need to touch the UI from the callback.
        """
        if not self.loop:
            raise RuntimeError("Initialization failed. Check logs.")
        future = asyncio.run_coroutine_threadsafe(self._force_compact(), self.loop)

        def _on_done(fut):
            try:
                result = fut.result()
            except Exception as exc:
                result = (False, 0, 0, [], exc)
            if done_callback:
                done_callback(*result)

        future.add_done_callback(_on_done)
        return future

    def clear_context(self):
        if not self.loop:
            raise RuntimeError("Initialization failed. Check logs.")

        async def _clear_context():
            if self._ready_event:
                await self._ready_event.wait()
            self._conversation_state = ConversationState(fullMessages=[])
            if self.main_agent is not None:
                self.main_agent._last_messages = None
                self.main_agent._last_assistant_reply = None

        future = asyncio.run_coroutine_threadsafe(_clear_context(), self.loop)
        future.result()


class GUIAgentApp(QObject):
    # Signal for cross-thread voice result (worker thread → main/Qt thread)
    _voice_result_signal = Signal(object)  # str | None

    def __init__(self, skill_root_dirs: list[Path] | None = None):
        super().__init__()
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning)

        self.app = QApplication.instance() or QApplication(sys.argv)
        app_font = self.app.font()
        if app_font.pointSize() <= 0 and app_font.pointSizeF() <= 0:
            safe_app_font = QFont(app_font)
            safe_app_font.setPointSize(11)
            self.app.setFont(safe_app_font)
        self.base_config = load_base_config()
        self.voice_manager = VoiceManager()
        self.chat_history: list[ModelRequest | ModelResponse] | None = None
        self.runtime_ready = False
        self._active_request_id = 0
        self._display_text = ""
        self._tool_log_lines: list[str] = []
        self._todo_snapshot_text = ""
        self._discussion_text = ""  # Q&A from AskUserQuestion
        self._stop_context = ""    # context saved when user stops mid-run
        self._pending_tmp_images: list[str] = []  # temp image paths to delete after agent done
        self._prev_context_tokens = 0   # context token count from previous turn
        self._total_tokens_consumed = 0  # cumulative tokens consumed this session
        self._ui_collapsed = False
        self._waiting_response = False
        self._waiting_status = ""
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
        # Watchdog: restart typewriter if it stalls with pending chars
        self._typewriter_watchdog = QTimer()
        self._typewriter_watchdog.setInterval(500)
        self._typewriter_watchdog.timeout.connect(self._watchdog_kick_typewriter)
        self._typewriter_watchdog.start()
        # Tool HTML cache (avoid recomputing on every typewriter tick)
        self._tool_events_html_cache: str = ""
        self._tool_events_cache_dirty: bool = False
        # Partial result saved when interrupted mid-stream
        self._interrupted_partial: str = ""
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
        self._auto_config_panel_opened = False
        
        # UI 更新節流機制
        self._update_throttle_timer = QTimer()
        self._update_throttle_timer.setSingleShot(True)
        self._update_throttle_timer.timeout.connect(self._flush_display_update)
        self._pending_display_update = False
        self._throttle_interval = 80  # 最小更新間隔（毫秒）
        
        # 創建指令處理器（GUI 專用的輸出回調）
        self.command_handler: CommandHandler | None = None
        
        # 設置 GUI 確認處理器
        set_gui_confirm_handler(self._gui_confirm_handler)
        # 設置 GUI 問題選單處理器
        set_gui_question_handler(self._gui_question_handler)
        
        # Current UI mode: "circle" or "chat"
        self._current_mode: str = "circle"

        self.runtime = AgentRuntime(self.base_config, skill_root_dirs=skill_root_dirs)
        # AgentRuntime (QThread) lives in the main thread but emits signals from run().
        # Qt sees sender/receiver both as main-thread objects and uses DirectConnection.
        # Force QueuedConnection so slots always execute in the main thread event loop.
        _Q = Qt.ConnectionType.QueuedConnection
        self.runtime.ready.connect(self.handle_runtime_ready, _Q)
        self.runtime.result_ready.connect(self.handle_result, _Q)
        self.runtime.chunk_ready.connect(self.handle_chunk, _Q)
        self.runtime.error_occurred.connect(self.handle_error, _Q)
        self.runtime.tool_event.connect(self.handle_tool_event, _Q)
        self.runtime.compaction_event.connect(self.handle_compaction_event, _Q)
        self.runtime.compact_result.connect(self.handle_compact_result, _Q)
        self.runtime.start()

        self.main_window = MainWindow()
        self.main_window.set_input_callback(self.process_input)
        self.main_window.set_stop_callback(self.stop_current_request)
        self.main_window.set_bypass_callback(self._on_bypass_changed)
        self.main_window.set_voice_callback(self._on_voice_event)
        self.main_window.collapse_state_changed.connect(self._on_collapse_state_changed)
        self.main_window.switch_to_chat.connect(self._switch_to_chat)
        # Wire cross-thread voice result signal to main-thread slot
        self._voice_result_signal.connect(self._on_voice_result)
        # 當使用者在輸入框輸入時，重置閒置計時
        try:
            self.main_window.typing.connect(self._reset_idle_timer)
        except Exception:
            pass
        self.main_window.show()

        # Chat window (created lazily but set up now for signal wiring)
        self.chat_window = ChatWindow()
        self.chat_window.set_input_callback(self.process_input)
        self.chat_window.set_stop_callback(self.stop_current_request)
        self.chat_window.set_bypass_callback(self._on_bypass_changed)
        self.chat_window.set_voice_callback(self._on_voice_event)
        self.chat_window.switch_to_circle.connect(self._switch_to_circle)
        try:
            self.chat_window.typing.connect(self._reset_idle_timer)
        except Exception:
            pass

        self.main_window.update_speech_bubble("Initializing...")
        self.main_window.speech_bubble.show()

    def _on_bypass_changed(self, enabled: bool) -> None:
        logger.info(f"Bypass mode {'enabled' if enabled else 'disabled'}")

    # ── Active UI (circle or chat) ────────────────────────────────────────

    @property
    def _active_ui(self):
        """Return the currently visible UI window."""
        if self._current_mode == "chat":
            return self.chat_window
        return self.main_window

    def _switch_to_chat(self) -> None:
        """Switch from circle mode to chat mode."""
        if self._current_mode == "chat":
            return
        self._current_mode = "chat"
        # Populate chat history from completed pairs
        self.chat_window.load_history(list(self._gui_history))
        # Sync live exchange state
        self.chat_window.sync_live_state(
            user_text=self._last_user_input if self._waiting_response else "",
            agent_text=self._display_text,
            is_running=self._waiting_response,
        )
        # Sync bypass state
        self.chat_window.sync_bypass_state(
            self.main_window.is_bypass_mode()
        )
        # Sync running state
        self.chat_window.set_running(self._waiting_response)
        # Sync context meter
        try:
            from internal.compaction import MAX_CONTEXT_TOKENS
            ctx = getattr(self.runtime._conversation_state, "totalTokens", 0) or 0
            self.chat_window.update_context_meter(ctx, MAX_CONTEXT_TOKENS, self._total_tokens_consumed)
        except Exception:
            pass
        self.main_window.hide()
        self.chat_window.show()
        self.chat_window.raise_()
        self.chat_window.activateWindow()

    def _switch_to_circle(self) -> None:
        """Switch from chat mode to circle mode."""
        if self._current_mode == "circle":
            return
        self._current_mode = "circle"
        # Sync bypass state back to circle window
        if self.chat_window.is_bypass_mode() != self.main_window.is_bypass_mode():
            self.main_window._bypass_btn.setChecked(self.chat_window.is_bypass_mode())
            self.main_window._on_bypass_toggled(self.chat_window.is_bypass_mode())
        self.chat_window.hide()
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()
        # Restore current display text
        if self._display_text:
            self.main_window.update_speech_bubble(self._compose_display_text())
        elif self._waiting_response and self._last_user_input:
            self.main_window.update_speech_bubble(
                f"You: {self._last_user_input}\n\n{self._waiting_status}"
            )

    # ── Voice mode handlers ───────────────────────────────────────────────

    def _on_voice_event(self, event: str) -> None:
        """Called from active UI when user interacts with voice button/send."""
        if event == "__start__":
            self._start_voice_recognition()
        elif event == "__cancel__":
            self.voice_manager.cancel()
            self._active_ui.update_speech_bubble("語音取消")
        elif event == "__submit__":
            self.voice_manager.submit_now()
            self._active_ui.update_speech_bubble("辨識中...")

    def _start_voice_recognition(self) -> None:
        self._active_ui.update_speech_bubble("Listening...")

        def _on_result(text):
            self._voice_result_signal.emit(text)

        self.voice_manager.start_listening(on_result=_on_result)

    def _on_voice_result(self, text) -> None:
        """Called in main thread when recognition finishes.
        Appends text to the input field — user presses 發送 manually to submit."""
        self._active_ui.voice_result_ready(text)
        if text:
            logger.info(f"Voice recognized: {text[:60]}")
        else:
            self._active_ui.update_speech_bubble("未識別到語音，請再試一次")

    def _gui_confirm_handler(self, message: str, default_choice: str) -> bool:
        """GUI 模式下的確認處理器（線程安全）"""
        # Bypass mode: auto-approve everything
        if self._active_ui.is_bypass_mode():
            logger.info(f"[bypass] auto-approving: {message[:60]}")
            return True
        logger.info(f"_gui_confirm_handler called: {message[:50]}...")
        result = self._active_ui.show_confirm_dialog(message, default_choice)
        logger.info(f"_gui_confirm_handler returning: {result}")
        return result

    def _gui_question_handler(self, question: str, options: list[str]) -> str:
        """GUI 模式下的問題選單處理器（線程安全）"""
        logger.info(f"_gui_question_handler called: {question[:50]}...")
        result = self._active_ui.show_question_dialog(question, options)
        logger.info(f"_gui_question_handler returning: {result!r}")
        if result and result != "(no answer — user dismissed the dialog)":
            if self._current_mode != "chat":
                # In circle mode update the speech bubble with Q&A context.
                # In chat mode the inline bubble already shows the exchange.
                self._discussion_text = f"**Q:** {question}\n\n**A:** {result}"
                self._request_display_update()
        return result

    def _reset_tool_log(self) -> None:
        self._tool_log_lines = []
        self._tool_events_html_cache = ""
        self._tool_events_cache_dirty = False

    def _reset_todo_snapshot(self) -> None:
        self._todo_snapshot_text = ""
        try:
            self._active_ui.update_todo_drawer("")
        except Exception:
            pass

    # ── Tool event rendering (Claude Code style) ──────────────────────────

    _TOOL_ICONS: dict[str, str] = {
        "bash": "⬛",
        "terminal": "⬛",
        "read": "📄",
        "write": "✏️",
        "edit": "✏️",
        "glob": "🔍",
        "grep": "🔍",
        "web": "🌐",
        "fetch": "🌐",
        "search": "🔍",
        "skill": "⚡",
        "agent": "🤖",
        "subagent": "🤖",
        "todo": "📋",
    }

    def _tool_icon(self, label: str) -> str:
        low = label.lower()
        for key, icon in self._TOOL_ICONS.items():
            if key in low:
                return icon
        return "🔧"

    def _render_tool_line_html(self, line: str) -> str:
        esc = _html_module.escape
        if line.startswith("[>] "):
            label = line[4:]
            icon = self._tool_icon(label)
            return (
                f'<div style="padding:1px 0 1px 2px;color:#6eaee8;font-size:11px;'
                f'font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                f'{icon} <span style="color:#8bbcf0;">{esc(label)}</span>'
                f'</div>'
            )
        if line.startswith("[OK]"):
            return (
                f'<div style="padding:1px 0 1px 2px;color:#4ec94e;font-size:11px;">'
                f'✓</div>'
            )
        if line.startswith("[ERR] "):
            label = line[6:]
            return (
                f'<div style="padding:1px 0 1px 2px;color:#f06b6b;font-size:11px;'
                f'font-family:monospace;">'
                f'✗ {esc(label)}'
                f'</div>'
            )
        if line.startswith("[SKILL] "):
            label = line[8:]
            return (
                f'<div style="padding:1px 0 1px 2px;color:#c792ea;font-size:11px;">'
                f'⚡ {esc(label)}'
                f'</div>'
            )
        if line.startswith("[*] "):
            label = line[4:]
            return (
                f'<div style="padding:1px 0 1px 2px;color:#888;font-size:11px;'
                f'font-family:monospace;">'
                f'· {esc(label)}'
                f'</div>'
            )
        return ""

    def _watchdog_kick_typewriter(self) -> None:
        """Restart typewriter if it stalled with pending characters."""
        if self._pending and not self._typewriter_active:
            self._typewriter_active = True
            self._typewriter_tick()

    def _render_tool_events_html(self) -> str:
        """Render tool log lines as compact Claude Code-style HTML rows (cached)."""
        if not self._tool_log_lines:
            self._tool_events_html_cache = ""
            self._tool_events_cache_dirty = False
            return ""
        if not self._tool_events_cache_dirty and self._tool_events_html_cache:
            return self._tool_events_html_cache
        # Pair [>] start and [OK]/[ERR] together into single rows.
        # Use a FIFO queue so concurrent tool calls are matched correctly.
        rows: list[str] = []
        in_flight: list[str] = []
        esc = _html_module.escape
        for line in self._tool_log_lines[-40:]:  # show last 40 events at most
            if line.startswith("[>] "):
                in_flight.append(line[4:])
            elif line.startswith("[OK]"):
                if in_flight:
                    label = in_flight.pop(0)
                    icon = self._tool_icon(label)
                    rows.append(
                        f'<div style="padding:1px 0 1px 2px;color:#4db87a;font-size:11px;'
                        f'font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                        f'✓ {icon} <span style="color:#7ec8a0;">{esc(label)}</span>'
                        f'</div>'
                    )
                # If no in_flight match, skip orphan [OK] to avoid bare ✓
            elif line.startswith("[ERR] "):
                err = line[6:]
                if in_flight:
                    label = in_flight.pop(0)
                    icon = self._tool_icon(label)
                    rows.append(
                        f'<div style="padding:1px 0 1px 2px;color:#f06b6b;font-size:11px;'
                        f'font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                        f'✗ {icon} <span style="color:#f09090;">{esc(label)}: {esc(err)}</span>'
                        f'</div>'
                    )
                else:
                    rows.append(
                        f'<div style="padding:1px 0 1px 2px;color:#f06b6b;font-size:11px;">'
                        f'✗ {esc(err)}'
                        f'</div>'
                    )
            else:
                rendered = self._render_tool_line_html(line)
                if rendered:
                    rows.append(rendered)

        # Show all still-running tools as in-progress
        for label in in_flight:
            icon = self._tool_icon(label)
            rows.append(
                f'<div style="padding:1px 0 1px 2px;color:#6eaee8;font-size:11px;'
                f'font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                f'▶ {icon} <span style="color:#8bbcf0;">{esc(label)}</span>'
                f'</div>'
            )

        if not rows:
            self._tool_events_html_cache = ""
            self._tool_events_cache_dirty = False
            return ""
        inner = "\n".join(rows)
        result = (
            f'<div style="margin:0 0 6px 0;padding:4px 6px;'
            f'background:rgba(20,20,28,0.7);border-left:2px solid rgba(100,160,255,0.4);'
            f'border-radius:4px;">'
            f'{inner}'
            f'</div>'
        )
        self._tool_events_html_cache = result
        self._tool_events_cache_dirty = False
        return result

    # ── Display composition ────────────────────────────────────────────────

    def _compose_display_text(self, base_text: str | None = None) -> str:
        text = self._display_text if base_text is None else base_text
        blocks: list[str] = []

        tool_html = self._render_tool_events_html()
        if tool_html:
            blocks.append(tool_html)

        if self._discussion_text:
            blocks.append(
                f"<discussion>\n{self._discussion_text}\n</discussion>"
            )

        if text:
            blocks.append(text)

        return "\n\n".join(blocks)

    def handle_tool_event(self, payload: dict) -> None:
        request_id = payload.get("request_id")
        if request_id != self._active_request_id:
            return
        todo_text = payload.get("todo_text")
        if isinstance(todo_text, str) and todo_text.strip():
            self._todo_snapshot_text = todo_text.strip()
            try:
                self._active_ui.update_todo_drawer(self._todo_snapshot_text)
            except Exception:
                pass
            self._request_display_update()
            self._reset_idle_timer()
            return

        line = payload.get("line")
        if not line:
            return
        line_text = str(line).rstrip()
        self._tool_log_lines.append(line_text)
        if len(self._tool_log_lines) > 200:
            self._tool_log_lines = self._tool_log_lines[-200:]
        self._tool_events_cache_dirty = True
        if line_text.startswith("[>] "):
            if "runAgentTask" in line_text:
                self._set_waiting_status("委派子代理中...")
            elif "use_skill" in line_text:
                self._set_waiting_status("載入技能中...")
            else:
                self._set_waiting_status("執行工具中...")
        elif line_text.startswith("[OK]"):
            self._set_waiting_status("整理結果中...")
        self._request_display_update()
        self._reset_idle_timer()

    def handle_compaction_event(self, started: bool) -> None:
        try:
            self._active_ui.set_compact_indicator(started)
        except Exception:
            pass

    def handle_compact_result(self, payload: object) -> None:
        """Called in main thread when /compact finishes."""
        self._active_ui.set_compact_indicator(False)
        try:
            changed, before, after, updated_history = payload  # type: ignore[misc]
            self.chat_history = updated_history or self.chat_history
            if changed:
                self._active_ui.update_speech_bubble(f"已執行壓縮：訊息數 {before} → {after}")
            else:
                self._active_ui.update_speech_bubble("已嘗試壓縮，但目前可壓縮內容不足（需要超過最近保留訊息量）。")
        except Exception as exc:
            self._active_ui.update_speech_bubble(f"手動壓縮失敗：{exc}")

    def _set_waiting_status(self, status: str) -> None:
        self._waiting_status = status
        if not self._waiting_response:
            return
        if self._display_text.strip():
            return
        if self._last_user_input:
            self._active_ui.update_speech_bubble(
                f"You: {self._last_user_input}\n\n{status}"
            )
        else:
            self._active_ui.update_speech_bubble(status)

    def _reset_idle_timer(self) -> None:
        # In chat mode there is no collapse/idle, skip
        if self._current_mode == "chat":
            return
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

    def _is_config_empty(self) -> bool:
        """Return True when all configurable sections are empty."""
        try:
            has_providers = bool(list_providers())
            has_agents = bool(list_agent_configs())
            has_mcp_tools = bool(list_mcp_tools())
            has_remote_mcps = bool(list_remote_mcps())
            return not (has_providers or has_agents or has_mcp_tools or has_remote_mcps)
        except Exception:
            logger.exception("Failed to evaluate config emptiness")
            return False

    def _auto_open_config_panel_if_needed(self) -> None:
        if self._auto_config_panel_opened:
            return
        if not self._is_config_empty():
            return

        self._auto_config_panel_opened = True
        self._active_ui.update_speech_bubble(
            "尚未設定任何 Provider/Agent，已自動打開設定面板。"
        )
        QTimer.singleShot(250, self._active_ui.open_config_webview)

    def handle_runtime_ready(self):
        self.runtime_ready = True

        def _close_window() -> None:
            self.main_window.close()
            self.chat_window.close()

        # 初始化指令處理器
        if self.runtime and self.runtime.main_agent:
            self.command_handler = CommandHandler(
                main_agent=self.runtime.main_agent,
                history=self._gui_history,
                output_callback=self._gui_output_callback,
                exit_callback=_close_window,
                gui_window=self.main_window,  # 傳入 GUI 窗口以支持 webview
            )

        self._active_ui.update_speech_bubble("AI ready. Double-click to show input.")
        QTimer.singleShot(500, self.show_input_container)
        self._auto_open_config_panel_if_needed()
        self._reset_idle_timer()

    def _cleanup_pending_tmp_image(self) -> None:
        """Delete all temp image files created for clipboard paste."""
        import os
        for path in self._pending_tmp_images:
            try:
                if os.path.exists(path):
                    os.unlink(path)
                    logger.debug(f"Deleted temp image: {path}")
            except Exception as e:
                logger.debug(f"Could not delete temp image {path}: {e}")
        self._pending_tmp_images = []

    def handle_result(self, request_id, output, updated_history):
        if request_id != self._active_request_id:
            return
        self._cleanup_pending_tmp_image()
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
            self._active_ui.update_speech_bubble(final_text)
            # 停止動畫，表示 agent 已完成
            self._active_ui.stop_agent_animation()
        logger.info(f"AI Response: {output[:100]}...")
        if updated_history:
            self.chat_history = updated_history
            # 更新 GUI 歷史
            if self._last_user_input:
                self._gui_history.append((self._last_user_input, output or ""))
            # Update token usage display
            try:
                from internal.compaction import MAX_CONTEXT_TOKENS
                ctx = getattr(self.runtime._conversation_state, "totalTokens", 0) or 0
                # Accumulate delta: how many new tokens were consumed this turn.
                # If ctx shrank (compaction occurred), count the new context size as the contribution.
                delta = ctx - self._prev_context_tokens
                self._total_tokens_consumed += delta if delta > 0 else ctx
                self._prev_context_tokens = ctx
                self._active_ui.update_context_meter(ctx, MAX_CONTEXT_TOKENS, self._total_tokens_consumed)
            except Exception:
                pass

        self._waiting_response = False
        self._waiting_status = ""
        self._interrupted_partial = ""
        try:
            self._active_ui.set_running(False)
        except Exception:
            pass
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
        self._cleanup_pending_tmp_image()
        self._active_ui.update_speech_bubble(self._compose_display_text(f"Error: {error_message}"))
        # 停止動畫，即使發生錯誤
        self._active_ui.stop_agent_animation()
        self._waiting_response = False
        self._waiting_status = ""
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
                # If there is no emit because the buffer is still small, wait for more chunks.
                if not emit:
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
                if tag == "<plan-suggestion>":
                    self._set_waiting_status("規劃回覆中...")
                elif tag == "<discussion>":
                    self._set_waiting_status("分析需求中...")
                else:
                    self._set_waiting_status("執行步驟中...")
            else:
                self._stream_mode = "normal"
                self._set_waiting_status("生成回覆中...")
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
                self._active_ui.update_speech_bubble(display_text)
                self._pending_display_update = False
            except Exception as e:
                logger.error(f"Display update error: {e}")

    def _gui_output_callback(self, text: str):
        """GUI 輸出回調函數，用於指令處理器"""
        # 特殊指令：清空
        if text == "__clear__":
            self._active_ui.update_speech_bubble("對話已清空")
            QTimer.singleShot(1000, lambda: self._active_ui.update_speech_bubble(""))
        else:
            # Markdown 格式化輸出
            if not text.startswith("**"):
                # 如果不是 Markdown，轉換為 Markdown
                formatted = text.replace("\n", "\n\n")
            else:
                formatted = text
            # 直接使用原始文字，讓 circle_ui 處理圖片
            self._active_ui.update_speech_bubble(self._compose_display_text(formatted))
        self._reset_idle_timer()

    def show_input_container(self):
        """Show input container."""
        self._active_ui.show_input_container()

    def process_input(self, user_input: str | None = None):
        """Handle user input (text or speech)."""
        if not self.runtime_ready:
            self._active_ui.update_speech_bubble("Initializing... Please wait.")
            logger.warning("Runtime not ready yet")
            return

        if user_input is None:
            # Legacy CLI voice path (GUI voice now goes through _on_voice_result)
            return

        if user_input:
            self._reset_todo_snapshot()
            # 檢查是否為指令
            if user_input.startswith(COMMAND_PREFIX):
                if not self.command_handler:
                    self._active_ui.update_speech_bubble("指令處理器尚未就緒")
                    return
                # 處理指令（異步）
                import asyncio
                async def handle_command():
                    result = await self.command_handler.handle(user_input)
                    if result == "__clear_context__":
                        try:
                            self.runtime.clear_context()
                            self.chat_history = None
                            self._gui_history.clear()
                            if self.command_handler:
                                self.command_handler.clear_context_state()
                            self._last_user_input = ""
                            self._last_assistant_reply = ""
                            self._display_text = ""
                            self._discussion_text = ""
                            self._stop_context = ""
                            self._cleanup_pending_tmp_image()
                            self._reset_tool_log()
                            self._reset_todo_snapshot()
                            self._active_ui.update_speech_bubble("對話 context 已清空")
                            # Also clear chat window history widgets if visible
                            if self._current_mode == "chat":
                                self.chat_window.load_history([])
                        except Exception as exc:
                            self._active_ui.update_speech_bubble(f"清空 context 失敗：{exc}")
                        return
                    if result == "__compact__":
                        self._active_ui.update_speech_bubble("壓縮中…")
                        self._active_ui.set_compact_indicator(True)

                        def _on_compact_done(changed, before, after, updated_history, *_exc):
                            # called from background thread — emit signal to main thread
                            self.runtime.compact_result.emit(
                                (changed, before, after, updated_history)
                            )

                        try:
                            self.runtime.force_compact(done_callback=_on_compact_done)
                        except Exception as exc:
                            self._active_ui.set_compact_indicator(False)
                            self._active_ui.update_speech_bubble(f"手動壓縮失敗：{exc}")
                        return
                    if result:
                        # 指令返回了要執行的提示（如 /retry）
                        self.process_input(result)
                    else:
                        # 指令已處理完畢
                        pass
                
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(handle_command())
                    else:
                        loop.run_until_complete(handle_command())
                except Exception:
                    # 如果無法獲取事件循環，使用 QTimer
                    pass
                return
            
            # 記錄用戶輸入
            self._last_user_input = user_input
            if self.command_handler:
                self.command_handler.update_last_prompt(user_input)

            # ── Retrieve any attachment from the input bar ─────────────────
            _tmp_image_paths: list[str] = []
            try:
                attached_file = self._active_ui.get_attached_file_path()
                if attached_file:
                    user_input = f"{user_input}\n\n[Attached file: {attached_file}]"
            except Exception:
                pass
            try:
                _tmp_image_paths = self._active_ui.pop_attached_images_as_tempfiles()
                if _tmp_image_paths:
                    self._pending_tmp_images = _tmp_image_paths
                    if len(_tmp_image_paths) == 1:
                        user_input = (
                            f"{user_input}\n\n"
                            f"[User pasted an image saved to: {_tmp_image_paths[0]}]\n"
                            f"Read or analyse this image file."
                        )
                    else:
                        paths_str = "\n".join(f"  - {p}" for p in _tmp_image_paths)
                        user_input = (
                            f"{user_input}\n\n"
                            f"[User pasted {len(_tmp_image_paths)} images saved to:]\n"
                            f"{paths_str}\n"
                            f"Read or analyse these image files."
                        )
            except Exception:
                pass
            # ──────────────────────────────────────────────────────────────

            # ── Inject stop-context from previous cancelled request ────────
            if self._stop_context and not self._waiting_response:
                user_input = f"{self._stop_context}\nNew message from user: {user_input}"
                self._stop_context = ""
            # ──────────────────────────────────────────────────────────────

            # ── Interrupt-with-progress ────────────────────────────────────
            # If agent is mid-stream, save partial result and inject context
            if self._waiting_response:
                partial = (self._display_text or "").strip()
                if partial:
                    # Keep only a brief excerpt to avoid bloating context
                    excerpt = partial[:400] + ("…" if len(partial) > 400 else "")
                    self._interrupted_partial = partial
                    user_input = (
                        f"[Interrupt] User sent a new message while you were responding.\n"
                        f"Your partial response so far (do not repeat it):\n"
                        f"---\n{excerpt}\n---\n\n"
                        f"New message from user: {user_input}\n\n"
                        f"Decide: should you continue the original task (incorporating the new message), "
                        f"pivot entirely, or address the new message first? Act accordingly."
                    )
                else:
                    self._interrupted_partial = ""
            else:
                self._interrupted_partial = ""
            # ──────────────────────────────────────────────────────────────

            logger.info(f"Processing input: {user_input[:80]}...")
            self._active_ui.update_speech_bubble(f"You: {self._last_user_input}")

            # 啟動動畫並顯示等待狀態
            def start_waiting():
                if not self._waiting_response:
                    return
                self._set_waiting_status("分析需求中...")
                self._active_ui.start_agent_animation()

            QTimer.singleShot(500, start_waiting)
            self._display_text = ""
            self._discussion_text = ""
            self._reset_tool_log()
            self._pending.clear()
            self._stream_buffer = ""
            self._stream_mode = "normal"
            self._typewriter_active = False
            self._typewriter_timer.stop()
            self._waiting_response = True
            self._waiting_status = "分析需求中..."
            self._idle_timer.stop()
            # Update stop button state
            try:
                self._active_ui.set_running(True)
            except Exception:
                pass
            request_id = self.runtime.submit(user_input, self.chat_history)
            if request_id:
                self._active_request_id = request_id

    def stop_current_request(self) -> None:
        """Cancel the current agent request (stop button handler)."""
        if not self._waiting_response:
            return
        self._cleanup_pending_tmp_image()
        try:
            if self.runtime._current_future and not self.runtime._current_future.done():
                self.runtime._current_future.cancel()
        except Exception:
            pass
        # Save interrupted context so next message can reference it
        partial = (self._display_text or "").strip()
        if self._last_user_input:
            excerpt = partial[:300] + ("…" if len(partial) > 300 else "") if partial else ""
            self._stop_context = (
                f"[Previous session was interrupted by user]\n"
                f"User had asked: {self._last_user_input}\n"
                + (f"Your partial response: {excerpt}\n" if excerpt else "")
            )
        self._waiting_response = False
        self._waiting_status = ""
        if partial:
            self._active_ui.update_speech_bubble(self._compose_display_text())
        else:
            self._active_ui.update_speech_bubble("(stopped)")
        self._active_ui.stop_agent_animation()
        try:
            self._active_ui.set_running(False)
        except Exception:
            pass

    def run(self):
        """Run GUI application."""
        try:
            result = self.app.exec()
        finally:
            # 清理 GUI 處理器
            set_gui_confirm_handler(None)
            set_gui_question_handler(None)
            self.runtime.stop()
            self.runtime.wait(3000)
        return result


def _resolve_skill_root_dirs(raw_paths: list[str] | None) -> list[Path]:
    """Resolve and normalize skill root directories from CLI args."""
    if not raw_paths:
        return []

    # 使用沙盒目錄作為基準目錄，保持一致性
    from internal.paths import TIM_AGENT_SANDBOX_DIR
    
    resolved: list[Path] = []
    seen: set[str] = set()

    for raw in raw_paths:
        text = (raw or "").strip()
        if not text:
            continue

        path_obj = Path(text).expanduser()
        if not path_obj.is_absolute():
            path_obj = (TIM_AGENT_SANDBOX_DIR / path_obj).resolve()
        else:
            path_obj = path_obj.resolve()

        key = str(path_obj).lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path_obj)

    return resolved


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
        "--cli",
        action="store_true",
        help="Launch the CLI version (default behavior; kept for compatibility).",
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
    parser.add_argument(
        "--skills-dir",
        nargs="+",
        metavar="PATH",
        help="One or more skill root directories. Defaults to built-in skills/ when omitted.",
    )
    args = parser.parse_args()
    skill_root_dirs = _resolve_skill_root_dirs(args.skills_dir)

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
            gui_app = GUIAgentApp(skill_root_dirs=skill_root_dirs)
            sys.exit(gui_app.run())
        else:
            prompt = " ".join(args.prompt) if args.prompt else None
            asyncio.run(
                run_cli(
                    prompt_once=prompt,
                    single_turn=args.once,
                    skill_root_dirs=skill_root_dirs,
                )
            )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
