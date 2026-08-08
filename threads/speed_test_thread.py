# speed test thread
import time
import requests
from PyQt5.QtCore import QThread, pyqtSignal
from utils.network import requests_proxies
from resources.strings import _t

class SpeedTestThread(QThread):
    result_signal = pyqtSignal(float)
    error_signal = pyqtSignal(str)

    def __init__(self, mode: str, port: int, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.port = port

    def run(self) -> None:
        try:
            proxies = requests_proxies(self.port) if self.mode == "proxy" else None
            url = "https://speed.cloudflare.com/__down?bytes=26214400"
            start = time.time()
            total_bytes = 0
            resp = requests.get(url, proxies=proxies, stream=True, timeout=15)
            for chunk in resp.iter_content(chunk_size=131072):
                if not chunk:
                    continue
                total_bytes += len(chunk)
                if time.time() - start > 6.0:
                    break
            elapsed = max(0.05, time.time() - start)
            mbps = (total_bytes * 8) / elapsed / 1_000_000
            self.result_signal.emit(mbps)
        except Exception as e:
            self.error_signal.emit(str(e))