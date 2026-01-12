import random
import re
import string
import sys

from PySide6.QtCore import Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
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
            self.content.setMarkdown(content)
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
        self.content.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.content.setVisible(is_active)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(head)
        layout.addWidget(self.content)

    def set_active(self, active: bool):
        self.is_active = active
        if active:
            self.spinner.start()
            self.button.setChecked(True)
            self.button.setArrowType(Qt.DownArrow)
            # If the content was empty, restore placeholder so the block remains visible
            if not self.content.toPlainText().strip():
                self.content.setHtml("<i>Waiting for output...</i>")
            self.content.setVisible(True)
            QTimer.singleShot(
                0,
                lambda: self.content.setFixedHeight(
                    max(self.content.document().size().height() + 16, 28)
                ),
            )
        else:
            self.spinner.stop()
            self.button.setChecked(False)
            self.button.setArrowType(Qt.RightArrow)
            self.content.setVisible(False)

    def toggle(self):
        expanded = self.button.isChecked()
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)


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
                browser.setMarkdown(content)
                browser.setOpenExternalLinks(True)
                browser.setStyleSheet(
                    "background: transparent; color: white; font-size: 14px;"
                )
                browser.setFrameShape(QFrame.NoFrame)
                browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                browser.setTextInteractionFlags(
                    Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
                )
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
        # Clear existing widgets
        for i in reversed(range(self.layout.count())):
            item = self.layout.takeAt(i)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        segments = self._parse_segments(text or "")
        for kind, content, is_active in segments:
            # If there's no content and it's not an active block, skip
            if kind == "normal":
                sub_segments = self._split_normal_segments(content)
                if not sub_segments:
                    continue
                for sub_kind, sub_content in sub_segments:
                    if sub_kind == "spinner":
                        container = QWidget()
                        h = QHBoxLayout(container)
                        h.setContentsMargins(0, 0, 0, 0)
                        h.setSpacing(8)
                        spinner = SpinnerLabel(container, base_text="")
                        spinner.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                        spinner.start()
                        label = QTextBrowser(container)
                        label.setLineWrapMode(QTextEdit.WidgetWidth)
                        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                        label.setMarkdown(sub_content)
                        label.setOpenExternalLinks(True)
                        label.setStyleSheet(
                            "background: transparent; border: none; color: #FFFFFF; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; font-size: 16px; line-height: 1.6;"
                        )
                        label.setFrameShape(QFrame.NoFrame)
                        label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        label.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        label.document().setDocumentMargin(0)

                        def update_spinner_label_height(b=label):
                            try:
                                height = b.document().size().height()
                                b.setFixedHeight(max(int(height) + 10, 24))
                            except RuntimeError:
                                pass

                        try:
                            label.textChanged.connect(update_spinner_label_height)
                        except Exception:
                            pass
                        update_spinner_label_height()
                        h.addWidget(spinner)
                        h.setAlignment(spinner, Qt.AlignTop)
                        h.addWidget(label, 1)
                        h.addStretch(1)
                        self.layout.addWidget(container)
                    else:
                        if not sub_content.strip():
                            continue
                        browser = QTextBrowser()
                        browser.setMarkdown(sub_content)
                        browser.setOpenExternalLinks(True)
                        browser.setStyleSheet(
                            "QTextBrowser { color: #FFFFFF; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; font-size: 16px; }"
                        )
                        browser.setFrameShape(QFrame.NoFrame)
                        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        browser.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        browser.document().setDocumentMargin(0)

                        def update_browser_height(b=browser):
                            try:
                                h2 = b.document().size().height()
                                b.setFixedHeight(max(int(h2) + 10, 24))
                            except RuntimeError:
                                pass

                        try:
                            browser.textChanged.connect(update_browser_height)
                        except Exception:
                            pass
                        update_browser_height()
                        self.layout.addWidget(browser)
                continue
            else:
                title = "🛠️ Tool execution" if kind == "tool" else "💭 Discussion"
                # ensure active-but-empty blocks display a placeholder and show spinner
                content_for_section = content
                if is_active and not content.strip():
                    content_for_section = "<i>Waiting for results...</i>"
                section = CollapsibleSection(
                    title, content_for_section, is_active=is_active
                )
                self.layout.addWidget(section)

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

        # 計算球球位置 - 位於視窗高度80%的地方
        ball_center_x = self.width() / 2
        ball_center_y = self.height() * 0.8  # 從頂部算起80%的位置

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

        # 第二層：中等擴散
        mid_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter / 1.2
        )
        c_mid = QColor(circle_color)
        c_mid.setAlpha(100)
        mid_grad.setColorAt(0, c_mid)
        mid_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(mid_grad)
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter),
            int(ball_center_y - self.circle.diameter),
            int(self.circle.diameter * 2),
            int(self.circle.diameter * 2),
        )

        # 第三層：廣域外溢
        outer_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter * 1.5
        )
        c_outer = QColor(circle_color)
        c_outer.setAlpha(40)
        outer_grad.setColorAt(0, c_outer)
        outer_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(outer_grad)
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter * 1.5),
            int(ball_center_y - self.circle.diameter * 1.5),
            int(self.circle.diameter * 3),
            int(self.circle.diameter * 3),
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Assistant")
        self.setGeometry(100, 100, 460, 800)  # 初始較小的尺寸
        self.arcWidget = ArcWidget()
        # Essential for translucency and frameless
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setCentralWidget(self.arcWidget)

        self.old_pos = None  # 初始化拖拽位置
        self.input_callback = None  # 回調函數，用於處理用戶輸入

        self.close_button = QPushButton("×", self)
        self.close_button.setFixedSize(26, 26)
        self.close_button.setStyleSheet(
            "QPushButton { "
            "background-color: rgba(255, 69, 58, 180); "
            "color: white; "
            "border-radius: 13px; "
            "font-size: 18px; "
            "font-weight: bold; "
            "border: none; "
            "line-height: 22px; "
            "}"
            "QPushButton:hover { background-color: rgba(255, 69, 58, 255); }"
        )
        self.close_button.clicked.connect(self.close)
        self.close_button.raise_()

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

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("輸入文字或按啟動語音...")
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

    def set_input_callback(self, callback):
        """設置輸入回調函數"""
        self.input_callback = callback

    def on_input_submitted(self):
        """處理文字輸入提交"""
        text = self.input_field.text().strip()
        if text and self.input_callback:
            self.input_field.clear()
            self.input_field.setPlaceholderText("輸入文字或按啟動語音...")
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
            # 設置輸入框位置（在視窗底部）
            input_width = min(self.width() - 40, 500)
            input_height = 45
            self.input_container.setGeometry(
                (self.width() - input_width) // 2,
                self.height() - input_height - 20,
                input_width,
                input_height,
            )
            self.input_container.show()
        event.accept()

    def update_speech_bubble(self, text):
        """更新對話框內容並動態調整大小和視窗大小"""
        self.speech_bubble.set_content(text)

        # Process events to allow layout updates before measuring
        QApplication.processEvents()

        padding = 60
        bubble_width = min(max(self.speech_bubble.preferred_width, 240), 440)

        # Get actual content height and apply growing logic
        needed_height = self.speech_bubble.content_height() + padding
        bubble_height = min(
            max(needed_height, 180),
            self.speech_bubble.max_height,
        )
        self.speech_bubble.setFixedSize(bubble_width, bubble_height)
        # Force synchronous layout updates so parent measurement sees the new sizes immediately.
        try:
            self.speech_bubble.layout.activate()
            self.speech_bubble.container.adjustSize()
            QApplication.processEvents()
        except Exception:
            pass

        # 計算球球的有效範圍（包含旋轉圓弧）
        circle_radius = self.arcWidget.circle.diameter // 2  # 實心圓半徑 = 50
        max_arc_diameter = 100  # Arc 的最大直徑
        max_arc_radius = max_arc_diameter // 2  # Arc 的最大半徑 = 50

        # 有效半徑應該是實心圓半徑加上最大圓弧半徑
        effective_radius = circle_radius + max_arc_radius  # 50 + 50 = 100

        # 計算球球區域的高度（球球位於視窗80%的位置）
        ball_area_height = effective_radius * 2  # 球球需要的高度
        ball_center_ratio = 0.8  # 球球中心位於視窗高度的80%

        # 計算理想的視窗寬度和高度
        min_side_margin = 20  # 定義最小側邊距
        min_top_margin = 20  # 定義最小頂部邊距
        overlap_offset = 40  # 對話框底部與球體頂部的重疊深度
        ideal_width = max(
            bubble_width + min_side_margin * 2,
            effective_radius * 2 + min_side_margin * 2,
        )
        # 確保球體中心維持在 80% 的位置，由上方所需空間倒推總高度
        # 扣除重疊部分，讓視窗高度計算更精確
        required_height_above_center = (
            min_top_margin + bubble_height - overlap_offset + effective_radius
        )
        ideal_height = required_height_above_center / ball_center_ratio

        # 取得當前視窗尺寸和位置
        current_width = self.width()
        current_height = self.height()

        # 計算當前視窗底部位置（在螢幕座標系中）
        current_bottom_y = self.y() + current_height

        # 計算新的視窗位置（保持視窗底部不變，讓內容從底部向上伸展）
        new_y = current_bottom_y - ideal_height  # 鎖定底部位置，從底部推算新視窗Y座標
        new_x = self.x() + (current_width - ideal_width) // 2  # X方向置中調整

        # 調整視窗大小和位置 - 使用 fixed geometry 確保球心不變
        # 為了避免"漂移感"，我們明確地設置視窗，並呼叫 raise_ 確保氣泡在最上層
        self.setGeometry(int(new_x), int(new_y), int(ideal_width), int(ideal_height))
        self.speech_bubble.raise_()

        # 定位關閉按鈕到右上角
        self.close_button.move(self.width() - self.close_button.width() - 10, 10)

        # 重新計算對話框位置
        window_center_x = self.width() // 2
        ball_center_y = self.height() * ball_center_ratio  # 球球中心位置
        ball_top_y = ball_center_y - effective_radius

        # 計算氣泡框位置：讓氣泡底部「沉入」球體區域產生重疊感，並始終往上生長
        bubble_x = window_center_x - bubble_width // 2
        bubble_y = ball_top_y - bubble_height + overlap_offset
        # 確保氣泡不會超出頂部
        bubble_y = max(min_top_margin, bubble_y)

        # 確保對話框不會超出視窗左右邊界
        bubble_x = max(10, min(bubble_x, self.width() - bubble_width - 10))

        # 設置講話框位置
        self.speech_bubble.move(bubble_x, bubble_y)
        self.speech_bubble.show()

        # 更新輸入容器位置（在視窗底部）
        if self.input_container.isVisible():
            input_width = min(self.width() - 40, 500)
            input_height = 45
            self.input_container.setGeometry(
                (self.width() - input_width) // 2,
                self.height() - input_height - 20,
                input_width,
                input_height,
            )
            self.input_container.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    mainWindow = MainWindow()
    mainWindow.show()

    app.exec()
