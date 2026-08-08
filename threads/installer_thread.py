# installer thread
import requests
from PyQt5.QtCore import QThread, pyqtSignal

class InstallerDownloadThread(QThread):
    progress_signal = pyqtSignal(int, float, float)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, url: str, dest_path: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path

    def run(self) -> None:
        try:
            resp = requests.get(self.url, stream=True, timeout=30)
            if resp.status_code != 200:
                self.finished_signal.emit(False, f"HTTP {resp.status_code}")
                return
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(self.dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded * 100 / total)
                        self.progress_signal.emit(pct, downloaded / (1024 * 1024), total / (1024 * 1024))
            self.finished_signal.emit(True, self.dest_path)
        except Exception as e:
            self.finished_signal.emit(False, str(e))