# warp disconnect thread
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from resources.constants import CREATE_NO_WINDOW

class WarpDisconnectThread(QThread):
    finished_ok = pyqtSignal(bool, str)

    def __init__(self, warp_cli_path: str, parent=None):
        super().__init__(parent)
        self.warp_cli_path = warp_cli_path

    def run(self) -> None:
        try:
            subprocess.run([self.warp_cli_path, "disconnect"], capture_output=True, text=True,
                            timeout=6, creationflags=CREATE_NO_WINDOW, check=False)
            self.finished_ok.emit(True, "")
        except Exception as e:
            try:
                subprocess.run(["taskkill", "/f", "/im", "warp-cli.exe"], capture_output=True,
                                check=False, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
            self.finished_ok.emit(False, str(e))