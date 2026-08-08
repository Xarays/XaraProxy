import os
import sys
import subprocess

# --- Основные параметры приложения ---
APP_NAME = "XaraProxy"
APP_VERSION = "1.0.0"

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(APP_DIR, "xaraproxy_config.json")

# --- Системные флаги для процессов ---
# Этот флаг скрывает окно консоли при вызове subprocess в Windows
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# --- Конфигурация по умолчанию ---
DEFAULT_CONFIG = {
    "proxy_port": 40000,
    "mode": "warp",
    "autostart_windows": False,
    "autostart_action": "nothing",
    "auto_reconnect": True,
    "system_proxy": False,
    "selected_apps": [],
    "hidden_apps": [],
    "dns_server": "1.1.1.1",
    "ui_level": "advanced",
    "custom_endpoint": "",
    "minimize_to_tray": True,
    "onboarding_done": False,
    "stalzone_path": "",
    "stalzone_region": "RU",
    "language": "ru",
    "selected_endpoint": "",
    "warp_region": "auto",
    "sound_enabled": True,
    "excluded_apps": [],
    "profiles": [],
    "kill_switch": False,
    "dns_family_filter": "off",
    "split_tunnel_entries": [],
    "warp_plus_key": "",
}

# --- Пути и ссылки WARP ---
WARP_CLI_PATHS = [
    r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe",
    r"C:\Program Files (x86)\Cloudflare\Cloudflare WARP\warp-cli.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Cloudflare WARP", "warp-cli.exe"),
]

WARP_INSTALLER_URL = "https://1111-releases.cloudflareclient.com/win/latest"

SCAN_ROOTS = [
    os.environ.get("PROGRAMFILES", r"C:\Program Files"),
    os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
]

DNS_SERVERS = [
    ("1.1.1.1", "Cloudflare Primary"),
    ("1.0.0.1", "Cloudflare Secondary"),
    ("8.8.8.8", "Google Primary"),
    ("8.8.4.4", "Google Secondary"),
    ("9.9.9.9", "Quad9"),
    ("208.67.222.222", "OpenDNS"),
    ("77.88.8.8", "Yandex"),
    ("94.140.14.14", "AdGuard"),
]

POPULAR_ENDPOINTS = [
    "162.159.192.1:2408",
    "162.159.193.1:2408",
    "162.159.195.1:2408",
    "162.159.196.1:2408",
    "162.159.198.1:2408",
    "162.159.199.1:2408",
]

SYSTEM_PROCESS_BLOCKLIST = {
    "svchost.exe", "explorer.exe", "taskmgr.exe", "dwm.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "smss.exe", "lsass.exe", "services.exe",
    "spoolsv.exe", "system", "registry", "memcompression", "conhost.exe",
    "runtimebroker.exe", "dllhost.exe", "backgroundtaskhost.exe",
    "cloudflare warp.exe", "warp-svc.exe", "warp-cli.exe",
    "python.exe", "pythonw.exe", "cmd.exe", "powershell.exe",
}

REGION_HOSTS = {
    "RU": "ru.stalzone.ru",
    "EU": "eu.stalzone.ru",
    "NA": "na.stalzone.ru",
}

# --- Цветовая палитра UI ---
C_BG = "#0B0C10"
C_CARD = "#14161E"
C_CARD_HOVER = "#1A1D28"
C_CARD_ALT = "#1C1F2B"
C_INPUT = "#0F1015"
C_BORDER = "#232736"
C_BORDER_LIGHT = "#32374A"

C_TEXT = "#F3F4F6"
C_MUTED = "#8B93A7"

C_ACCENT = "#6C5CE7"
C_ACCENT_HOVER = "#5B4BC4"
C_ACCENT_GLOW = "rgba(108, 92, 231, 0.3)"

C_SUCCESS = "#10B981"
C_SUCCESS_GLOW = "rgba(16, 185, 129, 0.25)"
C_DANGER = "#EF4444"
C_DANGER_HOVER = "#DC2626"
C_WARN = "#F59E0B"

C_CHART_DOWN = "#3B82F6"
C_CHART_UP = "#10B981"

FONT_FAMILY = "Segoe UI, -apple-system, BlinkMacSystemFont, Roboto, sans-serif"