import sys
import string
import random



from PySide6.QtWidgets import (QMainWindow, QPushButton, QVBoxLayout, 
        QApplication, QWidget, QLabel)
from PySide6.QtCore import (Qt, QVariantAnimation)
from PySide6.QtGui import (QPen, QPainter, QColor, QRadialGradient)

class Arc:
    colors = list(string.ascii_lowercase[0:6]+string.digits)

    shades_of_blue = ["#7CB9E8","#00308F","#72A0C1", "#F0F8FF",
            "#007FFF", "#6CB4EE", "#002D62", "#5072A7", 
            "#002244", "#B2FFFF", "#6F00FF", "#7DF9FF","#007791",
            "#ADD8E6", "#E0FFFF", "#005f69", "#76ABDF",
            "#6A5ACD", "#008080", "#1da1f2", "#1a1f71", "#0C2340"]

    shades_of_green = ['#32CD32', '#CAE00D', '#9EFD38', '#568203', '#93C572',
            '#8DB600', '#708238', '#556B2F', '#014421', '#98FB98', '#7CFC00',
            '#4F7942', '#009E60', '#00FF7F', '#00FA9A', '#177245', '#2E8B57', 
            '#3CB371', '#A7F432', '#123524', '#5E8C31', '#90EE90', '#03C03C',
            '#66FF00', '#006600', '#D9E650']

    def __init__(self):
        self.diameter = random.randint(1, 100)

        #cols = list(Arc.colors)
        #random.shuffle(cols)
        #_col = "#"+''.join(cols[:6])
        #print(f"{_col=}")
        #self.color = QColor(_col)

        #self.color = QColor(Arc.shades_of_blue[random.randint(0, len(Arc.shades_of_blue)-1)])
        self.color = QColor(Arc.shades_of_green[random.randint(0, len(Arc.shades_of_green)-1)])
        #print(f"{self.color=}")
        self.span = random.randint(40, 150)
        self.direction = 1 if random.randint(10, 15)%2 == 0 else -1
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
        g = int(current_color.green() + (next_color.green() - current_color.green()) * t)
        b = int(current_color.blue() + (next_color.blue() - current_color.blue()) * t)
        
        return QColor(r, g, b).name()

class ArcWidget(QWidget):

    def __init__(self):
        super().__init__()
        self.initUI()
        self.arcs = [Arc() for i in range(20)]
        self.circle = Circle()  # 新增這行
        self.startAnime()

    def initUI(self):
        #self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 添加這行
        self.setStyleSheet("background-color:transparent;")  # 改為透明
        

    def startAnime(self):

        self.anim = QVariantAnimation(self, duration = 10000)
        self.anim.setStartValue(0)
        self.anim.setEndValue(360)
        self.anim.valueChanged.connect(self.update)
        self.anim.start()


    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 取得圓圈顏色
        circle_color = self.circle.get_color(self.anim.currentValue())
        
    

        # 繪製底層實心圓
        painter.setBrush(QColor(circle_color))  # 使用變化的顏色
        painter.setPen(QPen(QColor(circle_color), 2))  # 邊框也使用相同顏色
        painter.drawEllipse(
            self.width()/2 - self.circle.diameter/2,
            self.height()/2 - self.circle.diameter/2,
            self.circle.diameter,
            self.circle.diameter
        )
        
        # 繪製旋轉的圓弧
        for arc in self.arcs:
            painter.setPen(QPen(arc.color, 6, Qt.SolidLine))
            painter.drawArc(self.width()/2 - arc.diameter/2,
                    self.height()/2 - arc.diameter/2, arc.diameter, 
                    arc.diameter, self.anim.currentValue()*16*arc.direction+arc.startAngle*100, arc.span*16) 
            
        if self.anim.currentValue() == 360:
            self.startAnime()

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Animate Arc")
        self.setGeometry(100, 100, 400, 400)  # 初始較小的尺寸
        self.arcWidget = ArcWidget()
        # Essential for translucency and frameless
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setCentralWidget(self.arcWidget)
        
        self.old_pos = None  # 初始化拖拽位置
        
        self.close_button = QPushButton("X")
        self.close_button.setFixedSize(25, 25)
        self.close_button.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; border-radius: 5px; }"
            "QPushButton:hover { background-color: #d32f2f; }"
        )
        
        # 創建講話框 - 改用 QLabel
        self.speech_bubble = QLabel("Hello! I'm a talking circle!")
        self.speech_bubble.setParent(self)
        self.speech_bubble.setFixedSize(200, 50)
        self.speech_bubble.setStyleSheet(
            "QLabel { "
            "background-color: white; "
            "color: black; "
            "border: 2px solid #2E8B57; "
            "border-radius: 15px; "
            "padding: 10px; "
            "}"
        )
        self.speech_bubble.setWordWrap(True)  # QLabel 支援自動換行
        self.speech_bubble.setAlignment(Qt.AlignCenter)  # 文字置中
        self.speech_bubble.hide()  # 初始隱藏

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
        # 雙擊切換講話框顯示/隱藏
        if self.speech_bubble.isVisible():
            self.speech_bubble.hide()
        else:
            # 設置講話框位置（在圓球上方）
            self.speech_bubble.move(
                self.width()//2 - self.speech_bubble.width()//2,
                self.height()//2 - 100
            )
            self.speech_bubble.show()
        event.accept()
    
    def update_speech_bubble(self, text):
        """更新對話框內容並動態調整大小和視窗大小"""
        self.speech_bubble.setText(text)
        
        # 獲取文字的大小
        font_metrics = self.speech_bubble.fontMetrics()
        text_rect = font_metrics.boundingRect(0, 0, 400, 0, Qt.TextWordWrap, text)
        
        # 計算所需的寬度和高度（加上一些padding）
        padding = 20
        bubble_width = min(max(text_rect.width() + padding, 150), 400)  # 最小150，最大400
        bubble_height = max(text_rect.height() + padding, 50)  # 最小50
        
        # 設置對話框新的大小
        self.speech_bubble.setFixedSize(bubble_width, bubble_height)
        
        # 更新樣式以支援文字換行
        self.speech_bubble.setStyleSheet(
            "QLabel { "
            "background-color: white; "
            "color: black; "
            "border: 2px solid #2E8B57; "
            "border-radius: 15px; "
            "padding: 10px; "
            "}"
        )
        
        # 計算球球的有效範圍（包含旋轉圓弧）
        circle_radius = self.arcWidget.circle.diameter // 2  # 實心圓半徑 = 50
        max_arc_diameter = 100  # Arc 的最大直徑
        max_arc_radius = max_arc_diameter // 2  # Arc 的最大半徑 = 50
        
        # 有效半徑應該是實心圓半徑加上最大圓弧半徑
        effective_radius = circle_radius + max_arc_radius  # 50 + 50 = 100
        
        # 計算理想的視窗尺寸
        min_top_margin = 10  # 視窗上緣的最小邊距
        min_side_margin = 20  # 視窗左右邊的最小邊距
        bubble_gap = 10  # 氣泡框與球球之間的間隙
        
        # 計算球球區域的高度（球球位於視窗下緣上方0.2的部分）
        ball_area_height = effective_radius * 2  # 球球需要的高度
        ball_bottom_margin = ball_area_height * 0.2  # 球球底部距離視窗下緣的距離
        
        # 計算理想的視窗寬度和高度
        ideal_width = max(bubble_width + min_side_margin * 2, effective_radius * 2 + min_side_margin * 2)
        ideal_height = min_top_margin + bubble_height + bubble_gap + ball_area_height + ball_bottom_margin
        
        # 取得當前視窗尺寸和位置
        current_width = self.width()
        current_height = self.height()
        current_center_x = self.x() + current_width // 2
        current_center_y = self.y() + current_height // 2
        
        # 計算新的視窗位置（保持中心不變）
        new_x = current_center_x - ideal_width // 2
        new_y = current_center_y - ideal_height // 2
        
        # 調整視窗大小和位置
        self.setGeometry(new_x, new_y, ideal_width, ideal_height)
        
        # 重新計算位置 - 球球位於視窗下緣上方0.2的部分
        window_center_x = self.width() // 2
        ball_center_y = self.height() - ball_bottom_margin - effective_radius  # 球球中心位置
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


if __name__ == "__main__":

    app = QApplication(sys.argv)

    mainWindow = MainWindow()
    mainWindow.show()

    app.exec()