# network
import socket
import time
import os
import subprocess
from typing import List, Tuple, Optional, Dict
from resources.constants import CREATE_NO_WINDOW

def socks_proxy_url(port: int, remote_dns: bool = True) -> str:
    scheme = "socks5h" if remote_dns else "socks5"
    return f"{scheme}://127.0.0.1:{port}"

def requests_proxies(port: int) -> Dict[str, str]:
    url = socks_proxy_url(port)
    return {"http": url, "https": url}

def build_proxy_env(port: int) -> Dict[str, str]:
    env = os.environ.copy()
    url = socks_proxy_url(port)
    env["ALL_PROXY"] = url
    env["HTTP_PROXY"] = url
    env["HTTPS_PROXY"] = url
    env["all_proxy"] = url
    env["http_proxy"] = url
    env["https_proxy"] = url
    return env

def build_launch_args(exe_path: str, port: int) -> Tuple[List[str], Optional[str]]:
    name_lower = os.path.basename(exe_path).lower()
    url = socks_proxy_url(port)
    if any(k in name_lower for k in ("chrome", "msedge", "edge", "brave", "opera", "vivaldi")):
        return [exe_path, f"--proxy-server={url}"], None
    if "firefox" in name_lower:
        return [exe_path], "launch_firefox_warning"
    return [exe_path], None

def ping_region(host: str, port: int = 443, timeout: float = 2.0) -> Optional[int]:
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return int((time.time() - start) * 1000)
    except Exception:
        return None

def ping_dns(server: str, timeout: float = 1.0) -> Optional[int]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        start = time.time()
        sock.sendto(b"\x00" * 12, (server, 53))
        sock.recvfrom(1024)
        elapsed = (time.time() - start) * 1000
        sock.close()
        return int(elapsed)
    except Exception:
        return None

def parse_cf_trace(text: str) -> Dict[str, str]:
    data = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data