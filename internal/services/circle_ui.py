import random
import string
import sys

from PySide6.QtCore import Qt, QVariantAnimation
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class Arc:
    colors = list(string.ascii_lowercase[0:6] + string.digits)

    shades_of_blue = [
        "#7CB9E8",
        "#00308F",
        "#72A0C1",
        "#F0F8FF",
        "#007FFF",
        "#6CB4EE",
        "#002D62",
        "#5072A7",
        "#002244",
        "#B2FFFF",
        "#6F00FF",
        "#7DF9FF",
        "#007791",
        "#ADD8E6",
        "#E0FFFF",
        "#005f69",
        "#76ABDF",
        "#6A5ACD",
        "#008080",
        "#1da1f2",
        "#1a1f71",
        "#0C2340",
    ]

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
        self.diameter = random.randint(1, 100)

        # cols = list(Arc.colors)
        # random.shuffle(cols)
        # _col = "#"+''.join(cols[:6])
        # print(f"{_col=}")
        # self.color = QColor(_col)

        # self.color = QColor(Arc.shades_of_blue[random.randint(0, len(Arc.shades_of_blue)-1)])
        self.color = QColor(
            Arc.shades_of_green[random.randint(0, len(Arc.shades_of_green) - 1)]
        )
        # print(f"{self.color=}")
        self.span = random.randint(40, 150)
        self.direction = 1 if random.randint(10, 15) % 2 == 0 else -1
        self.startAngle = random.randint(40, 200)
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


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(False)
        self.button.setArrowType(Qt.RightArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.clicked.connect(self.toggle)

        self.content = QTextBrowser()
        self.content.setMarkdown(content)
        self.content.setOpenExternalLinks(True)
        self.content.setFrameShape(QFrame.NoFrame)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.content.setVisible(False)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.button)
        layout.addWidget(self.content)

    def toggle(self):
        expanded = self.button.isChecked()
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)


class OutputBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_height = 320
        self.preferred_width = 360
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "background-color: white; "
            "color: black; "
            "border: 2px solid #2E8B57; "
            "border-radius: 15px;"
        )

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent;")

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

        def add_segment(kind, chunk):
            if not chunk:
                return
            if segments and segments[-1][0] == kind:
                segments[-1] = (kind, segments[-1][1] + chunk)
            else:
                segments.append((kind, chunk))

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

        # 繪製底層實心圓
        painter.setBrush(QColor(circle_color))  # 使用變化的顏色
        painter.setPen(QPen(QColor(circle_color), 2))  # 邊框也使用相同顏色
        painter.drawEllipse(
            ball_center_x - self.circle.diameter / 2,
            ball_center_y - self.circle.diameter / 2,
            self.circle.diameter,
            self.circle.diameter,
        )

        # 繪製旋轉的圓弧
        for arc in self.arcs:
            painter.setPen(QPen(arc.color, 6, Qt.SolidLine))
            painter.drawArc(
                ball_center_x - arc.diameter / 2,
                ball_center_y - arc.diameter / 2,
                arc.diameter,
                arc.diameter,
                self.anim.currentValue() * 16 * arc.direction + arc.startAngle * 100,
                arc.span * 16,
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

        self.close_button = QPushButton("X")
        self.close_button.setFixedSize(25, 25)
        self.close_button.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; border-radius: 5px; }"
            "QPushButton:hover { background-color: #d32f2f; }"
        )

        # 創建講話框 - 改用 OutputBubble
        self.speech_bubble = OutputBubble()
        self.speech_bubble.setParent(self)
        self.speech_bubble.setFixedSize(200, 50)
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
            "background-color: rgba(255, 255, 255, 0.9); "
            "color: black; "
            "border: 2px solid #2E8B57; "
            "border-radius: 10px; "
            "padding: 8px; "
            "}"
        )
        self.input_field.returnPressed.connect(self.on_input_submitted)

        self.voice_button = QPushButton("🎤")
        self.voice_button.setFixedSize(35, 35)
        self.voice_button.setStyleSheet(
            "QPushButton { "
            "background-color: #2E8B57; "
            "color: white; "
            "border: none; "
            "border-radius: 17px; "
            "font-size: 16px; "
            "}"
            "QPushButton:hover { background-color: #3CB371; }"
        )
        self.voice_button.clicked.connect(self.on_voice_requested)

        self.send_button = QPushButton("發送")
        self.send_button.setFixedSize(60, 35)
        self.send_button.setStyleSheet(
            "QPushButton { "
            "background-color: #2E8B57; "
            "color: white; "
            "border: none; "
            "border-radius: 10px; "
            "}"
            "QPushButton:hover { background-color: #3CB371; }"
        )
        self.send_button.clicked.connect(self.on_input_submitted)

        self.input_layout.addWidget(self.voice_button)
        self.input_layout.addWidget(self.input_field)
        self.input_layout.addWidget(self.send_button)

        self.input_container.hide()  # 初始隱藏

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

        padding = 10
        bubble_width = min(max(self.speech_bubble.preferred_width, 200), 400)
        bubble_height = min(
            max(self.speech_bubble.content_height() + padding, 50),
            self.speech_bubble.max_height,
        )
        self.speech_bubble.setFixedSize(bubble_width, bubble_height)

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
        bubble_gap = 10  # 對話框與球球之間的間距
        ideal_width = max(
            bubble_width + min_side_margin * 2,
            effective_radius * 2 + min_side_margin * 2,
        )
        ideal_height = (
            min_top_margin
            + bubble_height
            + bubble_gap
            + ball_area_height
            + (ball_area_height * (1 - ball_center_ratio))
        )

        # 取得當前視窗尺寸和位置
        current_width = self.width()
        current_height = self.height()

        # 計算當前球球的中心位置（在螢幕座標系中）
        current_ball_center_y = self.y() + current_height * ball_center_ratio

        # 計算新的視窗位置（保持球球中心不變）
        new_y = (
            current_ball_center_y - ideal_height * ball_center_ratio
        )  # 從球球中心推算新視窗Y座標
        new_x = self.x() + (current_width - ideal_width) // 2  # X方向置中調整

        # 調整視窗大小和位置
        self.setGeometry(new_x, new_y, ideal_width, ideal_height)

        # 重新計算對話框位置
        window_center_x = self.width() // 2
        ball_center_y = self.height() * ball_center_ratio  # 球球中心位置
        ball_top_y = ball_center_y - effective_radius
        available_space = ball_top_y - min_top_margin

        # 計算氣泡框位置（置中在可用空間）
        bubble_x = window_center_x - bubble_width // 2
        bubble_y = min_top_margin + (available_space - bubble_height) // 2

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
