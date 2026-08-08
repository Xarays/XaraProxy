# widgets
import math
from collections import deque

from PyQt5.QtCore import (
    Qt, QTimer, QVariantAnimation, QEasingCurve,
    QPropertyAnimation, QParallelAnimationGroup,
    QPoint, QPointF, QRectF, QSize, QAbstractAnimation,
    pyqtSignal
)
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient,
    QFont, QPalette, QPixmap, QFontMetrics, QPainterPath
)
from PyQt5.QtWidgets import (
    QWidget, QPushButton, QCheckBox, QLabel, QApplication,
    QHBoxLayout, QVBoxLayout, QProgressBar, QListWidget,
    QAbstractItemView, QScrollArea, QTextEdit, QGraphicsOpacityEffect,
    QSizePolicy
)
from resources.constants import (
    C_BG, C_CARD, C_CARD_ALT, C_INPUT, C_BORDER, C_TEXT,
    C_MUTED, C_ACCENT, C_ACCENT_HOVER, C_SUCCESS, C_DANGER, C_WARN,
    C_CHART_DOWN, C_CHART_UP
)

# ---- vector icon ----
def draw_vector_icon(painter: QPainter, kind: str, rect: QRectF, color: QColor) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(max(1.6, rect.width() * 0.11))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    w, h = rect.width(), rect.height()

    if kind == "download":
        painter.drawLine(int(cx), int(rect.top() + h * 0.1), int(cx), int(rect.bottom() - h * 0.35))
        path = QPainterPath()
        path.moveTo(cx - w * 0.22, rect.bottom() - h * 0.55)
        path.lineTo(cx, rect.bottom() - h * 0.3)
        path.lineTo(cx + w * 0.22, rect.bottom() - h * 0.55)
        painter.drawPath(path)
        painter.drawLine(int(rect.left() + w * 0.15), int(rect.bottom() - h * 0.12),
                          int(rect.right() - w * 0.15), int(rect.bottom() - h * 0.12))
    elif kind == "upload":
        painter.drawLine(int(cx), int(rect.bottom() - h * 0.1), int(cx), int(rect.top() + h * 0.35))
        path = QPainterPath()
        path.moveTo(cx - w * 0.22, rect.top() + h * 0.55)
        path.lineTo(cx, rect.top() + h * 0.3)
        path.lineTo(cx + w * 0.22, rect.top() + h * 0.55)
        painter.drawPath(path)
        painter.drawLine(int(rect.left() + w * 0.15), int(rect.bottom() - h * 0.12),
                          int(rect.right() - w * 0.15), int(rect.bottom() - h * 0.12))
    elif kind == "signal":
        bars = 4
        bar_w = w / (bars * 1.6)
        for i in range(bars):
            bh = h * (0.25 + 0.22 * i)
            bx = rect.left() + i * bar_w * 1.6
            by = rect.bottom() - bh
            painter.fillRect(QRectF(bx, by, bar_w, bh), color)
    elif kind == "check":
        path = QPainterPath()
        path.moveTo(rect.left() + w * 0.18, cy)
        path.lineTo(cx - w * 0.05, rect.bottom() - h * 0.2)
        path.lineTo(rect.right() - w * 0.18, rect.top() + h * 0.22)
        painter.drawPath(path)
    elif kind == "cross":
        painter.drawLine(int(rect.left() + w * 0.22), int(rect.top() + h * 0.22),
                          int(rect.right() - w * 0.22), int(rect.bottom() - h * 0.22))
        painter.drawLine(int(rect.right() - w * 0.22), int(rect.top() + h * 0.22),
                          int(rect.left() + w * 0.22), int(rect.bottom() - h * 0.22))
    elif kind == "gear":
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect.adjusted(w * 0.28, h * 0.28, -w * 0.28, -h * 0.28))
        painter.drawEllipse(rect.center(), w * 0.06, h * 0.06)
    elif kind == "shield":
        path = QPainterPath()
        path.moveTo(cx, rect.top() + h * 0.08)
        path.lineTo(rect.right() - w * 0.14, rect.top() + h * 0.24)
        path.lineTo(rect.right() - w * 0.14, rect.top() + h * 0.55)
        path.cubicTo(rect.right() - w * 0.14, rect.bottom() - h * 0.12,
                     cx + w * 0.1, rect.bottom() - h * 0.02,
                     cx, rect.bottom() - h * 0.02)
        path.cubicTo(cx - w * 0.1, rect.bottom() - h * 0.02,
                     rect.left() + w * 0.14, rect.bottom() - h * 0.12,
                     rect.left() + w * 0.14, rect.top() + h * 0.55)
        path.lineTo(rect.left() + w * 0.14, rect.top() + h * 0.24)
        path.closeSubpath()
        painter.drawPath(path)
    painter.restore()

class VectorIconLabel(QWidget):
    def __init__(self, kind: str, color: str = C_TEXT, size: int = 16, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        draw_vector_icon(painter, self.kind, QRectF(self.rect()), self.color)

# ---- smooth button ----
class SmoothButton(QPushButton):
    def __init__(self, text: str = "", parent=None, base_color: str = C_ACCENT,
                 hover_color: str = C_ACCENT_HOVER, text_color: str = "#FFFFFF", radius: int = 8):
        super().__init__(text, parent)
        self._base_color = QColor(base_color)
        self._hover_color = QColor(hover_color)
        self._text_color = QColor(text_color)
        self._current_color = QColor(base_color)
        self._radius = radius
        self._press_scale = 1.0
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setStyleSheet("border: none; background: transparent; font-weight: 600;")

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setStartValue(0.0)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(110)
        self._press_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._press_anim.valueChanged.connect(self._on_press_value)

        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(1100)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.valueChanged.connect(self._on_pulse_value)
        self._pulse_progress = 0.0

    def set_pulsing(self, enabled: bool) -> None:
        if enabled and self._pulse_anim.state() != QVariantAnimation.Running:
            self._pulse_anim.start()
        elif not enabled:
            self._pulse_anim.stop()
            self._pulse_progress = 0.0
            self.update()

    def _on_pulse_value(self, progress: float) -> None:
        self._pulse_progress = progress
        self.update()

    def _on_press_value(self, value: float) -> None:
        self._press_scale = value
        self.update()

    def _on_hover_value(self, progress: float) -> None:
        r = self._base_color.red() + (self._hover_color.red() - self._base_color.red()) * progress
        g = self._base_color.green() + (self._hover_color.green() - self._base_color.green()) * progress
        b = self._base_color.blue() + (self._hover_color.blue() - self._base_color.blue()) * progress
        self._current_color = QColor(int(r), int(g), int(b))
        self.update()

    def enterEvent(self, event) -> None:
        if self.isEnabled():
            self._hover_anim.setDirection(QVariantAnimation.Forward)
            self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.setDirection(QVariantAnimation.Backward)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.isEnabled():
            self._press_anim.stop()
            self._press_anim.setStartValue(1.0)
            self._press_anim.setEndValue(0.96)
            self._press_anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.isEnabled():
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_scale)
            self._press_anim.setEndValue(1.0)
            self._press_anim.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        color = self._current_color if self.isEnabled() else QColor("#3a3a3a")

        if self._pulse_progress > 0.0:
            glow = QColor(color)
            glow.setAlphaF(0.18 + 0.14 * self._pulse_progress)
            pad = 3 + int(3 * self._pulse_progress)
            painter.setBrush(QBrush(glow))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.adjusted(-pad, -pad, pad, pad), self._radius + pad, self._radius + pad)

        if self._press_scale != 1.0:
            cx, cy = rect.center().x(), rect.center().y()
            w = rect.width() * self._press_scale
            h = rect.height() * self._press_scale
            rect = QRectF(cx - w / 2, cy - h / 2, w, h)

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, self._radius, self._radius)
        painter.setPen(QPen(self._text_color if self.isEnabled() else QColor("#777777")))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter, self.text())

# ---- toggle switch ----
class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = "", parent=None, track_w: int = 42, track_h: int = 22):
        super().__init__(text, parent)
        self._track_w = track_w
        self._track_h = track_h
        self._knob_pos = 1.0 if self.isChecked() else 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }")

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self.toggled.connect(self._start_anim)

    def _start_anim(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_anim_value(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        extra = 10 if self.text() else 0
        w = self._track_w + extra + text_w + 4
        h = max(self._track_h + 6, fm.height() + 4)
        return QSize(w, h)

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        track_rect = QRectF(1, (self.height() - self._track_h) / 2.0, self._track_w, self._track_h)
        off_color = QColor(C_BORDER)
        on_color = QColor(C_ACCENT) if self.isEnabled() else QColor("#4a4a4a")
        r = off_color.red() + (on_color.red() - off_color.red()) * self._knob_pos
        g = off_color.green() + (on_color.green() - off_color.green()) * self._knob_pos
        b = off_color.blue() + (on_color.blue() - off_color.blue()) * self._knob_pos
        track_color = QColor(int(r), int(g), int(b))

        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, track_rect.height() / 2, track_rect.height() / 2)

        knob_d = track_rect.height() - 4
        knob_x = track_rect.left() + 2 + self._knob_pos * (track_rect.width() - knob_d - 4)
        knob_rect = QRectF(knob_x, track_rect.top() + 2, knob_d, knob_d)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(knob_rect)

        if self.text():
            text_rect = QRectF(track_rect.right() + 10, 0, self.width() - track_rect.right() - 12, self.height())
            painter.setPen(QColor(C_TEXT if self.isEnabled() else C_MUTED))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())

# ---- status indicator ----
class StatusIndicator(QWidget):
    def __init__(self, parent=None, size: int = 26):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._status = "off"
        self._spin_angle = 0.0
        self._pulse = 0.0

        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(16)
        self._spin_timer.timeout.connect(self._advance_spin)

        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(1600)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.valueChanged.connect(self._on_pulse)

    def _on_pulse(self, value: float) -> None:
        self._pulse = value
        self.update()

    def _advance_spin(self) -> None:
        self._spin_angle = (self._spin_angle + 6.0) % 360.0
        self.update()

    def set_status(self, status: str) -> None:
        self._status = status
        if status == "busy":
            if not self._spin_timer.isActive():
                self._spin_timer.start()
        else:
            self._spin_timer.stop()
        if status == "ok":
            if self._pulse_anim.state() != QVariantAnimation.Running:
                self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse = 0.0
        self.update()

    def hideEvent(self, event) -> None:
        self._spin_timer.stop()
        self._pulse_anim.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2 - 2

        if self._status == "ok":
            glow = QColor(C_SUCCESS)
            glow.setAlphaF(0.35 * (1.0 - self._pulse))
            glow_r = radius + self._pulse * (radius * 0.9)
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center, glow_r, glow_r)
            painter.setBrush(QColor(C_SUCCESS))
            painter.drawEllipse(center, radius, radius)
        elif self._status == "busy":
            pen = QPen(QColor(C_BORDER))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, radius, radius)

            arc_pen = QPen(QColor(C_WARN))
            arc_pen.setWidth(3)
            arc_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(arc_pen)
            span = 110 * 16
            start = int(-self._spin_angle * 16)
            painter.drawArc(QRectF(rect), start, span)
        else:
            painter.setBrush(QColor(C_DANGER))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center, radius, radius)

# ---- sparkline ----
class Sparkline(QWidget):
    def __init__(self, max_points: int = 30, parent=None):
        super().__init__(parent)
        self.max_points = max_points
        self.down_series = deque(maxlen=max_points)
        self.up_series = deque(maxlen=max_points)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def push(self, down_kb: float, up_kb: float) -> None:
        self.down_series.append(max(0.0, down_kb))
        self.up_series.append(max(0.0, up_kb))
        self.update()

    def clear_data(self) -> None:
        self.down_series.clear()
        self.up_series.clear()
        self.update()

    def _series_path(self, series, top: float, height: float, width: float, peak: float):
        path = QPainterPath()
        if not series:
            return path
        n = len(series)
        step = width / max(1, self.max_points - 1)
        offset = self.max_points - n
        for i, v in enumerate(series):
            x = (offset + i) * step
            ratio = 0.0 if peak <= 0 else (v / peak)
            y = top + height - ratio * height
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)

        painter.setPen(QPen(QColor(C_BORDER), 1))
        for frac in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * frac
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        peak = max([1.0] + list(self.down_series) + list(self.up_series))

        for series, color in ((self.down_series, C_CHART_DOWN), (self.up_series, C_CHART_UP)):
            path = self._series_path(series, rect.top(), rect.height(), rect.width(), peak)
            if path.elementCount() == 0:
                continue
            fill_path = QPainterPath(path)
            last_pt = path.currentPosition()
            fill_path.lineTo(last_pt.x(), rect.bottom())
            fill_path.lineTo(rect.left() + (self.max_points - len(series)) * (rect.width() / max(1, self.max_points - 1)), rect.bottom())
            fill_path.closeSubpath()
            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            fill_color = QColor(color)
            fill_color.setAlpha(70)
            grad.setColorAt(0, fill_color)
            transparent = QColor(color)
            transparent.setAlpha(0)
            grad.setColorAt(1, transparent)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawPath(fill_path)

            pen = QPen(QColor(color))
            pen.setWidthF(2.0)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

# ---- toast ----
class ToastNotification(QWidget):
    closed = pyqtSignal(object)
    _COLORS = {"success": C_SUCCESS, "error": C_DANGER, "info": C_ACCENT, "warn": C_WARN}
    _ICON_KIND = {"success": "check", "error": "cross", "info": "signal", "warn": "cross"}

    def __init__(self, parent, message: str, kind: str = "info", duration: int = 3800):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(340)
        self.duration = duration
        self._accent_color = QColor(self._COLORS.get(kind, C_ACCENT))
        self._countdown_progress = 1.0
        icon_kind = self._ICON_KIND.get(kind, "signal")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        self._card = QWidget(self)
        self._card.setObjectName("ToastCard")
        self._card.setStyleSheet(f"""
            #ToastCard {{
                background-color: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 12px;
            }}
        """)
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(14, 12, 10, 13)
        content_row.setSpacing(10)

        icon_wrap = QLabel()
        icon_wrap.setFixedSize(26, 26)
        icon_wrap.setStyleSheet(f"background-color:{self._accent_color.name()}; border-radius:13px;")
        icon_layout = QVBoxLayout(icon_wrap)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.addWidget(VectorIconLabel(icon_kind, "#FFFFFF", 14), alignment=Qt.AlignCenter)
        content_row.addWidget(icon_wrap)

        text_label = QLabel(message)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(f"color:{C_TEXT}; font-size:12px; background: transparent;")
        content_row.addWidget(text_label, stretch=1)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"background: transparent; color:{C_MUTED}; border:none; font-weight:700;")
        close_btn.clicked.connect(self.dismiss)
        content_row.addWidget(close_btn, alignment=Qt.AlignTop)

        card_layout.addLayout(content_row)
        self.adjustSize()

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        card_rect = QRectF(self._card.geometry())
        for i in range(3, 0, -1):
            expand = i * 1.4
            alpha = 16 - i * 3
            shadow_rect = card_rect.adjusted(-expand, -expand + 2, expand, expand + 4)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, max(0, alpha)))
            painter.drawRoundedRect(shadow_rect, 12 + expand, 12 + expand)

        if self._countdown_progress > 0:
            bar_h = 3
            bar_w = card_rect.width() * self._countdown_progress
            bar_rect = QRectF(card_rect.left(), card_rect.bottom() - bar_h, bar_w, bar_h)
            painter.setBrush(self._accent_color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 1.5, 1.5)

        super().paintEvent(event)

    def show_animated(self, target_pos: QPoint) -> None:
        start_pos = QPoint(target_pos.x(), target_pos.y() + 24)
        self.move(start_pos)
        self.show()

        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(240)
        pos_anim.setStartValue(start_pos)
        pos_anim.setEndValue(target_pos)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_anim.setDuration(240)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)

        self._enter_group = QParallelAnimationGroup(self)
        self._enter_group.addAnimation(pos_anim)
        self._enter_group.addAnimation(opacity_anim)
        self._enter_group.start()

        self._dismiss_timer.start(self.duration)

        self._countdown_anim = QVariantAnimation(self)
        self._countdown_anim.setDuration(self.duration)
        self._countdown_anim.setStartValue(1.0)
        self._countdown_anim.setEndValue(0.0)
        self._countdown_anim.valueChanged.connect(self._on_countdown_value)
        self._countdown_anim.start()

    def _on_countdown_value(self, value: float) -> None:
        self._countdown_progress = max(0.0, value)
        self.update()

    def move_to(self, pos: QPoint) -> None:
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(200)
        anim.setStartValue(self.pos())
        anim.setEndValue(pos)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._move_anim = anim

    def dismiss(self) -> None:
        self._dismiss_timer.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(200)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.finished.connect(self._finalize_close)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._exit_anim = anim

    def _finalize_close(self) -> None:
        self.closed.emit(self)
        self.close()
        self.deleteLater()

class ToastManager:
    _SOUND_FOR_KIND = {"success": "toast", "warn": "warn", "error": "error"}

    def __init__(self, parent_window: QWidget, sound_manager = None):
        self.parent_window = parent_window
        self.sound_manager = sound_manager
        self.active_toasts = []

    def show(self, message: str, kind: str = "info") -> None:
        toast = ToastNotification(self.parent_window, message, kind)
        toast.closed.connect(self._on_toast_closed)
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - toast.width() - 24
        y = screen.bottom() - toast.height() - 24
        for t in self.active_toasts:
            y -= (t.height() + 12)
        self.active_toasts.append(toast)
        toast.show_animated(QPoint(x, y))
        if self.sound_manager is not None:
            sound_name = self._SOUND_FOR_KIND.get(kind)
            if sound_name:
                self.sound_manager.play(sound_name)

    def _on_toast_closed(self, toast: ToastNotification) -> None:
        if toast in self.active_toasts:
            self.active_toasts.remove(toast)
        self._reflow()

    def _reflow(self) -> None:
        if not self.active_toasts:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        y = screen.bottom() - 24
        for t in reversed(self.active_toasts):
            y -= t.height()
            t.move_to(QPoint(t.x(), y))
            y -= 12

# ---- skeleton ----
class SkeletonRow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self._opacity = 0.3
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(900)
        self._anim.setStartValue(0.25)
        self._anim.setEndValue(0.6)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.start()

    def _on_value(self, value):
        self._opacity = value
        self.update()

    def stop(self):
        self._anim.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(C_BORDER)
        color.setAlphaF(self._opacity)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(6, 6, 26, 22, 5, 5)
        painter.drawRoundedRect(40, 9, min(self.width() - 60, 220), 16, 5, 5)

# ---- smooth scroll mixin ----
class SmoothScrollMixin:
    def _init_smooth_scroll(self):
        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_anim.setDuration(300)
        self._scroll_anim.valueChanged.connect(self._scroll_slot)
        self._scroll_target = 0

    def _scroll_slot(self, value):
        if hasattr(self, 'verticalScrollBar'):
            self.verticalScrollBar().setValue(int(value))

    def _smooth_scroll_wheel(self, event):
        scrollbar = self.verticalScrollBar()
        if not scrollbar:
            return False
        current = scrollbar.value()
        delta = event.angleDelta().y()

        if self._scroll_anim.state() == QVariantAnimation.Running:
            base = self._scroll_target
        else:
            base = current

        self._scroll_target = max(scrollbar.minimum(), min(scrollbar.maximum(), base - delta))
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(current)
        self._scroll_anim.setEndValue(self._scroll_target)
        self._scroll_anim.start()
        event.accept()
        return True

class SmoothListWidget(QListWidget, SmoothScrollMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_smooth_scroll()
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    def wheelEvent(self, event):
        if self._smooth_scroll_wheel(event):
            return
        super().wheelEvent(event)

class SmoothScrollArea(QScrollArea, SmoothScrollMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_smooth_scroll()

    def wheelEvent(self, event):
        if self._smooth_scroll_wheel(event):
            return
        super().wheelEvent(event)

class SmoothTextEdit(QTextEdit, SmoothScrollMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_smooth_scroll()

    def wheelEvent(self, event):
        if self._smooth_scroll_wheel(event):
            return
        super().wheelEvent(event)

# ---- apply theme ----
def apply_strict_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(C_BG))
    palette.setColor(QPalette.WindowText, QColor(C_TEXT))
    palette.setColor(QPalette.Base, QColor(C_INPUT))
    palette.setColor(QPalette.AlternateBase, QColor(C_CARD))
    palette.setColor(QPalette.ToolTipBase, QColor(C_BG))
    palette.setColor(QPalette.ToolTipText, QColor(C_TEXT))
    palette.setColor(QPalette.Text, QColor(C_TEXT))
    palette.setColor(QPalette.Button, QColor(C_CARD))
    palette.setColor(QPalette.ButtonText, QColor(C_TEXT))
    palette.setColor(QPalette.BrightText, QColor(C_ACCENT))
    palette.setColor(QPalette.Highlight, QColor(C_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#606060"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#606060"))
    app.setPalette(palette)

    app.setStyleSheet(f"""
        QWidget {{
            background-color: transparent;
            color: {C_TEXT};
            font-family: 'Segoe UI', 'Arial', sans-serif;
            font-size: 13px;
        }}
        QMainWindow, QDialog, QWizard {{ background-color: transparent; }}
        QGroupBox {{
            background-color: {C_CARD};
            border: 1px solid {C_BORDER};
            border-radius: 10px;
            margin-top: 16px;
            padding: 14px;
            padding-top: 16px;
            font-weight: 600;
        }}
        QGroupBox:hover {{
            border: 1px solid #4a4a58;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 8px;
            color: {C_MUTED};
        }}
        QLabel {{ background: transparent; }}
        QPushButton {{
            background-color: {C_ACCENT};
            color: white;
            border: none;
            border-radius: 6px;
            padding: 9px 18px;
            font-weight: 600;
            min-height: 18px;
        }}
        QPushButton:hover {{ background-color: {C_ACCENT_HOVER}; }}
        QPushButton:pressed {{ background-color: #4a5eb5; }}
        QPushButton:disabled {{ background-color: #3a3a3a; color: #777777; }}
        QComboBox, QLineEdit, QSpinBox, QTextEdit, QListWidget {{
            background-color: {C_INPUT};
            border: 1px solid {C_BORDER};
            border-radius: 6px;
            padding: 7px;
            color: {C_TEXT};
            selection-background-color: {C_ACCENT};
        }}
        QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {{ border: 1.5px solid {C_ACCENT}; }}
        QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border: 1px solid #4a4a58; }}
        QComboBox QAbstractItemView {{
            background-color: {C_CARD};
            color: {C_TEXT};
            selection-background-color: {C_ACCENT};
            border-radius: 6px;
            padding: 4px;
        }}
        QListWidget::item {{ padding: 8px 6px; border-radius: 4px; }}
        QListWidget::item:selected {{ background-color: #2a2a2a; }}
        QListWidget::item:hover {{ background-color: #1a1a1a; }}
        QTabWidget::pane {{ border: none; margin-top: 16px; background: transparent; }}
        QTabBar {{ qproperty-drawBase: 0; }}
        QTabBar::tab {{
            background-color: transparent;
            color: {C_MUTED};
            padding: 10px 22px;
            border-radius: 5px;
            margin-right: 2px;
            font-weight: 450;
        }}
        QTabBar::tab:selected {{ background-color: {C_CARD}; color: {C_TEXT}; }}
        QTabBar::tab:hover:!selected {{ background-color: #1a1a1a; }}
        QCheckBox, QRadioButton {{ spacing: 8px; color: {C_TEXT}; background: transparent; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 18px; height: 18px; border-radius: 4px;
            border: 2px solid {C_BORDER}; background: {C_INPUT};
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: {C_ACCENT}; border-color: {C_ACCENT};
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {C_ACCENT}; }}
        QRadioButton::indicator {{ border-radius: 9px; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
        QScrollBar::handle:vertical {{ background: {C_BORDER}; border-radius: 5px; min-height: 20px; }}
        QScrollBar::handle:vertical:hover {{ background: {C_ACCENT}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QProgressBar {{ border: none; background: {C_CARD_ALT}; border-radius: 4px; text-align: center; color: {C_TEXT}; }}
        QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 4px; }}
        QLabel#Title {{ font-size: 22px; font-weight: 700; letter-spacing: 0.5px; color: {C_TEXT}; }}
        QLabel#Hint {{ color: {C_MUTED}; font-size: 12px; }}
        QStatusBar {{ background-color: {C_CARD}; color: {C_MUTED}; font-size: 12px; }}
        QToolTip {{ background-color: {C_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 4px; }}
        QMenu {{ background-color: {C_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 4px; }}
        QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
        QMenu::item:selected {{ background-color: {C_ACCENT}; }}
        QMenu::separator {{ height: 1px; background: {C_BORDER}; margin: 4px 8px; }}
    """)