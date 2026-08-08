# main window
import os
import sys
import json
import time
import subprocess
import ctypes
import socket
import math
import logging
from collections import deque

from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation,
    QParallelAnimationGroup, QPoint, QRectF, QSize, QAbstractAnimation,
    QMutex, QMutexLocker, pyqtSignal, QFileInfo
)
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPalette, QPixmap, QRadialGradient,
    QPen, QTextCursor, QIcon
)
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QComboBox, QSpinBox, QGroupBox,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QFileDialog, QTabWidget, QTextEdit, QScrollArea,
    QSystemTrayIcon, QMenu, QRadioButton, QButtonGroup,
    QSizePolicy, QWizard, QWizardPage, QInputDialog,
    QFileIconProvider, QAbstractItemView, QGraphicsOpacityEffect,
    QLineEdit
)

import psutil
import requests

from resources.constants import *
from resources.strings import _t, set_language, STRINGS, _current_lang
from utils.system import (
    is_admin, run_as_admin, set_windows_autostart,
    find_warp_cli, is_system_path, set_windows_system_proxy,
    enable_acrylic_blur
)
from utils.network import (
    socks_proxy_url, requests_proxies, build_proxy_env,
    build_launch_args, ping_region, ping_dns, parse_cf_trace
)
from utils.security import verify_file_signature, apply_kill_switch_rule, remove_kill_switch_rule
from utils.config import load_config, save_config
from ui.widgets import *
from ui.title_bar import TitleBar
from controllers.warp_controller import WarpController
from threads.ping_thread import PingThread, DNSCheckThread, EndpointPingThread, TraceCheckThread
from threads.speed_test_thread import SpeedTestThread
from threads.installer_thread import InstallerDownloadThread
from threads.monitor_thread import ConnectionsMonitorThread
from threads.watchdog_thread import WarpServiceWatchdogThread
from threads.warp_disconnect_thread import WarpDisconnectThread
from threads.app_scanner_thread import AppScannerThread
from utils.stalzone import find_stalzone_paths

# ---- logger setup ----
logger = logging.getLogger("XaraProxy")
logger.setLevel(logging.DEBUG)

class QtLogHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink
        self.setFormatter(logging.Formatter("%(message)s"))
    def emit(self, record):
        try:
            msg = self.format(record)
            self.sink.emit_log(msg, record.levelname)
        except Exception:
            pass

class LogSignalEmitter(QWidget):
    log_signal = pyqtSignal(str, str)
    def emit_log(self, message, level):
        self.log_signal.emit(message, level)

# ---- sound manager ----
try:
    import winsound
    _HAS_WINSOUND = True
except Exception:
    winsound = None
    _HAS_WINSOUND = False

def _write_gentle_tone(path, freq_start, freq_end, duration_ms, volume=0.16):
    import wave, struct
    rate = 44100
    n_samples = int(rate * duration_ms / 1000)
    frames = bytearray()
    for i in range(n_samples):
        t = i / rate
        progress = i / max(1, n_samples - 1)
        freq = freq_start + (freq_end - freq_start) * progress
        if progress < 0.15:
            env = 0.5 - 0.5 * math.cos(math.pi * (progress / 0.15))
        elif progress > 0.70:
            env = 0.5 + 0.5 * math.cos(math.pi * ((progress - 0.70) / 0.30))
        else:
            env = 1.0
        sample = math.sin(2 * math.pi * freq * t) * volume * env
        frames += struct.pack("<h", int(sample * 32767))
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))

class SoundManager:
    _SPECS = {
        "connect": (392.0, 587.0, 260),
        "disconnect": (523.0, 349.0, 220),
        "warn": (330.0, 294.0, 180),
        "error": (247.0, 196.0, 260),
        "toast": (660.0, 660.0, 90),
    }
    def __init__(self):
        self.enabled = True
        self._dir = os.path.join(APP_DIR, "resources", "sounds")
        self._ready = False
    def _ensure_sounds(self):
        if self._ready:
            return
        try:
            os.makedirs(self._dir, exist_ok=True)
            for name, (f1, f2, dur) in self._SPECS.items():
                path = os.path.join(self._dir, f"{name}.wav")
                if not os.path.exists(path):
                    _write_gentle_tone(path, f1, f2, dur)
            self._ready = True
        except Exception:
            pass
    def play(self, name):
        if not self.enabled or not _HAS_WINSOUND:
            return
        self._ensure_sounds()
        path = os.path.join(self._dir, f"{name}.wav")
        if os.path.exists(path):
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                pass

# ---- main window ----
BORDER_WIDTH = 6
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTCAPTION = 2
HTLEFT, HTRIGHT, HTTOP, HTBOTTOM = 10, 11, 12, 15
HTTOPLEFT, HTTOPRIGHT, HTBOTTOMLEFT, HTBOTTOMRIGHT = 13, 14, 16, 17

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        set_language(self.config.get("language", "ru"))
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800)
        self.setMinimumSize(1000, 680)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.title_bar = TitleBar(self)

        self.warp_cli_path = find_warp_cli()
        self.controller = None
        self.app_list = []
        self.app_items = {}
        self.icon_provider = QFileIconProvider()
        self.system_proxy_enabled = False
        self.kill_switch_enabled = False
        self.is_running = False
        self._acrylic_enabled = False
        self._skeleton_rows = []
        self._ping_thread = None
        self._endpoint_ping_thread = None
        self._speed_test_thread = None
        self._trace_thread = None
        self._dns_thread = None
        self._monitor_thread = None
        self._download_thread = None
        self._disconnect_thread = None
        self._watchdog_thread = None
        self._apps_view_mode = "routes"
        self._excluded_apps_set = set(self.config.get("excluded_apps", []))
        self._session_connected_at = None
        self._session_total_down_kb = 0.0
        self._session_total_up_kb = 0.0
        self._settings_dirty = False
        self._loading_settings = False

        self.sound_manager = SoundManager()
        self.toast_manager = ToastManager(self, self.sound_manager)

        self._log_emitter = LogSignalEmitter(self)
        self._log_emitter.log_signal.connect(self.log)
        self._log_handler = QtLogHandler(self._log_emitter)
        if not any(isinstance(h, QtLogHandler) for h in logger.handlers):
            logger.addHandler(self._log_handler)

        self.init_ui()
        self.load_settings_to_ui()
        self.apply_ui_level()
        self._wire_dirty_tracking()

        if not self.config.get("onboarding_done", False):
            QTimer.singleShot(100, self.run_setup_wizard)
        else:
            QTimer.singleShot(300, self.scan_apps)
            self.update_help_status()
            QTimer.singleShot(1000, self.check_dns_auto)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(3000)

        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.refresh_connections_monitor)
        self.monitor_timer.start(4000)

        action = self.config.get("autostart_action", "nothing")
        if action in ("connect", "connect_and_apps") and self.warp_cli_path:
            QTimer.singleShot(1200, self.start_warp)
            if action == "connect_and_apps":
                QTimer.singleShot(6000, lambda: self._launch_checked(self.config.get("selected_apps", [])))

        self.create_tray()

        self.speed_timer = QTimer(self)
        self.speed_timer.timeout.connect(self.update_speed)
        self.speed_timer.start(1000)
        self._last_rx = 0
        self._last_tx = 0

        self._start_ambient_background()

        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self.update_session_stats)
        self.session_timer.start(1000)

    # ---- background ----
    def _start_ambient_background(self):
        self._bg_phase = 0.0
        self._bg_timer = QTimer(self)
        self._bg_timer.setInterval(50)
        self._bg_timer.timeout.connect(self._advance_ambient_background)
        self._bg_timer.start()

    def _advance_ambient_background(self):
        self._bg_phase = (self._bg_phase + 0.006) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self._acrylic_enabled:
            gradient = QRadialGradient(self.width()/2, self.height()/2,
                                       max(self.width(), self.height())/2)
            gradient.setColorAt(0, QColor("#1A1A24"))
            gradient.setColorAt(1, QColor("#0D0D11"))
            painter.fillRect(self.rect(), gradient)

            phase = getattr(self, "_bg_phase", 0.0)
            w, h = self.width(), self.height()
            # accent blob
            accent_x = w * 0.5 + math.cos(phase) * w * 0.30
            accent_y = h * 0.35 + math.sin(phase * 0.8) * h * 0.22
            accent_glow = QRadialGradient(accent_x, accent_y, max(w, h) * 0.42)
            accent_c = QColor(C_ACCENT); accent_c.setAlpha(46)
            accent_c_out = QColor(C_ACCENT); accent_c_out.setAlpha(0)
            accent_glow.setColorAt(0, accent_c)
            accent_glow.setColorAt(1, accent_c_out)
            painter.fillRect(self.rect(), accent_glow)

            success_x = w * 0.5 - math.cos(phase * 0.7 + 2.1) * w * 0.28
            success_y = h * 0.7 - math.sin(phase * 0.9 + 1.3) * h * 0.24
            success_glow = QRadialGradient(success_x, success_y, max(w, h) * 0.36)
            success_c = QColor(C_SUCCESS); success_c.setAlpha(28)
            success_c_out = QColor(C_SUCCESS); success_c_out.setAlpha(0)
            success_glow.setColorAt(0, success_c)
            success_glow.setColorAt(1, success_c_out)
            painter.fillRect(self.rect(), success_glow)

            mask_color = QColor("#0D0D11")
            mask_color.setAlpha(200)
            painter.fillRect(self.rect(), mask_color)
        else:
            tint = QColor("#0D0D11")
            tint.setAlpha(120)
            painter.fillRect(self.rect(), tint)

        painter.setPen(QPen(QColor(C_BORDER), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        super().paintEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._acrylic_enabled:
            try:
                hwnd = int(self.winId())
                self._acrylic_enabled = enable_acrylic_blur(hwnd)
            except Exception:
                self._acrylic_enabled = False

    # ---- native resize ----
    def nativeEvent(self, eventType, message):
        if eventType == "windows_generic_MSG" or eventType == b"windows_generic_MSG":
            try:
                import ctypes.wintypes as wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    result = self._hit_test(msg.lParam)
                    if result is not None:
                        return True, result
            except:
                pass
        return super().nativeEvent(eventType, message)

    def _hit_test(self, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        global_pos = QPoint(x, y)
        local_pos = self.mapFromGlobal(global_pos)
        w, h = self.width(), self.height()
        bw = BORDER_WIDTH

        if not self.isMaximized():
            on_left = local_pos.x() < bw
            on_right = local_pos.x() > w - bw
            on_top = local_pos.y() < bw
            on_bottom = local_pos.y() > h - bw
            if on_top and on_left: return HTTOPLEFT
            if on_top and on_right: return HTTOPRIGHT
            if on_bottom and on_left: return HTBOTTOMLEFT
            if on_bottom and on_right: return HTBOTTOMRIGHT
            if on_left: return HTLEFT
            if on_right: return HTRIGHT
            if on_top: return HTTOP
            if on_bottom: return HTBOTTOM

        title_rect = self.title_bar.geometry()
        if title_rect.contains(local_pos):
            title_local = self.title_bar.mapFrom(self, local_pos)
            if self.title_bar.button_at(title_local):
                return None
            return HTCAPTION
        return None

    # ---- ui init ----
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.title_bar)

        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 14)
        content_layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self.tabs)
        self.tabs.addTab(self.create_quick_tab(), _t("quick"))
        self.tabs.addTab(self.create_proxy_tab(), _t("control"))
        self.tabs.addTab(self.create_apps_tab(), _t("apps"))
        self.tabs.addTab(self.create_stalzone_tab(), _t("stalzone"))
        self.tabs.addTab(self.create_settings_tab(), _t("settings"))
        self.tabs.addTab(self.create_help_tab(), _t("help"))

        main_layout.addWidget(content)
        self.status_bar = self.statusBar()
        self.status_bar.setStyleSheet(f"background-color: {C_CARD}; color: {C_MUTED};")

    # ---- helpers for tabs ----
    def _make_scrollable_tab(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        content_layout = QVBoxLayout(inner)
        content_layout.setContentsMargins(2, 2, 10, 2)
        content_layout.setSpacing(14)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return tab, content_layout

    # ---- quick tab ----
    def create_quick_tab(self):
        tab, layout = self._make_scrollable_tab()

        intro = QLabel(_t("quick_intro"))
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        card = QGroupBox("Connection")
        cl = QVBoxLayout(card)
        cl.setSpacing(12)

        status_row = QHBoxLayout()
        self.quick_status_indicator = StatusIndicator()
        status_row.addWidget(self.quick_status_indicator)
        self.quick_status_label = QLabel(_t("disconnected"))
        self.quick_status_label.setStyleSheet(f"color: {C_DANGER}; font-weight: 700; font-size: 18px;")
        self.quick_status_label.setWordWrap(True)
        status_row.addWidget(self.quick_status_label, stretch=1)
        status_row.addStretch()
        self.session_stats_label = QLabel("00:00:00  ·  0.0 MB")
        self.session_stats_label.setObjectName("Hint")
        status_row.addWidget(self.session_stats_label)
        cl.addLayout(status_row)

        big_row = QHBoxLayout()
        big_row.setSpacing(10)
        self.quick_connect_btn = SmoothButton(_t("connect"), base_color=C_ACCENT, hover_color=C_ACCENT_HOVER)
        self.quick_connect_btn.setMinimumHeight(46)
        self.quick_connect_btn.clicked.connect(self.start_warp)
        self.quick_disconnect_btn = SmoothButton(_t("disconnect"), base_color=C_DANGER, hover_color="#c0353c")
        self.quick_disconnect_btn.setMinimumHeight(46)
        self.quick_disconnect_btn.clicked.connect(self.stop_warp)
        self.quick_disconnect_btn.setEnabled(False)
        big_row.addWidget(self.quick_connect_btn, stretch=2)
        big_row.addWidget(self.quick_disconnect_btn, stretch=1)
        cl.addLayout(big_row)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(6)
        self.profiles_label = QLabel(_t("profiles_label"))
        self.profiles_label.setObjectName("Hint")
        profile_row.addWidget(self.profiles_label)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_combo, stretch=1)
        self.profile_save_btn = SmoothButton("💾", base_color="#2a2a2a", hover_color="#3a3a3a")
        self.profile_save_btn.setFixedWidth(40)
        self.profile_save_btn.setToolTip(_t("profiles_save_btn"))
        self.profile_save_btn.clicked.connect(self.save_current_profile)
        profile_row.addWidget(self.profile_save_btn)
        self.profile_delete_btn = SmoothButton("🗑", base_color="#2a2a2a", hover_color="#3a3a3a")
        self.profile_delete_btn.setFixedWidth(40)
        self.profile_delete_btn.setToolTip(_t("profiles_delete_btn"))
        self.profile_delete_btn.clicked.connect(self.delete_current_profile)
        profile_row.addWidget(self.profile_delete_btn)
        cl.addLayout(profile_row)
        self._refresh_profile_combo()

        hint = QLabel(_t("quick_hint"))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        cl.addWidget(hint)
        layout.addWidget(card)

        speed_group = QGroupBox(_t("speed"))
        sg_layout = QVBoxLayout(speed_group)

        labels_row = QHBoxLayout()
        labels_row.setSpacing(20)

        down_box = QHBoxLayout()
        down_box.addWidget(VectorIconLabel("download", C_CHART_DOWN, 16))
        self.download_label = QLabel("0.0 KB/s")
        self.download_label.setStyleSheet(f"color: {C_CHART_DOWN}; font-weight: 600; font-size: 14px;")
        down_box.addWidget(self.download_label)
        labels_row.addLayout(down_box)

        up_box = QHBoxLayout()
        up_box.addWidget(VectorIconLabel("upload", C_CHART_UP, 16))
        self.upload_label = QLabel("0.0 KB/s")
        self.upload_label.setStyleSheet(f"color: {C_CHART_UP}; font-weight: 600; font-size: 14px;")
        up_box.addWidget(self.upload_label)
        labels_row.addLayout(up_box)

        total_box = QHBoxLayout()
        total_box.addWidget(VectorIconLabel("signal", C_MUTED, 16))
        self.total_label = QLabel("0.0 KB/s")
        self.total_label.setStyleSheet(f"color: {C_MUTED}; font-weight: 600; font-size: 14px;")
        total_box.addWidget(self.total_label)
        labels_row.addLayout(total_box)
        labels_row.addStretch()

        sg_layout.addLayout(labels_row)
        self.sparkline = Sparkline()
        sg_layout.addWidget(self.sparkline)

        speed_test_row = QHBoxLayout()
        speed_test_row.setSpacing(10)
        self.speed_test_btn = SmoothButton(_t("speed_test_btn"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.speed_test_btn.clicked.connect(self.run_speed_test)
        speed_test_row.addWidget(self.speed_test_btn)
        self.speed_test_result_label = QLabel("")
        self.speed_test_result_label.setObjectName("Hint")
        speed_test_row.addWidget(self.speed_test_result_label, stretch=1)
        sg_layout.addLayout(speed_test_row)
        layout.addWidget(speed_group)

        layout.addStretch()
        return tab

    # ---- profiles ----
    def _refresh_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(_t("profiles_none"), None)
        for profile in self.config.get("profiles", []):
            self.profile_combo.addItem(profile.get("name", "?"), profile.get("name"))
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)

    def _current_profile_snapshot(self):
        return {
            "mode": self.mode_combo.currentText().split()[0] if self.mode_combo.count() else "warp",
            "region": self.region_combo.currentText(),
            "custom_endpoint": self.endpoint_edit.text().strip(),
            "system_proxy": self.sys_proxy_check.isChecked(),
            "kill_switch": self.kill_switch_check.isChecked(),
            "dns_server": self.dns_combo.currentData(),
            "stalzone_region": self.stalzone_region_combo.currentText(),
        }

    def save_current_profile(self):
        name, ok = QInputDialog.getText(self, _t("profiles_name_prompt_title"), _t("profiles_name_prompt_label"))
        name = (name or "").strip()
        if not ok or not name:
            return
        profiles = self.config.setdefault("profiles", [])
        snapshot = self._current_profile_snapshot()
        snapshot["name"] = name
        profiles[:] = [p for p in profiles if p.get("name") != name]
        profiles.append(snapshot)
        save_config(self.config)
        self._refresh_profile_combo()
        idx = self.profile_combo.findData(name)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self.toast_manager.show(_t("profiles_saved_toast") + name, "success")

    def delete_current_profile(self):
        name = self.profile_combo.currentData()
        if not name:
            return
        reply = QMessageBox.question(self, _t("profiles_delete_btn"), _t("profiles_delete_confirm") % name,
                                      QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        profiles = self.config.setdefault("profiles", [])
        profiles[:] = [p for p in profiles if p.get("name") != name]
        save_config(self.config)
        self._refresh_profile_combo()
        self.toast_manager.show(_t("profiles_deleted_toast") + name, "info")

    def _on_profile_selected(self, _index):
        name = self.profile_combo.currentData()
        if not name:
            return
        profile = next((p for p in self.config.get("profiles", []) if p.get("name") == name), None)
        if not profile:
            return
        self._apply_profile(profile)
        self.toast_manager.show(_t("profiles_applied_toast") + name, "success")

    def _apply_profile(self, profile):
        mode = profile.get("mode", "warp")
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemText(i).startswith(mode):
                self.mode_combo.setCurrentIndex(i)
                break
        region = profile.get("region", "auto")
        idx = self.region_combo.findText(region)
        if idx >= 0:
            self.region_combo.setCurrentIndex(idx)
        self.endpoint_edit.setText(profile.get("custom_endpoint", ""))
        self.sys_proxy_check.setChecked(profile.get("system_proxy", False))
        self.kill_switch_check.setChecked(profile.get("kill_switch", False))
        dns = profile.get("dns_server")
        if dns:
            idx = self.dns_combo.findData(dns)
            if idx >= 0:
                self.dns_combo.setCurrentIndex(idx)
        stalzone_region = profile.get("stalzone_region")
        if stalzone_region:
            self.stalzone_region_combo.setCurrentText(stalzone_region)

    # ---- control tab ----
    def create_proxy_tab(self):
        tab, layout = self._make_scrollable_tab()

        control_group = QGroupBox("WARP Control")
        cl = QVBoxLayout(control_group)
        cl.setSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(20)
        col1 = QVBoxLayout()
        hint1 = QLabel(_t("mode_label"))
        hint1.setObjectName("Hint")
        col1.addWidget(hint1)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([_t("mode_warp"), _t("mode_proxy")])
        self.mode_combo.setMinimumWidth(300)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        col1.addWidget(self.mode_combo)
        row1.addLayout(col1, stretch=2)

        col2 = QVBoxLayout()
        hint2 = QLabel(_t("port_label"))
        hint2.setObjectName("Hint")
        col2.addWidget(hint2)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(40000)
        self.port_spin.setMinimumWidth(100)
        col2.addWidget(self.port_spin)
        row1.addLayout(col2, stretch=1)
        cl.addLayout(row1)

        region_layout = QHBoxLayout()
        region_label = QLabel(_t("warp_region"))
        region_label.setObjectName("Hint")
        region_label.setMinimumWidth(90)
        region_layout.addWidget(region_label)
        self.region_combo = QComboBox()
        self.region_combo.addItems(["auto", "ru", "us", "eu"])
        region_layout.addWidget(self.region_combo)
        region_layout.addStretch()
        cl.addLayout(region_layout)

        self.endpoint_group = QWidget()
        eg = QVBoxLayout(self.endpoint_group)
        eg.setContentsMargins(0,0,0,0)
        endpoint_hint = QLabel(_t("endpoint_hint"))
        endpoint_hint.setObjectName("Hint")
        endpoint_hint.setWordWrap(True)
        eg.addWidget(endpoint_hint)
        ep_layout = QHBoxLayout()
        ep_layout.setSpacing(8)
        self.endpoint_combo = QComboBox()
        self.endpoint_combo.addItems(POPULAR_ENDPOINTS)
        self.endpoint_combo.currentTextChanged.connect(self.on_endpoint_selected)
        ep_layout.addWidget(self.endpoint_combo, stretch=1)
        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setPlaceholderText(_t("endpoint_placeholder"))
        ep_layout.addWidget(self.endpoint_edit, stretch=2)
        self.find_endpoint_btn = SmoothButton("⚡", base_color="#2a2a2a", hover_color="#3a3a3a")
        self.find_endpoint_btn.setFixedWidth(44)
        self.find_endpoint_btn.setToolTip("Find fastest WARP endpoint / Найти самый быстрый эндпоинт")
        self.find_endpoint_btn.clicked.connect(self.find_fastest_endpoint)
        ep_layout.addWidget(self.find_endpoint_btn)
        eg.addLayout(ep_layout)
        note = QLabel(_t("endpoint_note"))
        note.setObjectName("Hint")
        note.setWordWrap(True)
        eg.addWidget(note)

        plus_hint = QLabel(_t("warp_plus_info"))
        plus_hint.setObjectName("Hint")
        plus_hint.setWordWrap(True)
        eg.addWidget(plus_hint)
        plus_row = QHBoxLayout()
        plus_row.setSpacing(8)
        self.warp_plus_key_edit = QLineEdit()
        self.warp_plus_key_edit.setPlaceholderText(_t("warp_plus_placeholder"))
        plus_row.addWidget(self.warp_plus_key_edit, stretch=1)
        self.warp_plus_activate_btn = SmoothButton(_t("warp_plus_activate"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.warp_plus_activate_btn.clicked.connect(self.activate_warp_plus)
        plus_row.addWidget(self.warp_plus_activate_btn)
        eg.addLayout(plus_row)
        cl.addWidget(self.endpoint_group)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.start_btn = SmoothButton(_t("connect_warp"))
        self.start_btn.clicked.connect(self.start_warp)
        self.stop_btn = SmoothButton(_t("disconnect"), base_color=C_DANGER, hover_color="#c0353c")
        self.stop_btn.clicked.connect(self.stop_warp)
        self.stop_btn.setEnabled(False)
        row2.addWidget(self.start_btn)
        row2.addWidget(self.stop_btn)
        row2.addStretch()
        cl.addLayout(row2)

        status_row = QHBoxLayout()
        self.status_indicator = StatusIndicator()
        status_row.addWidget(self.status_indicator)
        self.status_label = QLabel(_t("disconnected"))
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, stretch=1)
        cl.addLayout(status_row)
        self.set_status_style("off", _t("disconnected"))

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        cl.addWidget(self.progress)
        layout.addWidget(control_group)

        kill_group = QGroupBox(_t("kill_switch_title"))
        self._kill_group_box = kill_group
        kl = QVBoxLayout(kill_group)
        self.kill_switch_check = ToggleSwitch(_t("kill_switch_label"))
        self.kill_switch_check.toggled.connect(self.toggle_kill_switch)
        kl.addWidget(self.kill_switch_check)
        self.kill_switch_info_label = QLabel(_t("kill_switch_info"))
        self.kill_switch_info_label.setObjectName("Hint")
        self.kill_switch_info_label.setWordWrap(True)
        kl.addWidget(self.kill_switch_info_label)
        layout.addWidget(kill_group)

        sys_group = QGroupBox(_t("sys_title"))
        self._sys_group_box = sys_group
        sl = QVBoxLayout(sys_group)
        self.sys_proxy_check = ToggleSwitch(_t("sys_check"))
        self.sys_proxy_check.toggled.connect(self.toggle_system_proxy)
        sl.addWidget(self.sys_proxy_check)
        self.sys_info_label = QLabel(_t("sys_info"))
        self.sys_info_label.setWordWrap(True)
        self.sys_info_label.setStyleSheet("color: #ff9aa8;")
        sl.addWidget(self.sys_info_label)
        self.sys_browser_info_label = QLabel(_t("help_text_browsers"))
        self.sys_browser_info_label.setObjectName("Hint")
        self.sys_browser_info_label.setWordWrap(True)
        sl.addWidget(self.sys_browser_info_label)
        layout.addWidget(sys_group)

        test_group = QGroupBox(_t("diagnostics"))
        test_layout = QVBoxLayout(test_group)
        test_btn_row = QHBoxLayout()
        test_btn_row.setSpacing(8)
        self.test_btn = SmoothButton(_t("check_ip"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.test_btn.clicked.connect(self.test_proxy)
        test_btn_row.addWidget(self.test_btn)
        self.leak_test_btn = SmoothButton(_t("leak_test"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.leak_test_btn.clicked.connect(self.run_leak_test)
        test_btn_row.addWidget(self.leak_test_btn)
        test_layout.addLayout(test_btn_row)
        layout.addWidget(test_group)

        log_group = QGroupBox(_t("log_title"))
        ll = QVBoxLayout(log_group)
        self.log_text = SmoothTextEdit()
        self.log_text.setMinimumHeight(220)
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        ll.addWidget(self.log_text)
        layout.addWidget(log_group, stretch=1)
        return tab

    def on_endpoint_selected(self, text):
        if text:
            self.endpoint_edit.setText(text)

    def activate_warp_plus(self):
        key = self.warp_plus_key_edit.text().strip()
        if not key:
            return
        if not self.warp_cli_path:
            self.toast_manager.show(_t("warp_not_installed"), "warn")
            return
        self.warp_plus_activate_btn.setEnabled(False)
        try:
            result = subprocess.run([self.warp_cli_path, "registration", "license", key],
                                     capture_output=True, text=True, timeout=15,
                                     creationflags=CREATE_NO_WINDOW, check=False)
            if result.returncode == 0:
                self.config["warp_plus_key"] = key
                save_config(self.config)
                self.log("WARP+ license activated", "SUCCESS")
                self.toast_manager.show(_t("warp_plus_success"), "success")
            else:
                err = (result.stderr or result.stdout or "unknown error").strip()
                self.toast_manager.show(_t("warp_plus_fail") + err, "error")
        except Exception as e:
            self.toast_manager.show(_t("warp_plus_fail") + str(e), "error")
        finally:
            self.warp_plus_activate_btn.setEnabled(True)

    def run_speed_test(self):
        if self._speed_test_thread and self._speed_test_thread.isRunning():
            return
        mode = self.mode_combo.currentText().split()[0] if self.mode_combo.count() else "warp"
        self.speed_test_btn.setEnabled(False)
        self.speed_test_result_label.setText(_t("speed_test_running"))
        self._speed_test_thread = SpeedTestThread(mode, self.port_spin.value())
        self._speed_test_thread.result_signal.connect(self._on_speed_test_result)
        self._speed_test_thread.error_signal.connect(self._on_speed_test_error)
        self._speed_test_thread.start()

    def _on_speed_test_result(self, mbps):
        self.speed_test_btn.setEnabled(True)
        self.speed_test_result_label.setText(_t("speed_test_result") % mbps)
        self.log(f"Speed test: {mbps:.1f} Mbps", "SUCCESS")

    def _on_speed_test_error(self, error):
        self.speed_test_btn.setEnabled(True)
        self.speed_test_result_label.setText("")
        self.toast_manager.show(_t("speed_test_fail") + error, "error")

    def find_fastest_endpoint(self):
        if self._endpoint_ping_thread and self._endpoint_ping_thread.isRunning():
            return
        self.find_endpoint_btn.setEnabled(False)
        self.toast_manager.show("Проверка эндпоинтов WARP..." if _current_lang == "ru" else "Testing WARP endpoints...", "info")
        self._endpoint_ping_thread = EndpointPingThread(POPULAR_ENDPOINTS)
        self._endpoint_ping_thread.result_signal.connect(self._on_endpoint_ping_result)
        self._endpoint_ping_thread.start()

    def _on_endpoint_ping_result(self, results):
        self.find_endpoint_btn.setEnabled(True)
        best, best_ms = None, float("inf")
        for ep, ms in results.items():
            if ms is not None and ms < best_ms:
                best_ms, best = ms, ep
        if best:
            idx = self.endpoint_combo.findText(best)
            if idx >= 0:
                self.endpoint_combo.setCurrentIndex(idx)
            self.endpoint_edit.setText(best)
            self.toast_manager.show(f"{best} ({best_ms} ms)", "success")
            self.log(f"Fastest endpoint: {best} ({best_ms} ms)", "SUCCESS")
        else:
            self.toast_manager.show("Не удалось измерить пинг ни до одного эндпоинта" if _current_lang == "ru"
                                     else "Could not ping any endpoint", "warn")

    # ---- apps tab ----
    def create_apps_tab(self):
        tab, layout = self._make_scrollable_tab()

        self.apps_title_label = QLabel(_t("apps_title"))
        self.apps_title_label.setObjectName("Title")
        layout.addWidget(self.apps_title_label)

        seg_row = QHBoxLayout()
        seg_row.setSpacing(0)
        seg_wrap = QWidget()
        seg_wrap.setStyleSheet(f"background-color:{C_INPUT}; border-radius:8px;")
        seg_inner = QHBoxLayout(seg_wrap)
        seg_inner.setContentsMargins(3,3,3,3)
        seg_inner.setSpacing(2)
        self.apps_seg_group = QButtonGroup(self)
        self.apps_seg_group.setExclusive(True)
        self.seg_routes_btn = QPushButton(_t("apps_view_routes"))
        self.seg_exceptions_btn = QPushButton(_t("apps_view_exceptions"))
        self.seg_monitor_btn = QPushButton(_t("apps_view_monitor"))
        seg_style = f"""
            QPushButton {{
                background: transparent; color: {C_MUTED}; border: none;
                border-radius: 6px; padding: 7px 16px; font-weight: 600;
            }}
            QPushButton:checked {{ background-color: {C_ACCENT}; color: white; }}
            QPushButton:hover:!checked {{ background-color: #2a2a2a; }}
        """
        for i, btn in enumerate((self.seg_routes_btn, self.seg_exceptions_btn, self.seg_monitor_btn)):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(seg_style)
            self.apps_seg_group.addButton(btn, i)
            seg_inner.addWidget(btn)
        self.seg_routes_btn.setChecked(True)
        seg_row.addWidget(seg_wrap)
        seg_row.addStretch()
        layout.addLayout(seg_row)
        self.apps_seg_group.buttonClicked[int].connect(self._on_apps_view_changed)

        self.apps_info_label = QLabel(_t("apps_info"))
        self.apps_info_label.setObjectName("Hint")
        self.apps_info_label.setWordWrap(True)
        layout.addWidget(self.apps_info_label)

        self.apps_search_row = QWidget()
        search_layout = QHBoxLayout(self.apps_search_row)
        search_layout.setContentsMargins(0,0,0,0)
        search_layout.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_t("search_placeholder"))
        self.search_edit.textChanged.connect(self.filter_apps)
        search_layout.addWidget(self.search_edit, stretch=2)
        self.category_combo = QComboBox()
        self.category_combo.addItem(_t("all_categories"))
        self.category_combo.addItems([_t("cat_games"), _t("cat_browsers"), _t("cat_messengers"),
                                      _t("cat_office"), _t("cat_dev"), _t("cat_media"), _t("cat_other")])
        self.category_combo.setMinimumWidth(190)
        self.category_combo.currentTextChanged.connect(self.filter_apps)
        search_layout.addWidget(self.category_combo, stretch=1)
        layout.addWidget(self.apps_search_row)

        self.apps_list = SmoothListWidget()
        self.apps_list.setIconSize(QSize(28,28))
        self.apps_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.apps_list.setMinimumHeight(260)
        self.apps_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.apps_list.customContextMenuRequested.connect(self._show_apps_context_menu)
        self.apps_list.itemChanged.connect(self._on_apps_item_changed)
        layout.addWidget(self.apps_list, stretch=1)

        self.monitor_list = SmoothListWidget()
        self.monitor_list.setMinimumHeight(260)
        self.monitor_list.setVisible(False)
        layout.addWidget(self.monitor_list, stretch=1)

        self.split_tunnel_widget = QWidget()
        self.split_tunnel_widget.setVisible(False)
        st_layout = QVBoxLayout(self.split_tunnel_widget)
        st_layout.setContentsMargins(0,0,0,0)
        st_layout.setSpacing(8)
        st_input_row = QHBoxLayout()
        st_input_row.setSpacing(8)
        self.split_tunnel_type_combo = QComboBox()
        self.split_tunnel_type_combo.addItem(_t("split_tunnel_type_domain"), "host")
        self.split_tunnel_type_combo.addItem(_t("split_tunnel_type_ip"), "ip")
        st_input_row.addWidget(self.split_tunnel_type_combo)
        self.split_tunnel_edit = QLineEdit()
        self.split_tunnel_edit.setPlaceholderText(_t("split_tunnel_placeholder"))
        st_input_row.addWidget(self.split_tunnel_edit, stretch=1)
        self.split_tunnel_add_btn = SmoothButton(_t("add"))
        self.split_tunnel_add_btn.clicked.connect(self.add_split_tunnel_entry)
        st_input_row.addWidget(self.split_tunnel_add_btn)
        st_layout.addLayout(st_input_row)
        self.split_tunnel_list = SmoothListWidget()
        self.split_tunnel_list.setMinimumHeight(220)
        self.split_tunnel_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.split_tunnel_list.customContextMenuRequested.connect(self._show_split_tunnel_context_menu)
        st_layout.addWidget(self.split_tunnel_list, stretch=1)
        layout.addWidget(self.split_tunnel_widget, stretch=1)

        self._apps_toolbar_row = QHBoxLayout()
        self._apps_toolbar_row.setSpacing(8)
        self.rescan_btn = SmoothButton(_t("refresh_list"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.rescan_btn.clicked.connect(self.scan_apps)
        self._apps_toolbar_row.addWidget(self.rescan_btn)
        self._apps_toolbar_row.addStretch()
        self.launch_selected_btn = SmoothButton(_t("launch_checked"), base_color=C_SUCCESS, hover_color="#369b6d")
        self.launch_selected_btn.clicked.connect(self.launch_checked_apps)
        self._apps_toolbar_row.addWidget(self.launch_selected_btn)
        layout.addLayout(self._apps_toolbar_row)

        self.add_group_box = QGroupBox(_t("add_manual"))
        al = QHBoxLayout(self.add_group_box)
        al.setSpacing(8)
        self.exe_path_edit = QLineEdit()
        self.exe_path_edit.setPlaceholderText(_t("exe_placeholder"))
        al.addWidget(self.exe_path_edit, stretch=1)
        self.browse_exe_btn = SmoothButton(_t("browse"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.browse_exe_btn.clicked.connect(self.browse_exe)
        self.add_app_btn = SmoothButton(_t("add"))
        self.add_app_btn.clicked.connect(self.add_manual_app)
        al.addWidget(self.browse_exe_btn)
        al.addWidget(self.add_app_btn)
        layout.addWidget(self.add_group_box)

        self._apply_apps_view_mode()
        return tab

    def _on_apps_view_changed(self, view_id):
        self._apps_view_mode = ("routes", "exceptions", "monitor")[view_id]
        self._apply_apps_view_mode()

    def _current_mode_key(self):
        return self.mode_combo.currentText().split()[0] if self.mode_combo.count() else "warp"

    def _apply_apps_view_mode(self):
        mode = self._apps_view_mode
        is_monitor = (mode == "monitor")
        is_warp_mode = self._current_mode_key() == "warp"
        is_split_tunnel = (mode == "exceptions" and is_warp_mode)
        show_apps_list = not is_monitor and not is_split_tunnel

        self.apps_search_row.setVisible(show_apps_list)
        self.apps_list.setVisible(show_apps_list)
        self.monitor_list.setVisible(is_monitor)
        self.split_tunnel_widget.setVisible(is_split_tunnel)
        self.rescan_btn.setVisible(show_apps_list)
        self.launch_selected_btn.setVisible(mode == "routes")
        self.add_group_box.setVisible(show_apps_list)

        if mode == "exceptions":
            self.apps_info_label.setText(_t("split_tunnel_info") if is_warp_mode else _t("exceptions_info"))
        else:
            self.apps_info_label.setText(_t("apps_info"))

        if is_split_tunnel:
            self._refresh_split_tunnel_list()
        elif show_apps_list:
            self.populate_apps_list(self.search_edit.text().strip(), self.category_combo.currentText())
        else:
            self.refresh_connections_monitor()

    # ---- split tunnel ----
    def _apply_split_tunnel_cli(self, entry_type, value, add):
        if not self.warp_cli_path:
            return False
        sub_cmd = "host" if entry_type == "host" else "ip"
        action = "add" if add else "remove"
        try:
            result = subprocess.run([self.warp_cli_path, "tunnel", sub_cmd, action, value],
                                     capture_output=True, text=True, timeout=8,
                                     creationflags=CREATE_NO_WINDOW, check=False)
            return result.returncode == 0
        except Exception:
            return False

    def add_split_tunnel_entry(self):
        value = self.split_tunnel_edit.text().strip()
        if not value:
            return
        entry_type = self.split_tunnel_type_combo.currentData()
        entries = self.config.setdefault("split_tunnel_entries", [])
        if any(e["type"] == entry_type and e["value"] == value for e in entries):
            self.toast_manager.show(_t("app_exists"), "info")
            return
        entries.append({"type": entry_type, "value": value})
        save_config(self.config)
        self.split_tunnel_edit.clear()
        self._refresh_split_tunnel_list()
        ok = self._apply_split_tunnel_cli(entry_type, value, add=True)
        if ok:
            self.log(f"Split-tunnel: added {entry_type}={value}", "SUCCESS")
            self.toast_manager.show(_t("split_tunnel_added") + value, "success")
        else:
            self.log(f"Split-tunnel: CLI rejected {entry_type}={value} (saved locally)", "WARN")
            self.toast_manager.show(_t("split_tunnel_apply_fail"), "warn")

    def _refresh_split_tunnel_list(self):
        self.split_tunnel_list.clear()
        entries = self.config.get("split_tunnel_entries", [])
        if not entries:
            item = QListWidgetItem(_t("split_tunnel_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.split_tunnel_list.addItem(item)
            return
        for e in entries:
            type_label = _t("split_tunnel_type_domain") if e["type"] == "host" else _t("split_tunnel_type_ip")
            item = QListWidgetItem(f"{type_label}:   {e['value']}")
            item.setData(Qt.UserRole, e)
            self.split_tunnel_list.addItem(item)

    def _show_split_tunnel_context_menu(self, pos):
        item = self.split_tunnel_list.itemAt(pos)
        if not item:
            return
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        menu = QMenu(self)
        remove_action = menu.addAction(_t("ctx_remove_exception"))
        remove_action.triggered.connect(lambda: self._remove_split_tunnel_entry(entry))
        menu.exec_(self.split_tunnel_list.viewport().mapToGlobal(pos))

    def _remove_split_tunnel_entry(self, entry):
        entries = self.config.setdefault("split_tunnel_entries", [])
        entries[:] = [e for e in entries if not (e["type"] == entry["type"] and e["value"] == entry["value"])]
        save_config(self.config)
        self._apply_split_tunnel_cli(entry["type"], entry["value"], add=False)
        self._refresh_split_tunnel_list()
        self.toast_manager.show(_t("split_tunnel_removed") + entry["value"], "info")

    def _reapply_split_tunnel_entries(self):
        for e in self.config.get("split_tunnel_entries", []):
            self._apply_split_tunnel_cli(e["type"], e["value"], add=True)

    # ---- monitor ----
    def refresh_connections_monitor(self):
        if not hasattr(self, "monitor_list"):
            return
        if self._apps_view_mode != "monitor":
            return
        if self._monitor_thread and self._monitor_thread.isRunning():
            return
        self._monitor_thread = ConnectionsMonitorThread(self.port_spin.value())
        self._monitor_thread.result_signal.connect(self._on_monitor_result)
        self._monitor_thread.error_signal.connect(lambda e: self.log(_t("monitor_scan_fail") + e, "WARN"))
        self._monitor_thread.start()

    def _on_monitor_result(self, rows):
        if self._apps_view_mode != "monitor":
            return
        self.monitor_list.clear()
        if not self.is_running or self.mode_combo.currentText().split()[0] != "proxy":
            item = QListWidgetItem(_t("monitor_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.monitor_list.addItem(item)
            return
        if not rows:
            item = QListWidgetItem(_t("monitor_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.monitor_list.addItem(item)
            return
        for pid, name, addr in rows:
            self.monitor_list.addItem(QListWidgetItem(f"{pid:<8}{name:<28}{addr}"))

    # ---- kill switch ----
    def toggle_kill_switch(self, checked):
        if checked and not is_admin():
            reply = QMessageBox.question(self, _t("admin_required"), _t("kill_switch_admin_q"),
                                          QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.close()
                run_as_admin()
            else:
                self.kill_switch_check.setChecked(False)
            return
        self.kill_switch_enabled = checked
        if not checked:
            remove_kill_switch_rule()
        self.log("Kill Switch " + ("enabled" if checked else "disabled"), "INFO")

    def _apply_kill_switch(self):
        if self.kill_switch_enabled:
            apply_kill_switch_rule()
            self.log("Kill Switch: internet traffic blocked.", "WARN")
            self.toast_manager.show(_t("kill_switch_blocked_toast"), "warn")

    # ---- leak test ----
    def run_leak_test(self):
        if not self.is_running:
            self.toast_manager.show(_t("connect_first"), "warn")
            return
        if self._trace_thread and self._trace_thread.isRunning():
            return
        mode = self.mode_combo.currentText().split()[0]
        self.leak_test_btn.setEnabled(False)
        self.leak_test_btn.setText(_t("leak_test_running"))
        self._trace_thread = TraceCheckThread(mode, self.port_spin.value())
        self._trace_thread.result_signal.connect(self._on_leak_test_result)
        self._trace_thread.error_signal.connect(self._on_leak_test_error)
        self._trace_thread.start()

    def _reset_leak_btn(self):
        self.leak_test_btn.setEnabled(True)
        self.leak_test_btn.setText(_t("leak_test"))

    def _on_leak_test_result(self, data):
        self._reset_leak_btn()
        warp_flag = data.get("warp", "off").lower()
        ip = data.get("ip", "?")
        loc = data.get("loc", "?")
        if warp_flag in ("on", "plus"):
            self.log(f"Leak test OK: IP={ip}, country={loc}, warp={warp_flag}", "SUCCESS")
            self.toast_manager.show(_t("leak_test_ok"), "success")
        else:
            self.log(f"Leak test WARNING: warp={warp_flag}, IP={ip}", "WARN")
            self.toast_manager.show(_t("leak_test_warn"), "warn")

    def _on_leak_test_error(self, error):
        self._reset_leak_btn()
        self.log(f"Leak test error: {error}", "ERROR")
        self.toast_manager.show(_t("leak_test_fail") + error, "error")

    # ---- stalzone ----
    def create_stalzone_tab(self):
        tab, layout = self._make_scrollable_tab()

        group = QGroupBox(_t("stalzone_title"))
        gl = QVBoxLayout(group)

        info = QLabel(_t("stalzone_info"))
        info.setObjectName("Hint")
        info.setWordWrap(True)
        gl.addWidget(info)

        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        path_label = QLabel(_t("game_path"))
        path_label.setMinimumWidth(90)
        path_layout.addWidget(path_label)
        self.stalzone_path_edit = QLineEdit()
        self.stalzone_path_edit.setPlaceholderText(_t("stalzone_placeholder"))
        path_layout.addWidget(self.stalzone_path_edit, stretch=1)
        browse_stalzone_btn = SmoothButton(_t("browse"), base_color="#2a2a2a", hover_color="#3a3a3a")
        browse_stalzone_btn.clicked.connect(self.browse_stalzone_folder)
        path_layout.addWidget(browse_stalzone_btn)
        gl.addLayout(path_layout)

        find_btn = SmoothButton(_t("auto_find"), base_color="#2a2a2a", hover_color="#3a3a3a")
        find_btn.clicked.connect(self.find_stalzone_auto)
        gl.addWidget(find_btn)

        region_layout = QHBoxLayout()
        region_layout.setSpacing(8)
        region_label = QLabel(_t("select_region"))
        region_label.setMinimumWidth(120)
        region_layout.addWidget(region_label)
        self.stalzone_region_combo = QComboBox()
        self.stalzone_region_combo.addItems(["RU", "EU", "NA"])
        self.stalzone_region_combo.setMinimumWidth(120)
        region_layout.addWidget(self.stalzone_region_combo)
        region_layout.addStretch()
        gl.addLayout(region_layout)

        ping_btn = SmoothButton(_t("check_ping"), base_color="#2a2a2a", hover_color="#3a3a3a")
        ping_btn.clicked.connect(self.check_stalzone_ping)
        gl.addWidget(ping_btn)

        apply_btn = SmoothButton(_t("apply_region"), base_color=C_SUCCESS, hover_color="#369b6d")
        apply_btn.clicked.connect(self.apply_stalzone_region)
        gl.addWidget(apply_btn)

        status_label = QLabel(_t("stalzone_status"))
        status_label.setObjectName("Hint")
        status_label.setWordWrap(True)
        self.stalzone_status_label = status_label
        gl.addWidget(status_label)

        layout.addWidget(group)
        layout.addStretch()
        return tab

    def check_stalzone_ping(self):
        if self._ping_thread and self._ping_thread.isRunning():
            return
        self.log(_t("stalzone_ping_start"), "INFO")
        self._ping_thread = PingThread(REGION_HOSTS)
        self._ping_thread.result_signal.connect(self._on_ping_result)
        self._ping_thread.start()

    def _on_ping_result(self, results):
        best, min_ms = None, float("inf")
        for region, ms in results.items():
            if ms is not None:
                self.log(_t("stalzone_ping_result") % (region, ms), "INFO")
                if ms < min_ms:
                    min_ms, best = ms, region
            else:
                self.log(_t("stalzone_ping_unavailable") % region, "WARN")
        if best:
            index = self.stalzone_region_combo.findText(best)
            if index >= 0:
                self.stalzone_region_combo.setCurrentIndex(index)
                self.stalzone_region_combo.setStyleSheet(f"QComboBox {{ color: {C_SUCCESS}; }}")
                QTimer.singleShot(3000, lambda: self.stalzone_region_combo.setStyleSheet(""))
            self.toast_manager.show(_t("stalzone_fastest") % (best, min_ms), "success")
        else:
            self.toast_manager.show(_t("stalzone_ping_fail"), "warn")

    def browse_stalzone_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select STALZONE game folder")
        if path:
            self.stalzone_path_edit.setText(path)
            self.update_stalzone_status()

    def find_stalzone_auto(self):
        paths = find_stalzone_paths()
        if paths:
            self.stalzone_path_edit.setText(paths[0])
            self.update_stalzone_status()
            self.log(_t("stalzone_game_found") + paths[0], "SUCCESS")
            self.toast_manager.show(_t("stalzone_game_found"), "success")
        else:
            self.toast_manager.show(_t("stalzone_game_not_found"), "warn")
            self.log("Auto-search for STALZONE gave no results", "WARN")

    def update_stalzone_status(self):
        path = self.stalzone_path_edit.text().strip()
        if path and os.path.isdir(path):
            file_path = os.path.join(path, "sc_forced_realm")
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    self.stalzone_status_label.setText(_t("stalzone_file_exists") + (content or _t("stalzone_file_empty")))
                except Exception:
                    self.stalzone_status_label.setText(_t("stalzone_file_read_error"))
            else:
                self.stalzone_status_label.setText(_t("stalzone_file_missing"))
        else:
            self.stalzone_status_label.setText(_t("stalzone_path_set"))

    def apply_stalzone_region(self):
        path = self.stalzone_path_edit.text().strip()
        if not path:
            self.toast_manager.show(_t("stalzone_path_set"), "warn")
            return
        if not os.path.isdir(path):
            self.toast_manager.show("Folder does not exist.", "error")
            return
        region = self.stalzone_region_combo.currentText()
        file_path = os.path.join(path, "sc_forced_realm")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(region)
            self.log(_t("stalzone_file_created") % (path, region), "SUCCESS")
            self.update_stalzone_status()
            self.toast_manager.show(_t("stalzone_apply_success") % region, "success")
        except Exception as e:
            self.toast_manager.show(_t("stalzone_file_fail") + str(e), "error")
            self.log(f"Region file error: {e}", "ERROR")

    # ---- settings tab ----
    def create_settings_tab(self):
        tab = QWidget()
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(0,0,0,0)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(12)

        gen_group = QGroupBox(_t("settings_connection"))
        gl = QVBoxLayout(gen_group)
        self.auto_reconnect_check = ToggleSwitch(_t("auto_reconnect"))
        gl.addWidget(self.auto_reconnect_check)

        dns_layout = QHBoxLayout()
        dns_layout.setSpacing(8)
        dns_label = QLabel(_t("dns_label"))
        dns_label.setObjectName("Hint")
        dns_label.setMinimumWidth(90)
        dns_layout.addWidget(dns_label)
        self.dns_combo = QComboBox()
        for server, desc in DNS_SERVERS:
            self.dns_combo.addItem(f"{server} ({desc})", server)
        self.dns_combo.setMinimumWidth(220)
        self.dns_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dns_layout.addWidget(self.dns_combo)
        dns_auto_btn = SmoothButton(_t("auto_dns_btn"), base_color="#2a2a2a", hover_color="#3a3a3a")
        dns_auto_btn.clicked.connect(self.check_dns_auto)
        dns_layout.addWidget(dns_auto_btn)
        gl.addLayout(dns_layout)
        dns_desc = QLabel(_t("dns_description"))
        dns_desc.setObjectName("Hint")
        dns_desc.setWordWrap(True)
        gl.addWidget(dns_desc)
        layout.addWidget(gen_group)

        tools_group = QGroupBox(_t("utilities"))
        self._tools_group_box = tools_group
        tl = QVBoxLayout(tools_group)
        tl.setSpacing(8)
        self.flush_dns_btn = SmoothButton(_t("flush_dns"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.flush_dns_btn.clicked.connect(self.flush_dns)
        self.clear_proxy_btn = SmoothButton(_t("clear_proxy"), base_color=C_DANGER, hover_color="#c0353c")
        self.clear_proxy_btn.clicked.connect(self.clear_proxy_settings)
        tl.addWidget(self.flush_dns_btn)
        tl.addWidget(self.clear_proxy_btn)
        layout.addWidget(tools_group)

        family_group = QGroupBox(_t("family_filter_title"))
        self._family_group_box = family_group
        fl = QVBoxLayout(family_group)
        self.family_filter_info_label = QLabel(_t("family_filter_info"))
        self.family_filter_info_label.setObjectName("Hint")
        self.family_filter_info_label.setWordWrap(True)
        fl.addWidget(self.family_filter_info_label)
        family_row = QHBoxLayout()
        family_row.setSpacing(8)
        self.family_filter_combo = QComboBox()
        self.family_filter_combo.addItem(_t("family_filter_off"), "off")
        self.family_filter_combo.addItem(_t("family_filter_malware"), "malware")
        self.family_filter_combo.addItem(_t("family_filter_full"), "full")
        family_row.addWidget(self.family_filter_combo, stretch=1)
        self.family_filter_apply_btn = SmoothButton(_t("family_filter_apply"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.family_filter_apply_btn.clicked.connect(self.apply_family_filter)
        family_row.addWidget(self.family_filter_apply_btn)
        fl.addLayout(family_row)
        layout.addWidget(family_group)

        notif_group = QGroupBox(_t("sound_enabled_label"))
        ngl = QVBoxLayout(notif_group)
        self.sound_enabled_check = ToggleSwitch(_t("sound_enabled_label"))
        self.sound_enabled_check.setChecked(True)
        self.sound_enabled_check.toggled.connect(self.on_sound_toggled)
        ngl.addWidget(self.sound_enabled_check)
        sound_info = QLabel(_t("sound_enabled_info"))
        sound_info.setObjectName("Hint")
        sound_info.setWordWrap(True)
        ngl.addWidget(sound_info)
        layout.addWidget(notif_group)

        diag_group = QGroupBox(_t("diag_export_title"))
        dgl = QVBoxLayout(diag_group)
        diag_info = QLabel(_t("diag_export_info"))
        diag_info.setObjectName("Hint")
        diag_info.setWordWrap(True)
        dgl.addWidget(diag_info)
        diag_btn_row = QHBoxLayout()
        diag_btn_row.setSpacing(8)
        self.diag_export_btn = SmoothButton(_t("diag_export_btn"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.diag_export_btn.clicked.connect(self.export_diagnostics)
        diag_btn_row.addWidget(self.diag_export_btn)
        self.diag_copy_btn = SmoothButton(_t("diag_copy_btn"), base_color="#2a2a2a", hover_color="#3a3a3a")
        self.diag_copy_btn.clicked.connect(self.copy_diagnostics_to_clipboard)
        diag_btn_row.addWidget(self.diag_copy_btn)
        dgl.addLayout(diag_btn_row)
        layout.addWidget(diag_group)

        auto_group = QGroupBox(_t("autostart"))
        agl = QVBoxLayout(auto_group)
        self.autostart_check = ToggleSwitch(_t("autostart_check"))
        self.autostart_check.toggled.connect(self.on_autostart_toggled)
        agl.addWidget(self.autostart_check)

        action_hint = QLabel(_t("autostart_action"))
        action_hint.setObjectName("Hint")
        agl.addWidget(action_hint)
        self.autostart_action_group = QButtonGroup(self)
        self.autostart_action_nothing = QRadioButton(_t("autostart_nothing"))
        self.autostart_action_connect = QRadioButton(_t("autostart_connect"))
        self.autostart_action_connect_apps = QRadioButton(_t("autostart_connect_apps"))
        for rb in (self.autostart_action_nothing, self.autostart_action_connect, self.autostart_action_connect_apps):
            self.autostart_action_group.addButton(rb)
            agl.addWidget(rb)
        self.autostart_action_nothing.setChecked(True)
        self.autostart_default_note_label = QLabel(_t("autostart_default_note"))
        self.autostart_default_note_label.setObjectName("Hint")
        self.autostart_default_note_label.setWordWrap(True)
        agl.addWidget(self.autostart_default_note_label)
        layout.addWidget(auto_group)

        ui_group = QGroupBox(_t("interface"))
        ugl = QVBoxLayout(ui_group)
        lvl_layout = QHBoxLayout()
        lvl_layout.setSpacing(8)
        lvl_label = QLabel(_t("ui_level"))
        lvl_label.setObjectName("Hint")
        lvl_label.setMinimumWidth(140)
        lvl_layout.addWidget(lvl_label)
        self.ui_level_combo = QComboBox()
        self.ui_level_combo.addItems(["simple", "advanced"])
        self.ui_level_combo.currentTextChanged.connect(lambda _: self.apply_ui_level())
        self.ui_level_combo.setMinimumWidth(140)
        lvl_layout.addWidget(self.ui_level_combo)
        lvl_layout.addStretch()
        ugl.addLayout(lvl_layout)

        lang_layout = QHBoxLayout()
        lang_label = QLabel(_t("lang_label"))
        lang_label.setObjectName("Hint")
        lang_label.setMinimumWidth(140)
        lang_layout.addWidget(lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["ru", "en"])
        self.lang_combo.currentTextChanged.connect(self.on_language_changed)
        lang_layout.addWidget(self.lang_combo)
        lang_layout.addStretch()
        ugl.addLayout(lang_layout)

        ui_hint = QLabel(_t("ui_hint_simple") + "\n" + _t("ui_hint_advanced"))
        ui_hint.setObjectName("Hint")
        ui_hint.setWordWrap(True)
        ugl.addWidget(ui_hint)
        layout.addWidget(ui_group)

        reset_group = QGroupBox(_t("reset"))
        rl = QVBoxLayout(reset_group)
        reset_btn = SmoothButton(_t("reset_btn"), base_color=C_DANGER, hover_color="#c0353c")
        reset_btn.clicked.connect(self.reset_config)
        rl.addWidget(reset_btn)
        reset_hint = QLabel(_t("reset_info"))
        reset_hint.setWordWrap(True)
        reset_hint.setObjectName("Hint")
        rl.addWidget(reset_hint)
        layout.addWidget(reset_group)

        save_btn = SmoothButton(_t("save_settings"), base_color=C_SUCCESS, hover_color="#369b6d")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setFixedHeight(42)
        layout.addWidget(save_btn)
        layout.addStretch()

        scroll.setWidget(inner)
        outer_layout.addWidget(scroll)
        return tab

    def on_language_changed(self, lang):
        if lang not in STRINGS:
            return
        set_language(lang)
        self.tabs.setTabText(0, _t("quick"))
        self.tabs.setTabText(1, _t("control"))
        self.tabs.setTabText(2, _t("apps"))
        self.tabs.setTabText(3, _t("stalzone"))
        self.tabs.setTabText(4, _t("settings"))
        self.tabs.setTabText(5, _t("help"))
        self.set_status_style(self.status_indicator._status, _t("connected") if self.is_running else _t("disconnected"))
        self.quick_status_label.setText(_t("connected") if self.is_running else _t("disconnected"))

        self.quick_connect_btn.setText(_t("connect"))
        self.quick_disconnect_btn.setText(_t("disconnect"))
        self.start_btn.setText(_t("connect_warp"))
        self.stop_btn.setText(_t("disconnect"))
        self.test_btn.setText(_t("check_ip") if not self.test_btn.text() == _t("checking") else self.test_btn.text())
        self.speed_test_btn.setText(_t("speed_test_btn"))
        self.rescan_btn.setText(_t("refresh_list"))
        self.launch_selected_btn.setText(_t("launch_checked"))
        self.apps_title_label.setText(_t("apps_title"))
        self.seg_routes_btn.setText(_t("apps_view_routes"))
        self.seg_exceptions_btn.setText(_t("apps_view_exceptions"))
        self.seg_monitor_btn.setText(_t("apps_view_monitor"))
        self.apps_info_label.setText(_t("exceptions_info") if self._apps_view_mode == "exceptions" else _t("apps_info"))
        self.search_edit.setPlaceholderText(_t("search_placeholder"))
        self.add_group_box.setTitle(_t("add_manual"))
        self.exe_path_edit.setPlaceholderText(_t("exe_placeholder"))
        self.browse_exe_btn.setText(_t("browse"))
        self.add_app_btn.setText(_t("add"))

        self.sys_proxy_check.setText(_t("sys_check"))
        self.sys_info_label.setText(_t("sys_info"))
        self.sys_browser_info_label.setText(_t("help_text_browsers"))
        self._sys_group_box.setTitle(_t("sys_title"))
        self._tools_group_box.setTitle(_t("utilities"))
        self.flush_dns_btn.setText(_t("flush_dns"))
        self.clear_proxy_btn.setText(_t("clear_proxy"))
        self._family_group_box.setTitle(_t("family_filter_title"))
        self.family_filter_info_label.setText(_t("family_filter_info"))
        self.family_filter_apply_btn.setText(_t("family_filter_apply"))
        current_family_idx = self.family_filter_combo.currentIndex()
        self.family_filter_combo.setItemText(0, _t("family_filter_off"))
        self.family_filter_combo.setItemText(1, _t("family_filter_malware"))
        self.family_filter_combo.setItemText(2, _t("family_filter_full"))
        self.family_filter_combo.setCurrentIndex(current_family_idx)

        self._kill_group_box.setTitle(_t("kill_switch_title"))
        self.kill_switch_check.setText(_t("kill_switch_label"))
        self.kill_switch_info_label.setText(_t("kill_switch_info"))
        self.leak_test_btn.setText(_t("leak_test"))

        self.auto_reconnect_check.setText(_t("auto_reconnect"))
        self.autostart_check.setText(_t("autostart_check"))
        self.autostart_default_note_label.setText(_t("autostart_default_note"))
        self.autostart_action_nothing.setText(_t("autostart_nothing"))
        self.autostart_action_connect.setText(_t("autostart_connect"))
        self.autostart_action_connect_apps.setText(_t("autostart_connect_apps"))

        self.profiles_label.setText(_t("profiles_label"))
        self.profile_save_btn.setToolTip(_t("profiles_save_btn"))
        self.profile_delete_btn.setToolTip(_t("profiles_delete_btn"))
        self._refresh_profile_combo()

        self.sound_enabled_check.setText(_t("sound_enabled_label"))
        self.diag_export_btn.setText(_t("diag_export_btn"))
        self.diag_copy_btn.setText(_t("diag_copy_btn"))

        self.config["language"] = lang
        save_config(self.config)

    def on_autostart_toggled(self, checked):
        ok = set_windows_autostart(checked)
        if not ok and checked:
            self.toast_manager.show(_t("autostart_fail"), "error")
            self.autostart_check.setChecked(False)

    def on_sound_toggled(self, checked):
        self.sound_manager.enabled = checked

    # ---- diagnostics ----
    def build_diagnostics_report(self):
        lines = []
        lines.append(f"XaraProxy diagnostics report - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"App version: {APP_VERSION}")
        lines.append(f"Python: {sys.version.split()[0]}")
        try:
            from PyQt5.QtCore import QT_VERSION_STR
            lines.append(f"PyQt5 / Qt: {QT_VERSION_STR}")
        except Exception:
            pass
        lines.append(f"OS: {sys.platform}, admin rights: {is_admin()}")
        lines.append("")
        lines.append("-- WARP --")
        lines.append(f"warp-cli found: {bool(self.warp_cli_path)}")
        if self.warp_cli_path:
            lines.append(f"warp-cli signature valid: {verify_file_signature(self.warp_cli_path)}")
            lines.append(f"warp-svc.exe process alive: {WarpServiceWatchdogThread.is_service_alive()}")
        lines.append(f"Connected: {self.is_running}")
        lines.append(f"Mode: {self.mode_combo.currentText().split()[0] if self.mode_combo.count() else '?'}")
        lines.append(f"Proxy port: {self.port_spin.value()}")
        lines.append(f"WARP region: {self.region_combo.currentText()}")
        lines.append(f"Auto-reconnect: {self.auto_reconnect_check.isChecked()}")
        lines.append("")
        lines.append("-- Protection --")
        lines.append(f"System proxy enabled: {self.system_proxy_enabled}")
        lines.append(f"Kill Switch enabled: {self.kill_switch_enabled}")
        lines.append(f"DNS server: {self.dns_combo.currentData()}")
        lines.append("")
        lines.append("-- App counts --")
        lines.append(f"Apps discovered: {len(self.app_list)}")
        lines.append(f"Apps routed via proxy: {len(self.config.get('selected_apps', []))}")
        lines.append(f"Apps in exceptions: {len(self._excluded_apps_set)}")
        lines.append(f"Saved profiles: {len(self.config.get('profiles', []))}")
        lines.append("")
        lines.append("-- Recent log (last 40 lines) --")
        try:
            log_plain = self.log_text.toPlainText()
            log_lines = log_plain.splitlines()[-40:]
            lines.extend(log_lines if log_lines else ["(empty)"])
        except Exception:
            lines.append("(could not read log)")
        return "\n".join(lines)

    def export_diagnostics(self):
        report = self.build_diagnostics_report()
        default_name = f"xaraproxy_diagnostics_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, _t("diag_export_title"), default_name, "Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(report)
            self.toast_manager.show(_t("diag_export_saved") + path, "success")
        except Exception as e:
            self.toast_manager.show(_t("diag_export_fail") + str(e), "error")

    def copy_diagnostics_to_clipboard(self):
        report = self.build_diagnostics_report()
        QApplication.clipboard().setText(report)
        self.toast_manager.show(_t("diag_copied_toast"), "success")

    # ---- help tab ----
    def create_help_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        install_group = QGroupBox(_t("help_install_title"))
        igl = QVBoxLayout(install_group)

        self.help_status_label = QLabel("Checking WARP installation...")
        self.help_status_label.setWordWrap(True)
        igl.addWidget(self.help_status_label)

        self.help_install_btn = SmoothButton(_t("help_install_btn"), base_color=C_SUCCESS, hover_color="#369b6d")
        self.help_install_btn.clicked.connect(self.install_warp_from_help)
        igl.addWidget(self.help_install_btn)

        self.help_progress = QProgressBar()
        self.help_progress.setRange(0, 100)
        self.help_progress.setValue(0)
        self.help_progress.setVisible(False)
        igl.addWidget(self.help_progress)
        self.help_progress_label = QLabel("")
        self.help_progress_label.setObjectName("Hint")
        igl.addWidget(self.help_progress_label)
        layout.addWidget(install_group)

        guide_group = QGroupBox(_t("help_instructions"))
        gl = QVBoxLayout(guide_group)
        text = f"""
        <h2 style="color:{C_TEXT};">XaraProxy</h2>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_proxy")}</b></p>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_warp")}</b></p>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_choose")}</b></p>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_diagnostics")}</b></p>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_autostart")}</b></p>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_stalzone")}</b></p>
        <p style="color:{C_MUTED};"><b style="color:{C_TEXT};">{_t("help_text_browsers")}</b></p>
        """
        label = QLabel(text)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(label)
        gl.addWidget(scroll)
        layout.addWidget(guide_group, stretch=1)

        self.update_help_status()
        return tab

    def update_help_status(self):
        if self.warp_cli_path:
            self.help_status_label.setText(_t("help_status_installed"))
            self.help_status_label.setStyleSheet(f"color: {C_SUCCESS};")
            self.help_install_btn.setEnabled(False)
            self.help_install_btn.setText(_t("help_install_btn_done"))
        else:
            self.help_status_label.setText(_t("help_status_not_installed"))
            self.help_status_label.setStyleSheet(f"color: {C_DANGER};")
            self.help_install_btn.setEnabled(True)
            self.help_install_btn.setText(_t("help_install_btn"))

    def install_warp_from_help(self):
        if not is_admin():
            reply = QMessageBox.question(self, _t("admin_required"), _t("admin_restart"),
                                          QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.close()
                run_as_admin()
            return

        self.help_install_btn.setEnabled(False)
        self.help_install_btn.setText(_t("download_installer"))
        self.help_progress.setVisible(True)
        self.help_progress.setValue(0)
        self.log("Starting WARP installation from Help tab...", "INFO")

        installer_path = os.path.join(APP_DIR, "WARP_Release.msi")
        self._download_thread = InstallerDownloadThread(WARP_INSTALLER_URL, installer_path)
        self._download_thread.progress_signal.connect(self._on_installer_progress)
        self._download_thread.finished_signal.connect(self._on_installer_finished)
        self._download_thread.start()

    def _on_installer_progress(self, pct, downloaded_mb, total_mb):
        self.help_progress.setValue(pct)
        self.help_progress_label.setText(_t("download_progress") % (pct, downloaded_mb, total_mb))

    def _on_installer_finished(self, success, path_or_error):
        self.help_progress.setVisible(False)
        self.help_install_btn.setEnabled(True)
        if not success:
            self.log(f"Installation error: {path_or_error}", "ERROR")
            self.toast_manager.show(_t("installer_error") + path_or_error, "error")
            self.update_help_status()
            return

        self.log("Downloaded, verifying signature...", "INFO")
        if not verify_file_signature(path_or_error):
            self.toast_manager.show(_t("installer_sig_fail"), "error")
            self.log("Signature verification FAILED - installer removed.", "ERROR")
            try:
                os.remove(path_or_error)
            except Exception:
                pass
            self.update_help_status()
            return

        self.log("Signature verified, launching installer...", "SUCCESS")
        try:
            os.startfile(path_or_error)
            QMessageBox.information(self, "Installation started",
                                     "Wait for the installer to finish.\n"
                                     "After installation, close the WARP window if it opens.\n"
                                     "Then click OK to refresh status.")
        except Exception as e:
            self.toast_manager.show(_t("installer_error") + str(e), "error")

        self.warp_cli_path = find_warp_cli()
        self.update_help_status()
        if self.warp_cli_path:
            self.status_bar.showMessage("WARP installed! Ready to use.")
            self.log("WARP successfully installed.", "SUCCESS")
            self.toast_manager.show(_t("installer_success"), "success")

    # ---- log ----
    def log(self, message, level="INFO"):
        ts = time.strftime("%H:%M:%S")
        color = {"ERROR": C_DANGER, "WARN": C_WARN, "SUCCESS": C_SUCCESS}.get(level, C_MUTED)
        self.log_text.append(f'<span style="color:{color};">[{ts}] [{level}]</span> {message}')
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ---- warp control ----
    def start_warp(self):
        if not self.warp_cli_path:
            self.toast_manager.show(_t("warp_not_installed"), "warn")
            return
        if self.controller and self.controller.isRunning():
            return
        if self.sys_proxy_check.isChecked() and not is_admin():
            reply = QMessageBox.question(self, _t("admin_required"), _t("sys_proxy_admin"),
                                          QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.close()
                run_as_admin()
            return

        mode = self.mode_combo.currentText().split()[0]
        port = self.port_spin.value()
        endpoint = self.endpoint_edit.text().strip() or self.endpoint_combo.currentText().strip()
        region = self.region_combo.currentText()

        self.controller = WarpController(
            self.warp_cli_path, port=port, mode=mode,
            auto_reconnect=self.auto_reconnect_check.isChecked(),
            custom_endpoint=endpoint, region=region,
        )
        self.controller.log_signal.connect(lambda msg: self.log(msg, "INFO"))
        self.controller.status_signal.connect(self.on_warp_status_changed)
        self.controller.start()

        for b in (self.start_btn, self.quick_connect_btn):
            b.setEnabled(False)
        for b in (self.stop_btn, self.quick_disconnect_btn):
            b.setEnabled(True)
        self.progress.setVisible(True)
        self.set_status_style("busy", _t("connecting"))
        self.quick_connect_btn.set_pulsing(True)
        self._start_watchdog()

    def _start_watchdog(self):
        if self._watchdog_thread and self._watchdog_thread.isRunning():
            return
        self._watchdog_thread = WarpServiceWatchdogThread()
        self._watchdog_thread.service_down.connect(self._on_watchdog_service_down)
        self._watchdog_thread.service_recovered.connect(self._on_watchdog_service_recovered)
        self._watchdog_thread.start()

    def _stop_watchdog(self):
        if self._watchdog_thread:
            self._watchdog_thread.stop()

    def _on_watchdog_service_down(self):
        self.log(_t("watchdog_service_down"), "ERROR")
        self.toast_manager.show(_t("watchdog_service_down"), "error")

    def _on_watchdog_service_recovered(self):
        self.log(_t("watchdog_service_recovered"), "SUCCESS")
        self.toast_manager.show(_t("watchdog_service_recovered"), "success")

    def stop_warp(self):
        if self._disconnect_thread and self._disconnect_thread.isRunning():
            return
        if not self.warp_cli_path:
            return
        for b in (self.start_btn, self.quick_connect_btn, self.stop_btn, self.quick_disconnect_btn):
            b.setEnabled(False)
        self.quick_connect_btn.set_pulsing(False)
        self.set_status_style("busy", _t("disconnecting"))
        if self.controller:
            with QMutexLocker(self.controller._mutex):
                self.controller._stop_flag = True
        self._disconnect_thread = WarpDisconnectThread(self.warp_cli_path)
        self._disconnect_thread.finished_ok.connect(self._on_disconnect_finished)
        self._disconnect_thread.start()

    def _on_disconnect_finished(self, ok, error):
        self.is_running = False
        self._session_connected_at = None
        self.set_status_style("off", _t("disconnected"))
        for b in (self.start_btn, self.quick_connect_btn):
            b.setEnabled(True)
        for b in (self.stop_btn, self.quick_disconnect_btn):
            b.setEnabled(False)
        self.progress.setVisible(False)
        if self.system_proxy_enabled:
            self.disable_system_proxy()
        if self.kill_switch_enabled:
            remove_kill_switch_rule()
        self.sound_manager.play("disconnect")
        self.toast_manager.show(_t("toast_disconnected"), "info")
        self._stop_watchdog()
        if not ok and error:
            self.log(f"Disconnect warning: {error}", "WARN")

    def on_warp_status_changed(self, status):
        connected = status.get("connected", False)
        mode = status.get("mode", "")
        ip = status.get("ip", "")
        country = status.get("country", "-")
        msg = status.get("message", "")
        if connected:
            self.is_running = True
            self._session_connected_at = time.time()
            self._session_total_down_kb = 0.0
            self._session_total_up_kb = 0.0
            for b in (self.start_btn, self.quick_connect_btn):
                b.setEnabled(False)
            for b in (self.stop_btn, self.quick_disconnect_btn):
                b.setEnabled(True)
            self.progress.setVisible(False)
            self.quick_connect_btn.set_pulsing(False)
            self.set_status_style("ok", _t("connected") + f" - {ip} ({country})")
            self.status_bar.showMessage(_t("warp_connected") % (ip, country), 4000)
            self.log(_t("warp_connected") % (ip, country), "SUCCESS")
            self.sound_manager.play("connect")
            self.toast_manager.show(_t("toast_connected") + f" - {ip} ({country})", "success")
            if self.sys_proxy_check.isChecked() and mode == "proxy":
                self.enable_system_proxy()
            if self.kill_switch_enabled:
                remove_kill_switch_rule()
            if mode == "warp":
                self._reapply_split_tunnel_entries()
        else:
            was_running = self.is_running
            self.is_running = False
            self._session_connected_at = None
            for b in (self.start_btn, self.quick_connect_btn):
                b.setEnabled(True)
            for b in (self.stop_btn, self.quick_disconnect_btn):
                b.setEnabled(False)
            self.progress.setVisible(False)
            self.quick_connect_btn.set_pulsing(False)
            self.set_status_style("off", msg or _t("disconnected"))
            if msg and msg != _t("disconnected"):
                self.toast_manager.show(msg, "error")
            if self.system_proxy_enabled:
                self.disable_system_proxy()
            if self.kill_switch_enabled and was_running and self.controller and self.controller.isRunning():
                self._apply_kill_switch()

    def test_proxy(self):
        if not self.is_running:
            self.toast_manager.show(_t("connect_first"), "warn")
            return
        if self._trace_thread and self._trace_thread.isRunning():
            return
        mode = self.mode_combo.currentText().split()[0]
        self.test_btn.setEnabled(False)
        self.test_btn.setText(_t("checking"))
        self._trace_thread = TraceCheckThread(mode, self.port_spin.value())
        self._trace_thread.result_signal.connect(self._on_trace_result)
        self._trace_thread.error_signal.connect(self._on_trace_error)
        self._trace_thread.start()

    def _reset_test_btn(self):
        self.test_btn.setEnabled(True)
        self.test_btn.setText(_t("check_ip"))

    def _on_trace_result(self, data):
        self._reset_test_btn()
        ip, loc, warp = data.get("ip", "not found"), data.get("loc", "not found"), data.get("warp", "not found")
        self.log(f"Diagnostics: IP={ip}, country={loc}, warp={warp}", "SUCCESS")
        self.toast_manager.show(_t("ip_country") % (ip, loc, warp), "success")

    def _on_trace_error(self, error):
        self._reset_test_btn()
        self.log(f"Diagnostics error: {error}", "ERROR")
        self.toast_manager.show(_t("could_not_check") + error, "error")

    def on_mode_changed(self):
        if hasattr(self, "apps_seg_group"):
            self._apply_apps_view_mode()
        if self.is_running:
            self.log(_t("mode_changed"))
            self.stop_warp()
            QTimer.singleShot(1500, self.start_warp)

    # ---- dns ----
    def check_dns_auto(self):
        if self._dns_thread and self._dns_thread.isRunning():
            return
        self._dns_thread = DNSCheckThread()
        self._dns_thread.result_signal.connect(self._on_dns_result)
        self._dns_thread.start()
        self.toast_manager.show(_t("dns_checking"), "info")

    def _on_dns_result(self, best):
        self.toast_manager.show(_t("dns_fastest") + best, "success")
        idx = self.dns_combo.findData(best)
        if idx >= 0:
            self.dns_combo.setCurrentIndex(idx)
        self.config["dns_server"] = best
        save_config(self.config)

    # ---- apps scanning ----
    def scan_apps(self):
        self._show_skeleton_loading()
        self.rescan_btn.setEnabled(False)
        self.rescan_btn.setText(_t("scanning") + "...")
        hidden = self.config.get("hidden_apps", [])
        self.scanner = AppScannerThread(hidden_apps=hidden)
        self.scanner.progress_signal.connect(lambda m: self.log(m, "INFO"))
        self.scanner.finished_signal.connect(self.on_apps_scanned)
        self.scanner.start()

    def _show_skeleton_loading(self):
        self.apps_list.clear()
        self._skeleton_rows = []
        for _ in range(6):
            item = QListWidgetItem()
            item.setFlags(Qt.NoItemFlags)
            row = SkeletonRow()
            item.setSizeHint(row.sizeHint() if row.sizeHint().height() > 0 else QSize(100, 34))
            self.apps_list.addItem(item)
            self.apps_list.setItemWidget(item, row)
            self._skeleton_rows.append(row)

    def _clear_skeleton_loading(self):
        for row in self._skeleton_rows:
            row.stop()
        self._skeleton_rows = []
        self.apps_list.clear()

    def on_apps_scanned(self, apps):
        self._clear_skeleton_loading()
        self.app_list = apps
        self.populate_apps_list()
        self.rescan_btn.setEnabled(True)
        self.rescan_btn.setText(_t("refresh_list"))
        self.log(_t("apps_found") + str(len(apps)), "SUCCESS")

    def populate_apps_list(self, filter_text="", category=""):
        self.apps_list.blockSignals(True)
        self.apps_list.clear()
        self.app_items.clear()
        mode = self._apps_view_mode
        selected = set(self.config.get("selected_apps", []))
        for app in self.app_list:
            name, path, cat = app["name"], app["path"], app.get("category", _t("cat_other"))
            if filter_text and filter_text.lower() not in name.lower():
                continue
            if category and category != _t("all_categories") and cat != category:
                continue
            item = QListWidgetItem(f"{name}   .   {cat}")
            item.setData(Qt.UserRole, path)
            try:
                ico = self.icon_provider.icon(QFileInfo(path))
                if not ico.isNull():
                    item.setIcon(ico)
            except Exception:
                pass

            is_excluded = path in self._excluded_apps_set
            base_flags = Qt.ItemIsUserCheckable | Qt.ItemIsSelectable
            if mode == "exceptions":
                item.setFlags(base_flags | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if is_excluded else Qt.Unchecked)
                item.setToolTip(path)
            else:
                if is_excluded:
                    item.setFlags(base_flags)
                    item.setCheckState(Qt.Unchecked)
                    item.setToolTip(_t("exceptions_locked_tooltip"))
                else:
                    item.setFlags(base_flags | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Checked if path in selected else Qt.Unchecked)
                    item.setToolTip(path)

            self.apps_list.addItem(item)
            self.app_items[path] = item
        self.apps_list.blockSignals(False)

    def _on_apps_item_changed(self, item):
        path = item.data(Qt.UserRole)
        if not path:
            return
        checked = item.checkState() == Qt.Checked
        if self._apps_view_mode == "exceptions":
            if checked:
                self._excluded_apps_set.add(path)
                selected = self.config.setdefault("selected_apps", [])
                if path in selected:
                    selected.remove(path)
            else:
                self._excluded_apps_set.discard(path)
            self.config["excluded_apps"] = list(self._excluded_apps_set)
        else:
            selected = self.config.setdefault("selected_apps", [])
            if checked and path not in selected:
                selected.append(path)
            elif not checked and path in selected:
                selected.remove(path)
        self._settings_dirty = True

    def _show_apps_context_menu(self, pos):
        item = self.apps_list.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        menu = QMenu(self)
        if self.mode_combo.currentText().split()[0] == "proxy":
            launch_action = menu.addAction(_t("ctx_launch_one"))
            launch_action.triggered.connect(lambda: self._launch_single_app(path))
            menu.addSeparator()
        is_excluded = path in self._excluded_apps_set
        if is_excluded:
            exc_action = menu.addAction(_t("ctx_remove_exception"))
            exc_action.triggered.connect(lambda: self._toggle_exception(path, False))
        else:
            exc_action = menu.addAction(_t("ctx_add_exception"))
            exc_action.triggered.connect(lambda: self._toggle_exception(path, True))
        menu.addSeparator()
        hide_action = menu.addAction(_t("ctx_hide"))
        hide_action.triggered.connect(lambda: self._hide_app(path))
        menu.exec_(self.apps_list.viewport().mapToGlobal(pos))

    def _toggle_exception(self, path, exclude):
        if exclude:
            self._excluded_apps_set.add(path)
            selected = self.config.setdefault("selected_apps", [])
            if path in selected:
                selected.remove(path)
        else:
            self._excluded_apps_set.discard(path)
        self.config["excluded_apps"] = list(self._excluded_apps_set)
        self._settings_dirty = True
        self.populate_apps_list(self.search_edit.text().strip(), self.category_combo.currentText())

    def _hide_app(self, path):
        name = os.path.basename(path)
        reply = QMessageBox.question(self, _t("hide_confirm"), _t("hide_message") % name,
                                      QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        hidden = self.config.setdefault("hidden_apps", [])
        if path not in hidden:
            hidden.append(path)
        self.app_list = [a for a in self.app_list if a["path"] != path]
        self.app_items.pop(path, None)
        self.populate_apps_list(self.search_edit.text().strip(), self.category_combo.currentText())
        self.log(f"App hidden: {name}", "INFO")
        save_config(self.config)

    def _launch_single_app(self, path):
        if not self.is_running:
            reply = QMessageBox.question(self, _t("warp_not_connected"), _t("start_now"),
                                          QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.start_warp()
                QTimer.singleShot(3000, lambda: self._launch_checked([path]))
            return
        self._launch_checked([path])

    def filter_apps(self):
        self.populate_apps_list(self.search_edit.text().strip(), self.category_combo.currentText())

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select application", "", "Executable files (*.exe)")
        if path:
            self.exe_path_edit.setText(path)

    def add_manual_app(self):
        path = self.exe_path_edit.text().strip()
        if not path or not os.path.exists(path):
            self.toast_manager.show("Specify a valid .exe path", "warn")
            return
        if any(app["path"] == path for app in self.app_list):
            self.toast_manager.show(_t("app_exists"), "info")
            return
        name = os.path.splitext(os.path.basename(path))[0]
        category = AppScannerThread.guess_category(name, path)
        self.app_list.append({"name": name, "path": path, "category": category})
        self.app_list.sort(key=lambda x: x["name"].lower())
        self.populate_apps_list(self.search_edit.text(), self.category_combo.currentText())
        self.log(_t("app_added") + name, "SUCCESS")
        self.toast_manager.show(_t("app_added") + name, "success")
        self.exe_path_edit.clear()

    def launch_checked_apps(self):
        checked = [p for p, item in self.app_items.items() if item.checkState() == Qt.Checked]
        if not checked:
            self.toast_manager.show(_t("no_apps_checked"), "warn")
            return
        if self.mode_combo.currentText().split()[0] != "proxy":
            self.toast_manager.show(_t("proxy_mode_only"), "warn")
            return
        if not self.is_running:
            reply = QMessageBox.question(self, _t("warp_not_connected"), _t("start_now"),
                                          QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.start_warp()
                QTimer.singleShot(3000, lambda: self._launch_checked(checked))
            return
        self._launch_checked(checked)

    def _launch_checked(self, paths):
        if not paths:
            return
        port = self.port_spin.value()
        env = build_proxy_env(port)
        launched = 0
        for path in paths:
            if not path or not os.path.exists(path):
                continue
            if path in self._excluded_apps_set:
                self.log(f"Skipped launching excluded app: {os.path.basename(path)}", "WARN")
                continue
            argv, warning_key = build_launch_args(path, port)
            try:
                subprocess.Popen(argv, env=env, cwd=os.path.dirname(path), shell=False)
                self.log(_t("launched_via_proxy") + os.path.basename(path), "SUCCESS")
                if warning_key:
                    self.log(_t(warning_key), "WARN")
                    self.toast_manager.show(_t(warning_key), "warn")
                launched += 1
            except Exception as e:
                self.log(_t("launch_error") + f"{path}: {e}", "ERROR")
        if launched:
            self.toast_manager.show(_t("launched_count") + str(launched), "success")
        save_config(self.config)

    # ---- system proxy ----
    def toggle_system_proxy(self, checked):
        if self.mode_combo.currentText().split()[0] != "proxy":
            self.toast_manager.show(_t("system_proxy_only"), "warn")
            self.sys_proxy_check.setChecked(False)
            return
        if checked:
            if not is_admin():
                reply = QMessageBox.question(self, _t("admin_required"), _t("sys_proxy_admin"),
                                              QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.close()
                    run_as_admin()
                else:
                    self.sys_proxy_check.setChecked(False)
                return
            self.enable_system_proxy()
        else:
            self.disable_system_proxy()

    def enable_system_proxy(self):
        port = self.port_spin.value()
        if set_windows_system_proxy(True, port):
            self.system_proxy_enabled = True
            self.log(_t("sys_proxy_enabled") % port, "SUCCESS")
        else:
            self.toast_manager.show(_t("sys_proxy_failed"), "error")
            self.sys_proxy_check.setChecked(False)

    def disable_system_proxy(self):
        if set_windows_system_proxy(False):
            self.system_proxy_enabled = False
            self.log(_t("sys_proxy_disabled"), "INFO")

    # ---- utilities ----
    def flush_dns(self):
        try:
            subprocess.run(["ipconfig", "/flushdns"], shell=False, check=True, creationflags=CREATE_NO_WINDOW)
            self.log(_t("dns_flushed"), "SUCCESS")
            self.toast_manager.show(_t("dns_flushed"), "success")
        except Exception as e:
            self.toast_manager.show(_t("dns_flush_fail") + str(e), "error")

    def clear_proxy_settings(self):
        reply = QMessageBox.question(self, "Confirmation", _t("reset_confirm"), QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        if set_windows_system_proxy(False):
            self.system_proxy_enabled = False
            self.log(_t("proxy_cleared"), "SUCCESS")
            self.toast_manager.show(_t("proxy_cleared"), "success")
        else:
            self.toast_manager.show(_t("proxy_clear_fail"), "error")

    def apply_family_filter(self):
        if not self.warp_cli_path:
            self.toast_manager.show(_t("warp_not_installed"), "warn")
            return
        mode_key = self.family_filter_combo.currentData()
        try:
            result = subprocess.run([self.warp_cli_path, "dns", "families", mode_key],
                                     capture_output=True, text=True, timeout=8,
                                     creationflags=CREATE_NO_WINDOW, check=False)
            if result.returncode == 0:
                self.config["dns_family_filter"] = mode_key
                save_config(self.config)
                label = self.family_filter_combo.currentText()
                self.log(f"DNS family filter set to: {mode_key}", "SUCCESS")
                self.toast_manager.show(_t("family_filter_applied") + label, "success")
            else:
                err = (result.stderr or result.stdout or "unknown error").strip()
                self.toast_manager.show(_t("family_filter_fail") + err, "error")
        except Exception as e:
            self.toast_manager.show(_t("family_filter_fail") + str(e), "error")

    def update_status(self):
        if self.controller and not self.controller.isRunning() and self.is_running:
            self.on_warp_status_changed({"connected": False, "mode": "", "ip": "", "message": _t("disconnected")})

    def save_settings(self):
        self.save_config()
        self.status_bar.showMessage(_t("settings_saved"), 3000)
        self.log(_t("settings_saved"), "SUCCESS")
        self.toast_manager.show(_t("toast_saved"), "success")

    def reset_config(self):
        reply = QMessageBox.question(self, "Reset", _t("reset_confirm"), QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            self.log(_t("reset_done"), "SUCCESS")
            self.close()
            subprocess.Popen([sys.executable] + sys.argv, shell=False)
        except Exception as e:
            self.toast_manager.show(_t("reset_fail") + str(e), "error")

    def _fully_disconnect_everything(self):
        self._stop_watchdog()
        if self.controller and self.controller.isRunning():
            self.controller.stop()
            self.controller.wait(3000)
        if self.system_proxy_enabled:
            self.disable_system_proxy()
        if self.kill_switch_enabled:
            remove_kill_switch_rule()
        if self.warp_cli_path:
            try:
                subprocess.run([self.warp_cli_path, "disconnect"], capture_output=True,
                                check=False, timeout=5, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass

    def closeEvent(self, event):
        if self._settings_dirty:
            reply = QMessageBox.question(self, _t("unsaved_title"), _t("unsaved_body"),
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                                          QMessageBox.Yes)
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Yes:
                self.save_config()
        else:
            self.save_config()

        if self.config.get("minimize_to_tray", True) and getattr(self, "tray_icon", None) and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(APP_NAME, _t("minimized_to_tray"), QSystemTrayIcon.Information, 2000)
            return

        self._fully_disconnect_everything()
        event.accept()

    # ---- tray ----
    def create_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(64,64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(C_ACCENT))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(8,8,48,48,8,8)
        painter.end()
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction(_t("tray_connect")).triggered.connect(self.start_warp)
        menu.addAction(_t("tray_disconnect")).triggered.connect(self.stop_warp)
        menu.addSeparator()
        menu.addAction(_t("tray_show")).triggered.connect(self.showNormal)
        menu.addAction(_t("tray_quit")).triggered.connect(self._quit_app)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(
            lambda reason: self.showNormal() if reason == QSystemTrayIcon.DoubleClick else None
        )

    def _quit_app(self):
        self.config["minimize_to_tray"] = False
        self._fully_disconnect_everything()
        QApplication.quit()

    # ---- wizard ----
    def run_setup_wizard(self):
        wizard = SetupWizard(self)
        if wizard.exec_() == QWizard.Accepted:
            mode = wizard.mode_combo.currentText().split()[0]
            self.config["mode"] = mode
            self.config["onboarding_done"] = True
            save_config(self.config)
            if not self.warp_cli_path:
                self.warp_cli_path = find_warp_cli()
            if wizard.connect_now_check.isChecked() and self.warp_cli_path:
                self.log(_t("warp_register"))
                self.start_warp()
            self.scan_apps()
            self.update_help_status()

    # ---- status style ----
    def set_status_style(self, kind, text):
        colors = {"ok": C_SUCCESS, "off": C_DANGER, "busy": C_WARN}
        color = colors.get(kind, C_DANGER)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 14px;")
        self.status_indicator.set_status(kind)
        if hasattr(self, "quick_status_label"):
            self.quick_status_label.setText(text)
            self.quick_status_label.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 18px;")
            self.quick_status_indicator.set_status(kind)
        if hasattr(self, "title_bar"):
            self.title_bar.status_dot.set_status(kind)
            self.title_bar.status_dot.setToolTip(text)

    # ---- config ----
    def load_settings_to_ui(self):
        self._loading_settings = True
        self.port_spin.setValue(self.config.get("proxy_port", 40000))
        mode = self.config.get("mode", "warp")
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemText(i).startswith(mode):
                self.mode_combo.setCurrentIndex(i)
                break
        self.auto_reconnect_check.setChecked(self.config.get("auto_reconnect", True))
        self.sys_proxy_check.setChecked(self.config.get("system_proxy", False))
        self.kill_switch_check.setChecked(self.config.get("kill_switch", False))
        dns = self.config.get("dns_server", "1.1.1.1")
        idx = self.dns_combo.findData(dns)
        if idx >= 0:
            self.dns_combo.setCurrentIndex(idx)
        self.ui_level_combo.setCurrentText(self.config.get("ui_level", "advanced"))
        self.endpoint_edit.setText(self.config.get("custom_endpoint", ""))
        self.autostart_check.setChecked(self.config.get("autostart_windows", False))
        action = self.config.get("autostart_action", "nothing")
        {"nothing": self.autostart_action_nothing,
         "connect": self.autostart_action_connect,
         "connect_and_apps": self.autostart_action_connect_apps}.get(action, self.autostart_action_nothing).setChecked(True)
        self.stalzone_path_edit.setText(self.config.get("stalzone_path", ""))
        self.stalzone_region_combo.setCurrentText(self.config.get("stalzone_region", "RU"))
        lang = self.config.get("language", "ru")
        idx = self.lang_combo.findText(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        endpoint = self.config.get("selected_endpoint", "")
        if endpoint and endpoint in POPULAR_ENDPOINTS:
            idx = self.endpoint_combo.findText(endpoint)
            if idx >= 0:
                self.endpoint_combo.setCurrentIndex(idx)
                self.endpoint_edit.setText(endpoint)
        elif endpoint:
            self.endpoint_edit.setText(endpoint)
        region = self.config.get("warp_region", "auto")
        idx = self.region_combo.findText(region)
        if idx >= 0:
            self.region_combo.setCurrentIndex(idx)
        self.sound_enabled_check.setChecked(self.config.get("sound_enabled", True))
        self.sound_manager.enabled = self.sound_enabled_check.isChecked()
        self._excluded_apps_set = set(self.config.get("excluded_apps", []))
        saved_filter = self.config.get("dns_family_filter", "off")
        idx = self.family_filter_combo.findData(saved_filter)
        if idx >= 0:
            self.family_filter_combo.setCurrentIndex(idx)
        self._loading_settings = False
        self._settings_dirty = False

    def _wire_dirty_tracking(self):
        def mark_dirty(*_args):
            if not self._loading_settings:
                self._settings_dirty = True

        widgets_signals = [
            (self.port_spin, "valueChanged"),
            (self.mode_combo, "currentIndexChanged"),
            (self.auto_reconnect_check, "toggled"),
            (self.sys_proxy_check, "toggled"),
            (self.kill_switch_check, "toggled"),
            (self.dns_combo, "currentIndexChanged"),
            (self.ui_level_combo, "currentIndexChanged"),
            (self.endpoint_edit, "textChanged"),
            (self.autostart_check, "toggled"),
            (self.autostart_action_nothing, "toggled"),
            (self.autostart_action_connect, "toggled"),
            (self.autostart_action_connect_apps, "toggled"),
            (self.stalzone_path_edit, "textChanged"),
            (self.stalzone_region_combo, "currentIndexChanged"),
            (self.lang_combo, "currentIndexChanged"),
            (self.endpoint_combo, "currentTextChanged"),
            (self.region_combo, "currentIndexChanged"),
            (self.sound_enabled_check, "toggled"),
        ]
        for widget, signal_name in widgets_signals:
            getattr(widget, signal_name).connect(mark_dirty)

    def apply_ui_level(self):
        advanced = self.ui_level_combo.currentText() == "advanced"
        if hasattr(self.tabs, "setTabVisible"):
            self.tabs.setTabVisible(2, advanced)   # apps
            self.tabs.setTabVisible(3, True)       # stalzone always
            self.tabs.setTabVisible(4, True)       # settings
            self.tabs.setTabVisible(5, True)       # help
        self.endpoint_group.setVisible(advanced)

    def save_config(self):
        self.config["proxy_port"] = self.port_spin.value()
        self.config["mode"] = self.mode_combo.currentText().split()[0] if self.mode_combo.currentText() else "warp"
        self.config["auto_reconnect"] = self.auto_reconnect_check.isChecked()
        self.config["system_proxy"] = self.sys_proxy_check.isChecked()
        self.config["kill_switch"] = self.kill_switch_check.isChecked()
        self.config["dns_server"] = self.dns_combo.currentData() or self.config.get("dns_server", "1.1.1.1")
        self.config["ui_level"] = self.ui_level_combo.currentText()
        self.config["custom_endpoint"] = self.endpoint_edit.text().strip()
        self.config["autostart_windows"] = self.autostart_check.isChecked()
        self.config["autostart_action"] = self._current_autostart_action()
        self.config["excluded_apps"] = list(self._excluded_apps_set)
        self.config["stalzone_path"] = self.stalzone_path_edit.text().strip()
        self.config["stalzone_region"] = self.stalzone_region_combo.currentText()
        self.config["language"] = self.lang_combo.currentText()
        endpoint = self.endpoint_combo.currentText().strip()
        if endpoint:
            self.config["selected_endpoint"] = endpoint
        self.config["warp_region"] = self.region_combo.currentText()
        self.config["sound_enabled"] = self.sound_enabled_check.isChecked()
        save_config(self.config)
        self._settings_dirty = False

    def _current_autostart_action(self):
        if self.autostart_action_nothing.isChecked():
            return "nothing"
        if self.autostart_action_connect.isChecked():
            return "connect"
        return "connect_and_apps"

    # ---- speed stats ----
    def update_speed(self):
        try:
            net = psutil.net_io_counters(pernic=True)
            lo = None
            for name, stats in net.items():
                if "lo" in name.lower():
                    lo = stats
                    break
            if lo is None:
                for _, stats in net.items():
                    lo = stats
                    break
            if lo is None:
                return
            now_rx, now_tx = lo.bytes_recv, lo.bytes_sent
            if self._last_rx == 0:
                self._last_rx, self._last_tx = now_rx, now_tx
                return
            down_speed = max(0.0, (now_rx - self._last_rx) / 1024)
            up_speed = max(0.0, (now_tx - self._last_tx) / 1024)
            self._last_rx, self._last_tx = now_rx, now_tx
            self.download_label.setText(f"{down_speed:.1f} KB/s")
            self.upload_label.setText(f"{up_speed:.1f} KB/s")
            self.total_label.setText(f"{down_speed + up_speed:.1f} KB/s")
            self.sparkline.push(down_speed, up_speed)
            if self.is_running:
                self._session_total_down_kb += down_speed
                self._session_total_up_kb += up_speed
        except Exception:
            pass

    def update_session_stats(self):
        if not hasattr(self, "session_stats_label"):
            return
        if self.is_running and self._session_connected_at:
            elapsed = int(time.time() - self._session_connected_at)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            total_mb = (self._session_total_down_kb + self._session_total_up_kb) / 1024.0
            self.session_stats_label.setText(f"{h:02d}:{m:02d}:{s:02d}  ·  {total_mb:.1f} MB")
        else:
            self.session_stats_label.setText("00:00:00  ·  0.0 MB")

# ---- setup wizard ----
class SetupWizard(QWizard):
    PAGE_LANG, PAGE_WELCOME, PAGE_INSTALL, PAGE_FINAL = range(4)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("XaraProxy - Setup")
        self.setMinimumSize(740, 560)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setStyleSheet(f"""
            QWizard {{ background-color: {C_BG}; color: {C_TEXT}; }}
            QWizardPage {{ background-color: {C_BG}; }}
            QLabel {{ color: {C_TEXT}; background: transparent; }}
            QPushButton {{ background-color: {C_ACCENT}; color: white; border: none; border-radius: 6px; padding: 8px 16px; }}
            QPushButton:hover {{ background-color: {C_ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: #3a3a3a; color: #777777; }}
            QComboBox, QLineEdit {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px; color: {C_TEXT}; }}
            QProgressBar {{ border: none; background: {C_CARD_ALT}; border-radius: 4px; text-align: center; }}
            QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 4px; }}
        """)
        self.setOption(QWizard.NoBackButtonOnStartPage)
        self.setOption(QWizard.HaveNextButtonOnLastPage, False)
        self._download_thread = None
        self._page_effects = {}

        self.addPage(self.create_language_page())
        self.addPage(self.create_welcome_page())
        self.addPage(self.create_install_page())
        self.addPage(self.create_final_page())

        self.retranslate_ui()
        self.currentIdChanged.connect(self._animate_page_transition)

    def _animate_page_transition(self, page_id):
        page = self.page(page_id)
        if page is None:
            return
        effect = self._page_effects.get(page_id)
        if effect is None:
            effect = QGraphicsOpacityEffect(page)
            self._page_effects[page_id] = effect
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(260)
        anim.setStartValue(0.2)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        page._fade_anim = anim

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QRadialGradient(self.width()/2, self.height()/2, max(self.width(), self.height())/2)
        gradient.setColorAt(0, QColor("#1A1A24"))
        gradient.setColorAt(1, QColor("#0D0D11"))
        painter.fillRect(self.rect(), gradient)
        super().paintEvent(event)

    def create_language_page(self):
        page = QWizardPage()
        layout = QVBoxLayout()
        self.lang_page_body_label = QLabel()
        self.lang_page_body_label.setWordWrap(True)
        layout.addWidget(self.lang_page_body_label)

        lang_row = QHBoxLayout()
        self.lang_page_label = QLabel()
        lang_row.addWidget(self.lang_page_label)
        self.wizard_lang_combo = QComboBox()
        self.wizard_lang_combo.addItem("Русский", "ru")
        self.wizard_lang_combo.addItem("English", "en")
        idx = self.wizard_lang_combo.findData(_current_lang)
        if idx >= 0:
            self.wizard_lang_combo.setCurrentIndex(idx)
        self.wizard_lang_combo.currentIndexChanged.connect(self._on_wizard_language_changed)
        lang_row.addWidget(self.wizard_lang_combo, stretch=1)
        layout.addLayout(lang_row)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def _on_wizard_language_changed(self):
        code = self.wizard_lang_combo.currentData()
        if code:
            set_language(code)
            self.retranslate_ui()

    def create_welcome_page(self):
        page = QWizardPage()
        layout = QVBoxLayout()
        self.welcome_body_label = QLabel()
        self.welcome_body_label.setWordWrap(True)
        layout.addWidget(self.welcome_body_label)
        layout.addStretch()
        page.setLayout(layout)
        return page

    def create_install_page(self):
        page = QWizardPage()
        layout = QVBoxLayout()
        self.install_label = QLabel()
        self.install_label.setWordWrap(True)
        layout.addWidget(self.install_label)

        self.download_btn = QPushButton()
        self.download_btn.clicked.connect(self.download_and_run_installer)
        layout.addWidget(self.download_btn)

        self.wizard_progress = QProgressBar()
        self.wizard_progress.setRange(0, 100)
        self.wizard_progress.setVisible(False)
        layout.addWidget(self.wizard_progress)

        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def download_and_run_installer(self):
        self.download_btn.setEnabled(False)
        self.wizard_progress.setVisible(True)
        self.wizard_progress.setValue(0)
        self.progress_label.setText(_t("wizard_downloading"))

        installer_path = os.path.join(APP_DIR, "WARP_Release.msi")
        self._download_thread = InstallerDownloadThread(WARP_INSTALLER_URL, installer_path)
        self._download_thread.progress_signal.connect(self._on_progress)
        self._download_thread.finished_signal.connect(self._on_finished)
        self._download_thread.start()

    def _on_progress(self, pct, downloaded_mb, total_mb):
        self.wizard_progress.setValue(pct)
        self.progress_label.setText(_t("download_progress") % (pct, downloaded_mb, total_mb))

    def _on_finished(self, success, path_or_error):
        self.download_btn.setEnabled(True)
        if not success:
            self.progress_label.setText(f"{_t('installer_error')}{path_or_error}")
            return
        self.progress_label.setText(_t("checking"))
        if not verify_file_signature(path_or_error):
            self.progress_label.setText(_t("installer_sig_fail"))
            try:
                os.remove(path_or_error)
            except Exception:
                pass
            return
        self.progress_label.setText(_t("installer_success"))
        try:
            os.startfile(path_or_error)
        except Exception as e:
            self.progress_label.setText(f"{_t('installer_error')}{e}")

    def create_final_page(self):
        page = QWizardPage()
        layout = QVBoxLayout()

        self.reg_label = QLabel()
        self.reg_label.setWordWrap(True)
        layout.addWidget(self.reg_label)

        self.mode_label = QLabel()
        layout.addWidget(self.mode_label)

        self.mode_combo = QComboBox()
        layout.addWidget(self.mode_combo)

        self.connect_now_check = ToggleSwitch()
        self.connect_now_check.setChecked(False)
        layout.addWidget(self.connect_now_check)

        self.connect_hint_label = QLabel()
        self.connect_hint_label.setWordWrap(True)
        self.connect_hint_label.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        layout.addWidget(self.connect_hint_label)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def retranslate_ui(self):
        self.lang_page_body_label.setText(_t("wizard_lang_body"))
        self.lang_page_label.setText(_t("wizard_lang_label"))
        self.page(self.PAGE_LANG).setTitle(_t("wizard_lang_title"))

        self.welcome_body_label.setText(_t("wizard_welcome_body"))
        self.page(self.PAGE_WELCOME).setTitle(_t("wizard_welcome_title"))

        self.install_label.setText(_t("wizard_install_body"))
        self.download_btn.setText(_t("wizard_download_btn"))
        self.page(self.PAGE_INSTALL).setTitle(_t("wizard_install_title"))

        self.reg_label.setText(_t("wizard_final_body"))
        self.mode_label.setText(_t("wizard_mode_label"))
        current_mode_idx = self.mode_combo.currentIndex() if self.mode_combo.count() else 0
        self.mode_combo.clear()
        self.mode_combo.addItems([_t("mode_warp"), _t("mode_proxy")])
        self.mode_combo.setCurrentIndex(max(0, current_mode_idx))
        self.connect_now_check.setText(_t("wizard_connect_now"))
        self.connect_hint_label.setText(_t("wizard_connect_hint"))
        self.page(self.PAGE_FINAL).setTitle(_t("wizard_final_title"))

    def nextId(self):
        current = self.currentId()
        if current in (self.PAGE_LANG, self.PAGE_WELCOME, self.PAGE_INSTALL):
            return current + 1
        return -1