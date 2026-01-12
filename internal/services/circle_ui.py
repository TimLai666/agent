import random
import re
import string
import sys

from PySide6.QtCore import Qt, QTimer, QVariantAnimation, QPropertyAnimation, QEasingCurve, Property, QMetaObject, Signal, Slot, QEventLoop
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QKeyEvent

# Convert bare URLs in markdown/plain text into markdown links so QTextBrowser renders them as clickable
import re

def _autolink_markdown(text: str) -> str:
    if not text:
        return text

    # Replace http(s)://... occurrences with [url](url) except when already inside brackets/parentheses/angle brackets
    def repl(m):
        url = m.group(0)
        start = m.start()
        # If immediately preceded by characters that indicate it's already part of a link or HTML, skip
        if start > 0:
            prev = text[start - 1]
            if prev in "([<\"'=":
                return url
        return f'[{url}]({url})'

    return re.sub(r'https?://[^\s<)]+', repl, text)
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from internal.logger import logger


class CommandLineEdit(QLineEdit):
    """支援指令補全和歷史記錄的輸入框"""
    
    # 所有可用的指令
    COMMANDS = [
        "/help",
        "/exit",
        "/quit",
        "/clear",
        "/history",
        "/history 5",
        "/history 10",
        "/last",
        "/retry",
        "/tools",
        "/subagents",
        "/skills",
        "/skills list",
        "/skills info ",
        "/skills test ",
        "/skills reload",
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []  # 指令歷史
        self.history_index = -1  # 當前歷史索引
        
        # 設置自動補全
        self.completer = QCompleter(self.COMMANDS, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setMaxVisibleItems(8)
        
        # 自定義補全器樣式
        popup = self.completer.popup()
        popup.setStyleSheet(
            "QListView {"
            "  background-color: rgba(40, 40, 40, 240);"
            "  color: white;"
            "  border: 1px solid rgba(255, 255, 255, 60);"
            "  border-radius: 8px;"
            "  padding: 4px;"
            "  selection-background-color: rgba(0, 122, 255, 180);"
            "}"
            "QListView::item {"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "}"
            "QListView::item:hover {"
            "  background-color: rgba(255, 255, 255, 30);"
            "}"
        )
        
        self.setCompleter(self.completer)
    
    def keyPressEvent(self, event: QKeyEvent):
        """處理特殊按鍵"""
        # 上箭頭：顯示上一條歷史記錄
        if event.key() == Qt.Key_Up:
            if self.history and self.history_index < len(self.history) - 1:
                self.history_index += 1
                self.setText(self.history[-(self.history_index + 1)])
            event.accept()
            return
        
        # 下箭頭：顯示下一條歷史記錄
        elif event.key() == Qt.Key_Down:
            if self.history_index > 0:
                self.history_index -= 1
                self.setText(self.history[-(self.history_index + 1)])
            elif self.history_index == 0:
                self.history_index = -1
                self.clear()
            event.accept()
            return
        
        # Tab 鍵：觸發補全（如果補全器有建議）
        elif event.key() == Qt.Key_Tab:
            if self.completer.completionCount() > 0:
                # 如果有補全建議，選擇第一個
                self.completer.setCurrentRow(0)
                self.setText(self.completer.currentCompletion())
                # 如果是需要參數的指令，將游標移到末尾
                if self.text().endswith(" "):
                    self.setCursorPosition(len(self.text()))
            event.accept()
            return
        
        # 其他按鍵：重置歷史索引
        if event.key() not in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab):
            self.history_index = -1
        
        # 調用父類處理
        super().keyPressEvent(event)
    
    def add_to_history(self, text: str):
        """添加到歷史記錄"""
        if text and text.strip():
            # 避免重複
            if not self.history or self.history[-1] != text:
                self.history.append(text)
                # 限制歷史記錄數量
                if len(self.history) > 100:
                    self.history = self.history[-100:]
            self.history_index = -1


class Arc:
    colors = list(string.ascii_lowercase[0:6] + string.digits)

    shades_of_green = [
        "#32CD32",
        "#CAE00D",
        "#9EFD38",
        "#568203",
        "#93C572",
        "#8DB600",
        "#708238",
        "#556B2F",
        "#014421",
        "#98FB98",
        "#7CFC00",
        "#4F7942",
        "#009E60",
        "#00FF7F",
        "#00FA9A",
        "#177245",
        "#2E8B57",
        "#3CB371",
        "#A7F432",
        "#123524",
        "#5E8C31",
        "#90EE90",
        "#03C03C",
        "#66FF00",
        "#006600",
        "#D9E650",
    ]

    def __init__(self):
        self.diameter = random.randint(40, 110)
        color_hex = random.choice(Arc.shades_of_green)
        self.color = QColor(color_hex)
        self.color.setAlpha(150)
        self.span = random.randint(60, 180)
        self.direction = 1 if random.randint(10, 15) % 2 == 0 else -1
        self.startAngle = random.randint(0, 360)
        self.step = random.randint(100, 300)


class Circle:
    def __init__(self):
        self.diameter = 100
        self.color_index = 0

    def get_color(self, animation_progress):
        # 根據動畫進度選擇顏色
        progress = (animation_progress / 360) * len(Arc.shades_of_green)
        current_index = int(progress) % len(Arc.shades_of_green)
        next_index = (current_index + 1) % len(Arc.shades_of_green)

        # 計算兩個顏色之間的插值比例
        t = progress - int(progress)  # 0.0 到 1.0 之間的小數部分

        # 取得當前和下一個顏色
        current_color = QColor(Arc.shades_of_green[current_index])
        next_color = QColor(Arc.shades_of_green[next_index])

        # 在兩個顏色之間插值
        r = int(current_color.red() + (next_color.red() - current_color.red()) * t)
        g = int(
            current_color.green() + (next_color.green() - current_color.green()) * t
        )
        b = int(current_color.blue() + (next_color.blue() - current_color.blue()) * t)

        return QColor(r, g, b).name()


class SpinnerLabel(QLabel):
    """Lightweight text-spinner label that cycles frames with a QTimer."""

    def __init__(self, parent=None, base_text: str = ""):
        super().__init__(parent)
        self.base_text = base_text
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._idx = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setText(base_text)
        self.setVisible(False)
        self.setStyleSheet("color: #A0A0A0; border: none; background: transparent;")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

    def _tick(self):
        try:
            self.setText(
                f"{self.frames[self._idx % len(self.frames)]} {self.base_text}"
            )
            self._idx += 1
        except RuntimeError:
            # C++ object gone; ignore
            pass

    def set_base_text(self, text: str):
        self.base_text = text
        if not self._timer.isActive():
            self.setText(text)

    def start(self):
        if not self._timer.isActive():
            self._idx = 0
            self.setVisible(True)
            self._timer.start(100)

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
        self.setVisible(False)
        self.setText(self.base_text)


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: str, parent=None, is_active=False):
        super().__init__(parent)
        self.base_title = title
        self.is_active = is_active
        self._content_height = 0
        self._animation = None

        # Title button + spinner on the left
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(6)

        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(is_active)  # Auto-expand if active
        self.button.setArrowType(Qt.DownArrow if is_active else Qt.RightArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setStyleSheet(
            "QToolButton { color: #007AFF; font-weight: bold; border: none; background: transparent; padding: 2px; }"
            "QToolButton:hover { color: #329DFF; }"
        )
        self.button.clicked.connect(self.toggle)

        self.spinner = SpinnerLabel(self, base_text=title)
        if is_active:
            self.spinner.start()

        head_layout.addWidget(self.button)
        head_layout.addWidget(self.spinner)
        head_layout.addStretch(1)

        # Content area
        self.content = QTextBrowser()
        # If the section is active but empty, provide a small placeholder so the section is visible
        if is_active and not content.strip():
            self.content.setHtml("<i>Waiting for output...</i>")
        else:
            self.content.setMarkdown(_autolink_markdown(content))
        self.content.setOpenExternalLinks(True)
        self.content.setStyleSheet(
            "background: transparent; color: #F0F0F0; font-size: 13px; border-radius: 10px; padding: 8px; border: none;"
        )
        self.content.setFrameShape(QFrame.NoFrame)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Ensure content doesn't scroll internally and compute size changes
        self.content.document().setDocumentMargin(0)

        def adjust():
            try:
                if self.content is None:
                    return
                h = self.content.document().size().height()
                # Ensure a sensible minimum height so active blocks are visible
                min_h = 28 if self.is_active else 10
                self.content.setFixedHeight(max(int(h) + 16, min_h))
                if self.layout():
                    self.layout().activate()
            except RuntimeError:
                pass

        # Listen to both text and document changes
        try:
            self.content.textChanged.connect(adjust)
        except Exception:
            pass
        try:
            self.content.document().contentsChanged.connect(adjust)
        except Exception:
            pass
        QTimer.singleShot(0, adjust)
        # Allow clicking links as well as text selection
        self.content.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.content.setVisible(is_active)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(head)
        layout.addWidget(self.content)

    def get_content_height(self):
        """獲取內容區域的高度（用於動畫）"""
        return self._content_height

    def set_content_height(self, height):
        """設置內容區域的高度（用於動畫）"""
        self._content_height = height
        self.content.setFixedHeight(int(height))

    contentHeight = Property(int, get_content_height, set_content_height)

    def update_content(self, new_content: str):
        """更新區塊內容並重新計算高度"""
        if not new_content.strip() and self.is_active:
            self.content.setHtml("<i>Waiting for output...</i>")
        else:
            self.content.setMarkdown(_autolink_markdown(new_content))
        
        # 強制重新計算高度
        QTimer.singleShot(0, self._recalculate_height)
        QTimer.singleShot(50, self._recalculate_height)  # 再次確認
    
    def _recalculate_height(self):
        """重新計算內容高度"""
        try:
            if self.content is None:
                return
            self.content.document().adjustSize()
            h = self.content.document().size().height()
            min_h = 28 if self.is_active else 10
            new_height = max(int(h) + 16, min_h)
            self._content_height = new_height
            self.content.setFixedHeight(new_height)
            if self.layout():
                self.layout().activate()
            # 通知父容器更新
            if self.parent():
                self.parent().updateGeometry()
        except RuntimeError:
            pass

    def set_active(self, active: bool, animate: bool = True):
        """設置區塊的活動狀態，可選擇是否使用動畫"""
        if self.is_active == active:
            return
        
        self.is_active = active
        
        if active:
            self.spinner.start()
            self.button.setChecked(True)
            self.button.setArrowType(Qt.DownArrow)
            if not self.content.toPlainText().strip():
                self.content.setHtml("<i>Waiting for output...</i>")
            
            self.content.document().adjustSize()
            target_height = max(int(self.content.document().size().height()) + 16, 28)
            
            if animate and self._content_height == 0:
                self.content.setVisible(True)
                self._animate_height(0, target_height)
            else:
                self._content_height = target_height
                self.content.setFixedHeight(target_height)
                self.content.setVisible(True)
        else:
            # 當標籤關閉時，停止spinner並自動收合區塊
            self.spinner.stop()
            content_text = self.content.toPlainText().strip()
            has_real_content = content_text and "Waiting for" not in content_text
            
            # 無論是否有內容，都自動收合區塊
            if has_real_content:
                # 有內容時，使用動畫收合
                current_height = self._content_height if self._content_height > 0 else self.content.height()
                if animate and current_height > 0:
                    self._animate_height(current_height, 0, on_finish=lambda: self._finish_collapse())
                else:
                    self._finish_collapse()
            else:
                # 沒有實際內容時，也要收合
                if animate and self._content_height > 0:
                    self._animate_height(self._content_height, 0, on_finish=lambda: self._finish_collapse())
                else:
                    self._finish_collapse()

    def toggle(self):
        """切換區塊展開/收起狀態（用戶手動點擊）"""
        expanded = self.button.isChecked()
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        
        if expanded:
            # 展開
            self.content.document().adjustSize()
            target_height = max(int(self.content.document().size().height()) + 16, 28)
            self._animate_height(0, target_height)
            self.content.setVisible(True)
        else:
            # 收起
            current_height = self._content_height if self._content_height > 0 else self.content.height()
            self._animate_height(current_height, 0, on_finish=lambda: self.content.setVisible(False))

    def _animate_height(self, start_height: int, end_height: int, on_finish=None):
        """創建高度變化的動畫"""
        if self._animation and self._animation.state() == QPropertyAnimation.Running:
            self._animation.stop()
        
        self._animation = QPropertyAnimation(self, b"contentHeight")
        self._animation.setDuration(250)
        self._animation.setStartValue(start_height)
        self._animation.setEndValue(end_height)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        
        if on_finish:
            self._animation.finished.connect(on_finish)
        
        self._animation.start()

    def _finish_collapse(self):
        """完成收起動作"""
        self.button.setChecked(False)
        self.button.setArrowType(Qt.RightArrow)
        self.content.setVisible(False)
        self._content_height = 0


class OutputBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_height = 500
        self.preferred_width = 400
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "OutputBubble { "
            "background-color: rgba(30, 30, 30, 210); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 50); "
            "border-radius: 20px;"
            "}"
        )

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollBar:vertical { border: none; background: transparent; width: 4px; margin: 4px 0 4px 0; } "
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40); min-height: 20px; border-radius: 2px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.scroll.setWidget(self.container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

    def content_height(self) -> int:
        return int(self.container.sizeHint().height())

    def set_content(self, text: str):
        for i in reversed(range(self.layout.count())):
            item = self.layout.takeAt(i)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        segments = self._parse_segments(text or "")
        for kind, content in segments:
            if not content.strip():
                continue
            if kind == "normal":
                browser = QTextBrowser()
                browser.setMarkdown(_autolink_markdown(content))
                browser.setOpenExternalLinks(True)
                browser.setStyleSheet(
                    "background: transparent; color: white; font-size: 14px;"
                )
                browser.setFrameShape(QFrame.NoFrame)
                browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                # Allow clicking links as well as text selection
                browser.setTextInteractionFlags(Qt.TextBrowserInteraction)
                browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                self.layout.addWidget(browser)
            else:
                title = "Tool execution" if kind == "tool" else "Discussion"
                section = CollapsibleSection(title, content)
                self.layout.addWidget(section)

        self.layout.addStretch(1)

    def _parse_segments(self, text: str):
        tags = {
            "<tool-execution>": "tool",
            "</tool-execution>": "tool",
            "<discussion>": "discussion",
            "</discussion>": "discussion",
        }
        open_tags = {"<tool-execution>", "<discussion>"}
        close_tags = {"</tool-execution>", "</discussion>"}
        segments = []
        stack = ["normal"]
        pos = 0

        def add_segment(kind, chunk, active=False):
            # If there's no content and it's not explicitly marked active, skip.
            if not chunk and not active:
                return
            if segments and segments[-1][0] == kind:
                # Preserve existing active state if previously set.
                existing_active = segments[-1][2] if len(segments[-1]) > 2 else False
                segments[-1] = (
                    kind,
                    segments[-1][1] + chunk,
                    existing_active or active,
                )
            else:
                segments.append((kind, chunk, active))

        while pos < len(text):
            next_pos = -1
            next_tag = ""
            for tag in tags:
                idx = text.find(tag, pos)
                if idx == -1:
                    continue
                if next_pos == -1 or idx < next_pos:
                    next_pos = idx
                    next_tag = tag
            if next_pos == -1:
                add_segment(stack[-1], text[pos:])
                break
            if next_pos > pos:
                add_segment(stack[-1], text[pos:next_pos])
            if next_tag in open_tags:
                stack.append(tags[next_tag])
            elif next_tag in close_tags and len(stack) > 1:
                stack.pop()
            pos = next_pos + len(next_tag)

        return segments


class SiriResponseBubble(QWidget):
    SPINNER_PATTERN = re.compile(
        r"^\s*(?:[-*>\u2022]\s*)?(?:still\s+|currently\s+)?(?P<status>thinking|listening)(?:\s*(?:\.{3,}|…))?\s*$",
        re.IGNORECASE,
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_height = 600
        self.preferred_width = 420
        self.setAttribute(Qt.WA_StyledBackground, True)
        # 極致磨砂感：強制背景不繼承並移除內部所有預設邊框
        self.setStyleSheet(
            "SiriResponseBubble { "
            "background-color: rgba(20, 20, 20, 205); "
            "border: 1px solid rgba(255, 255, 255, 35); "
            "border-radius: 30px;"
            "} "
            "QTextBrowser { background: transparent; border: none; } "
            "QScrollArea { background: transparent; border: none; } "
            "QWidget#container { background: transparent; border: none; }"
        )

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollBar:vertical { border: none; background: transparent; width: 3px; margin: 12px 0 12px 0; } "
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40); min-height: 25px; border-radius: 1.5px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        self.container = QWidget()
        self.container.setObjectName("container")
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(22, 22, 22, 22)
        self.layout.setSpacing(15)
        self.scroll.setWidget(self.container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

    def _refresh_layout_metrics(self, process_events: bool = True) -> None:
        try:
            self.layout.activate()
            self.container.adjustSize()
            if self.scroll.widget():
                self.scroll.widget().adjustSize()
            if process_events:
                QApplication.processEvents()
        except Exception:
            pass

    def _split_normal_segments(self, content: str):
        segments = []
        buffer = []
        lines = content.splitlines(keepends=True)
        total = len(lines)
        for idx, line in enumerate(lines):
            stripped = line.strip()
            match = self.SPINNER_PATTERN.match(stripped)
            if match:
                remaining = "".join(lines[idx + 1 :]).strip()
                if remaining:
                    buffer.append(line)
                    continue
                chunk = "".join(buffer)
                if chunk.strip():
                    segments.append(("text", chunk.rstrip("\n")))
                buffer = []
                status = match.group("status")
                fallback_text = stripped
                if not fallback_text:
                    fallback_text = (
                        f"{status.capitalize()}..." if status else "Thinking..."
                    )
                segments.append(("spinner", fallback_text))
            else:
                buffer.append(line)
        if buffer:
            chunk = "".join(buffer)
            if chunk.strip():
                segments.append(("text", chunk))
        if not segments and content.strip():
            segments.append(("text", content))
        return segments

    def content_height(self) -> int:
        self._refresh_layout_metrics()
        container_hint = self.container.sizeHint().height()
        layout_hint = self.layout.sizeHint().height()
        return int(max(container_hint, layout_hint))

    def set_content(self, text: str):
        # Check if we should update existing sections instead of recreating
        existing_sections = {}
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, CollapsibleSection):
                title = widget.base_title
                existing_sections[title] = widget
        
        # Parse new segments
        segments = self._parse_segments(text or "")
        
        # Track which sections we've seen in this update
        seen_sections = set()
        
        # Clear ALL widgets to rebuild cleanly
        for i in reversed(range(self.layout.count())):
            item = self.layout.takeAt(i)
            widget = item.widget()
            if widget is not None and not isinstance(widget, CollapsibleSection):
                widget.setParent(None)
                widget.deleteLater()

        # Process segments
        for kind, content, is_active in segments:
            if kind == "normal":
                sub_segments = self._split_normal_segments(content)
                if not sub_segments:
                    continue
                for sub_kind, sub_content in sub_segments:
                    if sub_kind == "spinner":
                        sub_content = _autolink_markdown(sub_content)
                        container = QWidget()
                        h = QHBoxLayout(container)
                        h.setContentsMargins(0, 0, 0, 0)
                        h.setSpacing(8)
                        spinner = SpinnerLabel(container, base_text="")
                        spinner.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                        spinner.start()
                        label = QTextBrowser(container)
                        label.setLineWrapMode(QTextEdit.WidgetWidth)
                        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                        label.setMarkdown(_autolink_markdown(sub_content))
                        label.setOpenExternalLinks(True)
                        label.setStyleSheet(
                            "background: transparent; border: none; color: #FFFFFF; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; font-size: 16px; line-height: 1.6;"
                        )
                        label.setFrameShape(QFrame.NoFrame)
                        label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        label.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        # Allow clicking links inside spinner labels
                        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
                        label.document().setDocumentMargin(0)

                        def update_spinner_label_height(b=label):
                            try:
                                # 強制更新文件布局
                                b.document().adjustSize()
                                height = b.document().size().height()
                                min_height = max(int(height) + 20, 40)
                                b.setMinimumHeight(min_height)
                                b.setMaximumHeight(min_height)
                            except RuntimeError:
                                pass

                        try:
                            label.textChanged.connect(update_spinner_label_height)
                            label.document().contentsChanged.connect(update_spinner_label_height)
                        except Exception:
                            pass
                        QTimer.singleShot(0, update_spinner_label_height)
                        h.addWidget(spinner)
                        h.setAlignment(spinner, Qt.AlignTop)
                        h.addWidget(label, 1)
                        h.addStretch(1)
                        self.layout.addWidget(container)
                    else:
                        if not sub_content.strip():
                            continue
                        browser = QTextBrowser()
                        browser.setMarkdown(_autolink_markdown(sub_content))
                        browser.setOpenExternalLinks(True)
                        browser.setLineWrapMode(QTextEdit.WidgetWidth)
                        browser.setStyleSheet(
                            "QTextBrowser { color: #FFFFFF; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; font-size: 16px; line-height: 1.6; }"
                        )
                        browser.setFrameShape(QFrame.NoFrame)
                        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        # Allow clicking links inside sub-sections
                        browser.setTextInteractionFlags(Qt.TextBrowserInteraction)
                        browser.document().setDocumentMargin(0)
                        browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

                        def update_browser_height(b=browser):
                            try:
                                # 強制更新文件布局
                                b.document().adjustSize()
                                # 獲取文檔實際高度
                                doc_size = b.document().size()
                                h2 = doc_size.height()
                                # 設置最小高度並添加額外的padding
                                min_height = max(int(h2) + 20, 40)
                                b.setMinimumHeight(min_height)
                                b.setMaximumHeight(min_height)
                            except RuntimeError:
                                pass

                        try:
                            browser.textChanged.connect(update_browser_height)
                            browser.document().contentsChanged.connect(update_browser_height)
                        except Exception:
                            pass
                        QTimer.singleShot(0, update_browser_height)
                        self.layout.addWidget(browser)
            elif kind in ("tool", "discussion"):
                title = "🛠️ Tool execution" if kind == "tool" else "💭 Discussion"
                seen_sections.add(title)
                
                # 如果section已存在，更新其內容
                if title in existing_sections:
                    section = existing_sections[title]
                    # 更新內容
                    content_for_section = content if content.strip() else "<i>Waiting for results...</i>"
                    section.update_content(content_for_section)
                    section.set_active(is_active)
                    # 確保section在layout中
                    self.layout.addWidget(section)
                else:
                    # 創建新的section
                    content_for_section = content
                    if is_active and not content.strip():
                        content_for_section = "<i>Waiting for results...</i>"
                    section = CollapsibleSection(
                        title, content_for_section, is_active=is_active
                    )
                    self.layout.addWidget(section)
                    existing_sections[title] = section
        
        # 移除不再需要的sections
        for title, section in list(existing_sections.items()):
            if title not in seen_sections:
                section.setParent(None)
                section.deleteLater()

        self.layout.addStretch(1)

        self._refresh_layout_metrics()
        try:
            self.scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass
        QTimer.singleShot(0, lambda: self._refresh_layout_metrics())

    def _parse_segments(self, text: str):
        tags = {
            "<tool-execution>": "tool",
            "</tool-execution>": "tool",
            "<discussion>": "discussion",
            "</discussion>": "discussion",
        }

        open_tags = {"<tool-execution>", "<discussion>"}

        close_tags = {"</tool-execution>", "</discussion>"}

        segments = []  # List of (kind, content, is_active)

        stack = ["normal"]

        pos = 0

        def add_segment(kind: str, chunk: str, active: bool = False) -> None:
            if not chunk and not active:
                return

            if segments and segments[-1][0] == kind:
                prev_kind, prev_chunk, prev_active = segments[-1]
                segments[-1] = (prev_kind, prev_chunk + chunk, prev_active or active)
            else:
                segments.append((kind, chunk, active))

        while pos < len(text):
            next_pos = None
            next_tag = None
            for tag in tags:
                idx = text.find(tag, pos)

                if idx == -1:
                    continue

                if next_pos is None or idx < next_pos:
                    next_pos = idx

                    next_tag = tag

            if next_pos is None:
                add_segment(stack[-1], text[pos:])

                break

            if next_pos > pos:
                add_segment(stack[-1], text[pos:next_pos])

            if next_tag in open_tags:
                new_kind = tags[next_tag]

                stack.append(new_kind)

                add_segment(new_kind, "", True)

            elif next_tag in close_tags and len(stack) > 1:
                closing_kind = stack.pop()
                for idx in range(len(segments) - 1, -1, -1):
                    seg_kind, seg_chunk, seg_active = segments[idx]
                    if seg_kind == closing_kind:
                        segments[idx] = (seg_kind, seg_chunk, False)
                        break
            pos = next_pos + len(next_tag)

        if len(stack) > 1:
            current_kind = stack[-1]
            if segments and segments[-1][0] == current_kind:
                seg_kind, seg_chunk, seg_active = segments[-1]

                segments[-1] = (seg_kind, seg_chunk, True)
            else:
                segments.append((current_kind, "", True))

        return segments


class ArcWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.arcs = [Arc() for i in range(20)]
        self.circle = Circle()  # 新增這行
        self.startAnime()

    def initUI(self):
        # self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 添加這行
        self.setStyleSheet("background-color:transparent;")  # 改為透明

    def startAnime(self):
        self.anim = QVariantAnimation(self, duration=10000)
        self.anim.setStartValue(0)
        self.anim.setEndValue(360)
        self.anim.valueChanged.connect(self.update)
        self.anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 取得圓圈顏色
        circle_color = self.circle.get_color(self.anim.currentValue())

        # 計算球球位置 - 固定在底部往上150px的位置
        ball_center_x = self.width() / 2
        # 從父視窗獲取固定位置參數，如果沒有則使用預設值
        parent = self.parent()
        if parent and hasattr(parent, 'BALL_CENTER_FROM_BOTTOM'):
            ball_center_y = self.height() - parent.BALL_CENTER_FROM_BOTTOM
        else:
            ball_center_y = self.height() - 150  # 預設值

        # 繪製多層底層發光圓 (Siri 般的層次感發光效果)
        # 第一層：核心高亮
        core_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter / 4
        )
        c_core = QColor(circle_color)
        c_core.setAlpha(180)
        core_grad.setColorAt(0, c_core)
        core_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(core_grad)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter / 2),
            int(ball_center_y - self.circle.diameter / 2),
            int(self.circle.diameter),
            int(self.circle.diameter),
        )

        # 第二層：中等擴散（縮小範圍，降低強度）
        mid_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter / 1.5
        )
        c_mid = QColor(circle_color)
        c_mid.setAlpha(80)
        mid_grad.setColorAt(0, c_mid)
        mid_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(mid_grad)
        # 縮小中層的繪製範圍以配合較小的漸層半徑
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter * (4.0 / 3.0) / 2),
            int(ball_center_y - self.circle.diameter * (4.0 / 3.0) / 2),
            int(self.circle.diameter * 4.0 / 3.0),
            int(self.circle.diameter * 4.0 / 3.0),
        )

        # 第三層：廣域外溢（大幅縮小外溢範圍，並降低透明度）
        outer_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter * 1.0
        )
        c_outer = QColor(circle_color)
        c_outer.setAlpha(20)
        outer_grad.setColorAt(0, c_outer)
        outer_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(outer_grad)
        # outer 使用 2x radius 的繪製範圍
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter),
            int(ball_center_y - self.circle.diameter),
            int(self.circle.diameter * 2),
            int(self.circle.diameter * 2),
        )

        # 繪製旋轉的圓弧
        for arc in self.arcs:
            pen = QPen(arc.color, 4, Qt.SolidLine)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(
                int(ball_center_x - arc.diameter / 2),
                int(ball_center_y - arc.diameter / 2),
                int(arc.diameter),
                int(arc.diameter),
                int(
                    self.anim.currentValue() * 16 * arc.direction + arc.startAngle * 100
                ),
                int(arc.span * 16),
            )

        if self.anim.currentValue() == 360:
            self.startAnime()


class MainWindow(QMainWindow):
    # 信号：请求显示确认对话框
    confirm_requested = Signal(str, str, object)  # message, default_choice, result_container
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Assistant")
        # 固定視窗大小
        self.FIXED_WIDTH = 460
        self.FIXED_HEIGHT = 800
        self.setGeometry(100, 100, self.FIXED_WIDTH, self.FIXED_HEIGHT)
        self.setFixedSize(self.FIXED_WIDTH, self.FIXED_HEIGHT)
        self.arcWidget = ArcWidget()
        # Essential for translucency and frameless, and always on top
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCentralWidget(self.arcWidget)

        self.old_pos = None  # 初始化拖拽位置
        self.input_callback = None  # 回調函數，用於處理用戶輸入
        
        # 固定球的位置參數（球心在底部往上130px，縮小與輸入框的距離）
        self.BALL_CENTER_FROM_BOTTOM = 130
        # 固定輸入框的位置（距離底部40px，使輸入框上移，與球更接近）
        self.INPUT_FROM_BOTTOM = 40
        self.INPUT_HEIGHT = 45

        # 移除右上角關閉按鈕以簡化 UI（由視窗系統或快捷鍵關閉）

        # 創建講話框 - 改用新設計的 SiriResponseBubble
        self.speech_bubble = SiriResponseBubble()
        self.speech_bubble.setParent(self)
        self.speech_bubble.setFixedSize(220, 160)
        self.speech_bubble.show()  # 初始顯示

        # 創建輸入區域
        self.input_container = QWidget(self)
        self.input_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.input_layout = QHBoxLayout(self.input_container)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(5)

        # 使用自定義的 CommandLineEdit 替代 QLineEdit
        self.input_field = CommandLineEdit()
        self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
        self.input_field.setStyleSheet(
            "QLineEdit { "
            "background-color: rgba(50, 50, 50, 220); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 60); "
            "border-radius: 15px; "
            "padding: 8px 12px; "
            "}"
        )
        self.input_field.returnPressed.connect(self.on_input_submitted)

        self.voice_button = QPushButton("🎤")
        self.voice_button.setFixedSize(35, 35)
        self.voice_button.setStyleSheet(
            "QPushButton { "
            "background-color: rgba(70, 70, 70, 180); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 40); "
            "border-radius: 17px; "
            "font-size: 16px; "
            "}"
            "QPushButton:hover { background-color: rgba(100, 100, 100, 220); }"
        )
        self.voice_button.clicked.connect(self.on_voice_requested)

        self.send_button = QPushButton("發送")
        self.send_button.setFixedSize(60, 35)
        self.send_button.setStyleSheet(
            "QPushButton { "
            "background-color: #007AFF; "
            "color: white; "
            "border: none; "
            "border-radius: 15px; "
            "font-weight: bold; "
            "}"
            "QPushButton:hover { background-color: #0063CC; }"
        )
        self.send_button.clicked.connect(self.on_input_submitted)

        self.input_layout.addWidget(self.voice_button)
        self.input_layout.addWidget(self.input_field)
        self.input_layout.addWidget(self.send_button)

        self.input_container.hide()  # 初始隱藏

        self._pending_geometry_refresh = False
        
        # 连接确认信号到槽
        self.confirm_requested.connect(self._handle_confirm_request)

    def set_input_callback(self, callback):
        """設置輸入回調函數"""
        self.input_callback = callback

    @Slot(str, str, object)
    def _handle_confirm_request(self, message: str, default_choice: str, result_container: object):
        """
        槽函数：在主线程中处理确认请求
        """
        try:
            logger.info(f"[主线程] Creating ConfirmDialog for: {message[:50]}...")
            dialog = ConfirmDialog(message, default_choice, parent=self)
            result_container.result = dialog.get_result()
            logger.info(f"[主线程] Dialog result: {result_container.result}")
        except Exception as e:
            logger.error(f"[主线程] Error in _handle_confirm_request: {e}", exc_info=True)
        finally:
            # 退出事件循环
            if hasattr(result_container, 'loop'):
                result_container.loop.quit()
    
    def show_confirm_dialog(self, message: str, default_choice: str = '') -> bool:
        """
        顯示確認對話框（線程安全）
        使用信号-槽机制和 QEventLoop 确保对话框在主线程中创建和显示
        """
        logger.info(f"[工作线程] show_confirm_dialog called: {message[:50]}...")
        
        # 使用简单的对象来存储结果和事件循环
        class ResultContainer:
            def __init__(self):
                self.result = False
                self.loop = None
        
        result_container = ResultContainer()
        
        # 创建事件循环用于等待
        result_container.loop = QEventLoop()
        
        # 发送信号（Qt 会自动调度到主线程）
        logger.info("[工作线程] Emitting confirm_requested signal...")
        self.confirm_requested.emit(message, default_choice, result_container)
        
        # 运行事件循环，直到槽函数调用 loop.quit()
        logger.info("[工作线程] Starting event loop...")
        result_container.loop.exec()
        
        logger.info(f"[工作线程] Dialog closed, returning: {result_container.result}")
        return result_container.result

    def on_input_submitted(self):
        """處理文字輸入提交"""
        text = self.input_field.text().strip()
        if text and self.input_callback:
            # 添加到歷史記錄
            if isinstance(self.input_field, CommandLineEdit):
                self.input_field.add_to_history(text)
            self.input_field.clear()
            self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
            self.input_callback(text)

    def on_voice_requested(self):
        """處理語音請求"""
        if self.input_callback:
            self.input_callback(None)  # None 表示使用語音輸入

    # --- Mouse Events for dragging the window ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        self.old_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # 雙擊切換輸入框顯示/隱藏
        if self.input_container.isVisible():
            self.input_container.hide()
        else:
            # 設置輸入框位置（固定在視窗底部）
            input_width = min(self.FIXED_WIDTH - 40, 500)
            self.input_container.setGeometry(
                (self.FIXED_WIDTH - input_width) // 2,
                self.FIXED_HEIGHT - self.INPUT_HEIGHT - self.INPUT_FROM_BOTTOM,
                input_width,
                self.INPUT_HEIGHT,
            )
            self.input_container.show()
        event.accept()

    def update_speech_bubble(self, text):
        """更新對話框內容，輸出框疊到球的上方一半"""
        self.speech_bubble.set_content(text)

        # Process events to allow layout updates before measuring
        QApplication.processEvents()

        # 計算氣泡大小
        padding = 60
        bubble_width = min(max(self.speech_bubble.preferred_width, 240), self.FIXED_WIDTH - 40)
        
        # 計算內容需要的高度
        needed_height = self.speech_bubble.content_height() + padding
        # 氣泡最大高度限制
        max_bubble_height = self.FIXED_HEIGHT - 200
        bubble_height = min(
            max(needed_height, 80),  # 最小高度改為80
            max_bubble_height,
        )
        
        self.speech_bubble.setFixedSize(bubble_width, bubble_height)
        
        # Force synchronous layout updates
        try:
            self.speech_bubble.layout.activate()
            self.speech_bubble.container.adjustSize()
            QApplication.processEvents()
        except Exception:
            pass



        # 計算氣泡位置：疊到球的一半
        window_center_x = self.FIXED_WIDTH // 2
        # 球心位於底部往上BALL_CENTER_FROM_BOTTOM的位置
        ball_center_y = self.FIXED_HEIGHT - self.BALL_CENTER_FROM_BOTTOM
        
        # 氣泡只疊到球的一半（氣泡下邊緣對齊球心）
        bubble_x = window_center_x - bubble_width // 2
        bubble_y = ball_center_y - bubble_height
        
        # 確保氣泡不會超出視窗邊界
        bubble_x = max(10, min(bubble_x, self.FIXED_WIDTH - bubble_width - 10))
        bubble_y = max(20, min(bubble_y, self.FIXED_HEIGHT - bubble_height - 80))

        # 設置講話框位置
        self.speech_bubble.move(bubble_x, bubble_y)
        self.speech_bubble.show()

        # 更新輸入容器位置（固定在視窗底部）
        if self.input_container.isVisible():
            input_width = min(self.FIXED_WIDTH - 40, 500)
            self.input_container.setGeometry(
                (self.FIXED_WIDTH - input_width) // 2,
                self.FIXED_HEIGHT - self.INPUT_HEIGHT - self.INPUT_FROM_BOTTOM,
                input_width,
                self.INPUT_HEIGHT,
            )
            self.input_container.show()


class ConfirmDialog(QDialog):
    """確認對話框，用於工具執行確認"""
    
    def __init__(self, message: str, default_choice: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle("工具執行確認")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        # 設置樣式
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
                border-radius: 10px;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px;
            }
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #329DFF;
            }
            QPushButton:pressed {
                background-color: #0051D5;
            }
            QPushButton#cancelButton {
                background-color: #5a5a5a;
            }
            QPushButton#cancelButton:hover {
                background-color: #6a6a6a;
            }
        """)
        
        # 創建佈局
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 訊息標籤
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(message_label)
        
        # 按鈕區域
        button_box = QDialogButtonBox()
        
        yes_button = button_box.addButton("允許", QDialogButtonBox.AcceptRole)
        no_button = button_box.addButton("拒絕", QDialogButtonBox.RejectRole)
        no_button.setObjectName("cancelButton")
        
        # 根據默認選擇設置默認按鈕
        if default_choice.upper() == 'Y':
            yes_button.setDefault(True)
            yes_button.setFocus()
        elif default_choice.upper() == 'N':
            no_button.setDefault(True)
            no_button.setFocus()
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(button_box)
        
        self.result_value = False
    
    def get_result(self) -> bool:
        """顯示對話框並返回結果"""
        result = self.exec()
        return result == QDialog.Accepted


if __name__ == "__main__":
    app = QApplication(sys.argv)

    mainWindow = MainWindow()
    mainWindow.show()

    app.exec()
