# system
import os
import sys
import ctypes
import subprocess
import winreg
from PyQt5.QtGui import QColor
from resources.constants import WARP_CLI_PATHS, CREATE_NO_WINDOW, C_BG, APP_NAME

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def run_as_admin() -> None:
    try:
        if getattr(sys, "frozen", False):
            script_path = sys.executable
            arguments = " ".join(sys.argv[1:])
        else:
            script_path = sys.executable
            arguments = f'"{os.path.abspath(sys.argv[0])}" ' + " ".join(sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", script_path, arguments, None, 1)
        sys.exit(0)
    except Exception as e:
        print(f"Failed to run as admin: {e}")

def set_windows_autostart(enabled: bool, extra_args: str = "") -> bool:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        if enabled:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" {extra_args}'.strip()
            else:
                exe = sys.executable
                script = os.path.abspath(sys.argv[0])
                cmd = f'"{exe}" "{script}" {extra_args}'.strip()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def find_warp_cli() -> str | None:
    for path in WARP_CLI_PATHS:
        if os.path.exists(path):
            return path
    return None

def is_system_path(path: str) -> bool:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    try:
        return os.path.normpath(path).lower().startswith(os.path.normpath(windir).lower())
    except Exception:
        return False

def set_windows_system_proxy(enable: bool, port: int = 0) -> bool:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enable:
            proxy_value = f"socks=127.0.0.1:{port}"
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_value)
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "localhost;127.*;10.*;172.16.*;192.168.*;<local>")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            try:
                winreg.DeleteValue(key, "ProxyServer")
            except FileNotFoundError:
                pass
            try:
                winreg.DeleteValue(key, "ProxyOverride")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        if enable:
            subprocess.run(["netsh", "winhttp", "set", "proxy", f"proxy-server=socks=127.0.0.1:{port}"],
                            shell=False, check=False, creationflags=CREATE_NO_WINDOW)
        else:
            subprocess.run(["netsh", "winhttp", "reset", "proxy"], shell=False, check=False,
                            creationflags=CREATE_NO_WINDOW)
        return True
    except Exception:
        return False

def enable_acrylic_blur(hwnd: int, color_hex: str = C_BG, opacity: int = 200) -> bool:
    try:
        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        WCA_ACCENT_POLICY = 19
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_ulong),
                ("AnimationId", ctypes.c_int),
            ]
        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(ctypes.c_int)),
                ("SizeOfData", ctypes.c_size_t),
            ]
        accent = ACCENT_POLICY()
        accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        accent.GradientColor = (opacity << 24) | (b << 16) | (g << 8) | r

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.POINTER(ctypes.c_int))
        data.SizeOfData = ctypes.sizeof(accent)

        set_attr = ctypes.windll.user32.SetWindowCompositionAttribute
        set_attr(int(hwnd), ctypes.pointer(data))
        return True
    except Exception:
        return False