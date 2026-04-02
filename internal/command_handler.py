"""
共用的指令處理模組
CLI 和 GUI 模式都使用此模組處理用戶指令
"""

from typing import Callable, Optional
import threading
import webbrowser

from internal.services import config_webui
from internal.services import config_cli
from internal.agents import MainAgent
from internal.logger import logger


class CommandHandler:
    """處理所有用戶指令（CLI 和 GUI 共用）"""
    
    def __init__(
        self,
        main_agent: MainAgent,
        history: list[tuple[str, str]],
        output_callback: Optional[Callable[[str], None]] = None,
        exit_callback: Optional[Callable[[], None]] = None,
        gui_window = None,
    ):
        """
        初始化指令處理器
        
        Args:
            main_agent: 主代理實例
            history: 對話歷史記錄（用戶輸入、助手回覆）列表
            output_callback: 輸出回調函數（用於 GUI 顯示），如果為 None 則使用 print
            exit_callback: 退出回調函數（用於 GUI 關閉視窗）
            gui_window: GUI 主窗口實例（用於打開 webview）
        """
        self.main_agent = main_agent
        self.history = history
        self.output_callback = output_callback or print
        self.exit_callback = exit_callback
        self.gui_window = gui_window
        self.last_user_prompt = ""
        self.last_assistant_reply = ""
    
    def handle(self, command: str) -> Optional[str]:
        """
        處理指令
        
        Args:
            command: 用戶輸入的指令（以 / 開頭）
        
        Returns:
            - None: 指令已處理完畢
            - "__exit__": 請求退出
            - str: 要執行的提示文本（如 /retry 返回上次輸入）
        """
        parts = command.strip().split()
        name = parts[0].lower()
        args = parts[1:]
        
        # /exit, /quit - 退出
        if name in ("/exit", "/quit"):
            if self.exit_callback:
                self.exit_callback()
                return None
            return "__exit__"
        
        # /help - 顯示幫助
        elif name == "/help":
            self._show_help()
            return None
        
        # /clear - 清空（CLI 下清屏，GUI 下清空對話框）
        elif name == "/clear":
            self._handle_clear()
            return None
        
        # /tools - 列出工具
        elif name == "/tools":
            self._list_tools()
            return None
        
        # /skills - Skills 相關指令
        elif name == "/skills":
            self._handle_skills_command(args)
            return None
        
        # /history - 顯示對話歷史
        elif name == "/history":
            self._show_history(args)
            return None
        
        # /last - 顯示最後的助手回覆
        elif name == "/last":
            self._show_last_reply()
            return None
        
        # /retry - 重新執行最後的輸入
        elif name == "/retry":
            return self._handle_retry()

        # /config - 啟動設定 CLI 菜單（CLI 下同步，GUI 下非同步）
        elif name == "/config":
            try:
                if self.output_callback == print:
                    # CLI: run interactive menu synchronously
                    config_cli.cmd_config_menu()
                else:
                    # GUI: run the CLI menu in a background thread so it doesn't block UI
                    t = threading.Thread(target=config_cli.cmd_config_menu, daemon=True)
                    t.start()
                    self.output_callback("開啟設定選單（在終端中互動）...")
            except Exception as e:
                logger.error(f"Failed to open config menu: {e}")
                self.output_callback(f"無法啟動設定選單: {e}")
            return None

        # /config-web - 開啟設定 Web UI 頁面（GUI 模式下使用 webview，CLI 模式下使用瀏覽器）
        elif name == "/config-web":
            try:
                url = config_webui.ensure_webui_running()
                
                # 檢查是否為 GUI 模式（有 gui_window 且非 None）
                if self.gui_window is not None:
                    # GUI 模式：使用內建 webview
                    self.gui_window.open_config_webview()
                    self.output_callback("已打開配置頁面")
                else:
                    # CLI 模式：使用外部瀏覽器
                    opened = webbrowser.open(url, new=2)
                    if opened:
                        self.output_callback(f"已在瀏覽器開啟設定頁：{url}")
                    else:
                        self.output_callback(f"設定頁位置：{url}（請手動打開）")
            except Exception as e:
                logger.error(f"Failed to open config web UI: {e}")
                self.output_callback(f"無法開啟設定頁: {e}")
            return None
        
        # 未知指令
        else:
            self.output_callback(f"未知指令：{name}\n\n輸入 /help 查看可用指令。")
            return None
    
    def _show_help(self):
        """顯示幫助訊息"""
        help_text = """可用指令：

基本指令：
  /help              顯示此幫助訊息
  /exit, /quit       退出程式
  /clear             清空屏幕/對話框
    /config            開啟文字式設定選單（CLI）或在終端中顯示（GUI）
    /config-web        打開配置頁面（GUI 中使用內建 webview，CLI 中使用瀏覽器）

查詢指令：
  /tools             列出所有可用工具
  /skills [list]     列出所有 skills
  /skills info <name> 顯示 skill 詳細資訊
  /skills test <text> 測試 skill 匹配

對話管理：
  /history [N]       顯示最近 N 輪對話（預設 5）
  /last              顯示最後的助手回覆
  /retry             重新執行最後的輸入

Skills 管理：
  /skills reload     重新載入 skills
"""
        self.output_callback(help_text)
    
    def _handle_clear(self):
        """處理清空指令"""
        # CLI 模式下清屏
        if self.output_callback == print:
            print("\n" * 80)
        else:
            # GUI 模式下通知清空
            self.output_callback("__clear__")
    
    def _list_tools(self):
        """列出所有工具"""
        tools_meta = self.main_agent._get_function_tools()
        if not tools_meta:
            self.output_callback("沒有已註冊的工具。")
        else:
            lines = ["可用工具："]
            for tool_name, tool in tools_meta.items():
                doc = tool.description.splitlines()[0] if tool.description else ""
                lines.append(f"- {tool_name}: {doc}" if doc else f"- {tool_name}")
            self.output_callback("\n".join(lines))
    
    def _handle_skills_command(self, args: list[str]):
        """處理 /skills 子指令"""
        if not args or args[0] == "list":
            self._list_skills()
        elif args[0] == "info":
            self._show_skill_info(args[1:])
        elif args[0] == "test":
            self._test_skill_matching(args[1:])
        elif args[0] == "reload":
            self._reload_skills()
        else:
            self.output_callback(
                f"未知的 skills 指令：{args[0]}\n\n"
                "可用指令：\n"
                "  /skills [list]\n"
                "  /skills info <name>\n"
                "  /skills test <prompt>\n"
                "  /skills reload"
            )
    
    def _list_skills(self):
        """列出所有 skills"""
        if not self.main_agent.skills or self.main_agent.skills.is_empty():
            self.output_callback("沒有已載入的 skills。")
            return
        
        specs = self.main_agent.skills.list_summaries()
        lines = [f"可用 skills（共 {len(specs)} 個）："]
        for spec in specs:
            skill_name = spec.get("name", "")
            desc = spec.get("description", "")
            if desc:
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                lines.append(f"- {skill_name}: {desc}")
            else:
                lines.append(f"- {skill_name}")
        self.output_callback("\n".join(lines))
    
    def _show_skill_info(self, args: list[str]):
        """顯示特定 skill 的詳細資訊"""
        if not args:
            self.output_callback("用法：/skills info <skill-name>")
            return
        
        skill_name = args[0]
        if not self.main_agent.skills or self.main_agent.skills.is_empty():
            self.output_callback("沒有已載入的 skills。")
            return
        
        skill = self.main_agent.skills.get_skill(skill_name)
        if not skill:
            self.output_callback(
                f"找不到 skill：'{skill_name}'\n\n"
                "使用 /skills 查看可用的 skills。"
            )
            return
        
        lines = [
            f"Skill: {skill.name}",
            f"描述: {skill.description}",
            "",
        ]
        
        # 顯示資源
        if skill.resources.has_resources():
            lines.append("資源：")
            resources = skill.resources.list_all()
            if resources.get("scripts"):
                lines.append(f"  Scripts: {', '.join(resources['scripts'])}")
            if resources.get("references"):
                lines.append(f"  References: {', '.join(resources['references'])}")
            if resources.get("assets"):
                lines.append(f"  Assets: {', '.join(resources['assets'])}")
            lines.append("")
        
        # 內容預覽
        preview = skill.content[:500] if len(skill.content) > 500 else skill.content
        lines.append("內容預覽：")
        lines.append("-" * 40)
        lines.append(preview)
        if len(skill.content) > 500:
            lines.append(f"... (還有 {len(skill.content) - 500} 字元)")
        lines.append("-" * 40)
        
        self.output_callback("\n".join(lines))
    
    def _test_skill_matching(self, args: list[str]):
        """測試 skill 匹配"""
        if not args:
            self.output_callback("用法：/skills test <prompt>")
            return
        
        test_prompt = " ".join(args)
        if not self.main_agent.skills or self.main_agent.skills.is_empty():
            self.output_callback("沒有已載入的 skills。")
            return
        
        skills = self.main_agent.skills.find_relevant_skills(test_prompt, max_skills=5)
        if not skills:
            self.output_callback(f"沒有匹配的 skills：'{test_prompt}'")
            return
        
        lines = [
            f"測試提示：'{test_prompt}'",
            f"匹配了 {len(skills)} 個 skill(s)：",
            "",
        ]
        for i, skill in enumerate(skills, 1):
            lines.append(f"{i}. {skill.name}")
            lines.append(f"   {skill.short_description()}")
            lines.append("")
        
        self.output_callback("\n".join(lines))
    
    def _reload_skills(self):
        """重新載入 skills"""
        try:
            from internal.skills_loader import load_skill_registry
            self.main_agent.skills = load_skill_registry()
            count = len(self.main_agent.skills.list_names())
            self.output_callback(f"Skills 已重新載入。載入了 {count} 個 skills。")
        except Exception as e:
            self.output_callback(f"重新載入 skills 失敗：{e}")
    
    def _show_history(self, args: list[str]):
        """顯示對話歷史"""
        limit = 5
        if args and args[0].isdigit():
            limit = max(1, int(args[0]))
        
        if not self.history:
            self.output_callback("尚無對話歷史。")
            return
        
        recent = self.history[-limit:]
        lines = ["對話歷史：", ""]
        for idx, (user_text, assistant_text) in enumerate(recent, start=1):
            lines.append(f"[{idx}] 用戶：{user_text}")
            if assistant_text:
                # 對長回覆進行截斷（僅在顯示歷史時）
                preview = assistant_text[:100] + "..." if len(assistant_text) > 100 else assistant_text
                lines.append(f"[{idx}] 助手：{preview}")
            lines.append("")
        
        self.output_callback("\n".join(lines))
    
    def _show_last_reply(self):
        """顯示最後的助手回覆"""
        if self.last_assistant_reply:
            self.output_callback(self.last_assistant_reply)
        else:
            self.output_callback("尚無助手回覆。")
    
    def _handle_retry(self) -> Optional[str]:
        """處理重試指令"""
        if self.last_user_prompt:
            return self.last_user_prompt
        else:
            self.output_callback("沒有可重試的輸入。")
            return None
    
    def update_last_prompt(self, prompt: str):
        """更新最後的用戶輸入"""
        self.last_user_prompt = prompt
    
    def update_last_reply(self, reply: str):
        """更新最後的助手回覆"""
        self.last_assistant_reply = reply
