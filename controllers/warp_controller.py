# warp controller
import time
import subprocess
import requests
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from utils.system import find_warp_cli
from utils.network import parse_cf_trace, requests_proxies
from resources.strings import _t
from resources.constants import CREATE_NO_WINDOW

class WarpController(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(dict)

    def __init__(self, warp_cli_path: str, port: int = 40000, mode: str = "proxy",
                 auto_reconnect: bool = True, custom_endpoint: str = "", region: str = "auto"):
        super().__init__()
        self.warp_cli_path = warp_cli_path
        self.port = port
        self.mode = mode
        self.auto_reconnect = auto_reconnect
        self.custom_endpoint = (custom_endpoint or "").strip()
        self.region = region
        self._stop_flag = False
        self._mutex = QMutex()

    def _run_cli(self, args, timeout=10, check=True):
        cmd = [self.warp_cli_path] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                     creationflags=CREATE_NO_WINDOW, shell=False)
            if check and result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "unknown error").strip())
            return (result.stdout or "").strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command '{' '.join(cmd)}' timed out after {timeout}s")
        except Exception as e:
            raise RuntimeError(f"Execution error: {e}")

    def _set_mode(self, mode):
        for cmd in (["mode", mode], ["set-mode", mode]):
            try:
                self._run_cli(cmd)
                return True
            except Exception:
                continue
        return False

    def _set_port(self):
        for cmd in (["proxy", "port", str(self.port)], ["set-proxy-port", str(self.port)]):
            try:
                self._run_cli(cmd)
                return True
            except Exception:
                continue
        return False

    def _set_custom_endpoint(self, endpoint):
        if not endpoint:
            return False
        for cmd in (["tunnel", "host", "set", endpoint], ["tunnel", "host", endpoint]):
            try:
                self._run_cli(cmd)
                return True
            except Exception:
                continue
        return False

    def _set_region(self, region):
        if region == "auto":
            return True
        for cmd in (["set-location", region], ["set-country", region]):
            try:
                self._run_cli(cmd)
                return True
            except Exception:
                continue
        return False

    def _get_status(self):
        try:
            return self._run_cli(["status"], timeout=6, check=False)
        except Exception:
            return ""

    def _is_registered(self, status_text):
        low = status_text.lower()
        return "registration missing" not in low and "not registered" not in low

    def _register(self):
        for cmd in (["registration", "new"], ["register"]):
            try:
                self._run_cli(cmd, timeout=20)
                return True
            except Exception:
                continue
        return False

    def _get_trace(self):
        try:
            if self.mode == "proxy":
                import socks
                resp = requests.get("https://www.cloudflare.com/cdn-cgi/trace",
                                     proxies=requests_proxies(self.port), timeout=6)
            else:
                resp = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=6)
            return parse_cf_trace(resp.text)
        except Exception as e:
            self.log_signal.emit(f"Trace check error: {e}")
            return {}

    def _wait_until_connected(self, timeout):
        start = time.time()
        while time.time() - start < timeout and not self._stop_flag:
            if "connected" in self._get_status().lower():
                return True
            time.sleep(1)
        return False

    def run(self):
        with QMutexLocker(self._mutex):
            self._stop_flag = False
        try:
            status = self._get_status()
            if not self._is_registered(status):
                self.log_signal.emit(_t("registering"))
                if not self._register():
                    raise RuntimeError(_t("register_fail"))

            actual_mode = self.mode
            if not self._set_mode(actual_mode):
                self.log_signal.emit(f"Mode {actual_mode} failed, trying alternative")
                actual_mode = "warp" if actual_mode == "proxy" else "proxy"
                if not self._set_mode(actual_mode):
                    raise RuntimeError("Failed to set WARP mode")
            self.mode = actual_mode
            self.log_signal.emit(f"{_t('mode_set')}: {self.mode}")

            if self.mode == "proxy":
                self._set_port()
            elif self.mode == "warp" and self.custom_endpoint:
                if self._set_custom_endpoint(self.custom_endpoint):
                    self.log_signal.emit(f"{_t('endpoint_set')}{self.custom_endpoint}")
                else:
                    self.log_signal.emit(_t("no_endpoint"))

            if self.region != "auto":
                if self._set_region(self.region):
                    self.log_signal.emit(f"{_t('region_set')}{self.region}")
                else:
                    self.log_signal.emit(_t("region_fail"))

            self._run_cli(["connect"])
            if not self._wait_until_connected(30):
                self.status_signal.emit({"connected": False, "mode": self.mode, "ip": "", "message": _t("warp_failed")})
                return

            trace = self._get_trace()
            ip = trace.get("ip", "unknown")
            country = trace.get("loc", "-")
            warp_status = trace.get("warp", "off")
            if warp_status.lower() != "on":
                self.log_signal.emit(_t("warp_inactive"))
            self.log_signal.emit(f"WARP connected. IP: {ip}, country: {country}, mode: {self.mode}")
            self.status_signal.emit({"connected": True, "mode": self.mode, "ip": ip,
                                      "country": country, "message": _t("connected")})
        except Exception as e:
            self.log_signal.emit(f"Connection error: {e}")
            self.status_signal.emit({"connected": False, "mode": self.mode, "ip": "", "message": str(e)})
            return
        self._monitor_loop()

    def _monitor_loop(self):
        fails = 0
        max_fails = 10
        while not self._stop_flag:
            time.sleep(5)
            if self._stop_flag:
                break
            if "connected" in self._get_status().lower():
                fails = 0
                continue
            fails += 1
            self.log_signal.emit(_t("connection_lost") % fails)
            self.status_signal.emit({"connected": False, "mode": self.mode, "ip": "",
                                      "message": _t("connection_lost") % fails})
            if not self.auto_reconnect:
                continue
            delay = min(20, 2 ** fails)
            self.log_signal.emit(_t("reconnecting") % delay)
            time.sleep(delay)
            try:
                self._run_cli(["connect"])
                if self._wait_until_connected(15):
                    trace = self._get_trace()
                    ip = trace.get("ip", "unknown")
                    country = trace.get("loc", "-")
                    self.log_signal.emit(_t("reconnected") % (ip, country))
                    self.status_signal.emit({"connected": True, "mode": self.mode, "ip": ip,
                                              "country": country, "message": _t("connected")})
                    fails = 0
                else:
                    self.log_signal.emit(_t("reconnect_failed"))
            except Exception as e:
                self.log_signal.emit(f"Reconnection error: {e}")
            if fails > max_fails:
                self.log_signal.emit(_t("reconnect_stop"))
                break

    def stop(self):
        with QMutexLocker(self._mutex):
            self._stop_flag = True
        try:
            self._run_cli(["disconnect"], check=False, timeout=5)
            self.log_signal.emit(_t("warp_disconnected"))
        except Exception as e:
            self.log_signal.emit(f"Disconnect error: {e}, force killing...")
            try:
                subprocess.run(["taskkill", "/f", "/im", "warp-cli.exe"], capture_output=True,
                                check=False, creationflags=CREATE_NO_WINDOW)
                self.log_signal.emit("WARP force killed")
            except Exception:
                pass