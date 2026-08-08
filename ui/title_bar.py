from PyQt5.QtCore import Qt, QPoint, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from resources.constants import (
    C_CARD, C_BORDER, C_MUTED, C_TEXT, C_ACCENT, C_DANGER
)
from ui.widgets import StatusIndicator

class TitleBarButton(QPushButton):
    """Кастомная кнопка управления окном с качественной отрисовкой векторных иконок."""
    def __init__(self, btn_type: str, parent=None):
        super().__init__(parent)
        self.btn_type = btn_type  # 'min', 'max', 'close'
        self.setFixedSize(36, 32)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.underMouse():
            bg_color = QColor(C_DANGER) if self.btn_type == "close" else QColor(255, 255, 255, 18)
            icon_color = QColor(255, 255, 255)
        else:
            bg_color = QColor(Qt.transparent)
            icon_color = QColor(C_MUTED)

        # Отрисовка фона
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(self.rect(), 4, 4)

        # Отрисовка геометрии иконки
        pen = QPen(icon_color, 1.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2

        if self.btn_type == "min":
            painter.drawLine(int(cx - 5), int(cy), int(cx + 5), int(cy))
        elif self.btn_type == "max":
            painter.drawRect(QRectF(cx - 4.5, cy - 4.5, 9, 9))
        elif self.btn_type == "close":
            painter.drawLine(int(cx - 4), int(cy - 4), int(cx + 4), int(cy + 4))
            painter.drawLine(int(cx + 4), int(cy - 4), int(cx - 4), int(cy + 4))


class TitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.win = parent
        self.setFixedHeight(40)
        self.setObjectName("TitleBar")
        self.setStyleSheet(f"""
            #TitleBar {{
                background-color: {C_CARD};
                border-bottom: 1px solid {C_BORDER};
            }}
            QLabel#AppTitle {{
                color: {C_TEXT};
                font-size: 13px;
                font-weight: 600;
                padding-left: 6px;
            }}
            QLabel#VersionTag {{
                color: {C_MUTED};
                font-size: 11px;
                padding-right: 8px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(4)

        # Статус соединения в баре
        self.status_dot = StatusIndicator(size=8)
        self.status_dot.setToolTip("Disconnected")
        layout.addWidget(self.status_dot)

        # Название и версия
        self.title_label = QLabel("XaraProxy")
        self.title_label.setObjectName("AppTitle")
        layout.addWidget(self.title_label)

        self.version_label = QLabel("v1.0")
        self.version_label.setObjectName("VersionTag")
        layout.addWidget(self.version_label)

        layout.addStretch()

        # Кнопки управления окном
        self.min_btn = TitleBarButton("min", self)
        self.min_btn.clicked.connect(self.win.showMinimized)
        layout.addWidget(self.min_btn)

        self.max_btn = TitleBarButton("max", self)
        self.max_btn.clicked.connect(self.toggle_maximize)
        layout.addWidget(self.max_btn)

        self.close_btn = TitleBarButton("close", self)
        self.close_btn.clicked.connect(self.win.close)
        layout.addWidget(self.close_btn)

    def toggle_maximize(self) -> None:
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def button_at(self, local_pos: QPoint) -> bool:
        return any(btn.geometry().contains(local_pos) for btn in (self.min_btn, self.max_btn, self.close_btn))