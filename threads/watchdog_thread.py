# watchdog thread
import time
import subprocess
import psutil
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from resources.constants import CREATE_NO_WINDOW

class WarpServiceWatchdogThread(QThread):
    service_down = pyqtSignal()
    service_recovered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_flag = False
        self._mutex = QMutex()
        self._was_down = False

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop_flag = True

    @staticmethod
    def is_service_alive() -> bool:
        try:
            for proc in psutil.process_iter(["name"]):
                if (proc.info["name"] or "").lower() == "warp-svc.exe":
                    return True
        except Exception:
            return True
        return False

    @staticmethod
    def try_restart_service() -> bool:
        try:
            result = subprocess.run(["sc", "start", "CloudflareWARP"], capture_output=True, text=True,
                                     timeout=10, creationflags=CREATE_NO_WINDOW, check=False)
            return result.returncode == 0
        except Exception:
            return False

    def run(self) -> None:
        while True:
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    return
            time.sleep(10)
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    return
            alive = self.is_service_alive()
            if not alive and not self._was_down:
                self._was_down = True
                self.service_down.emit()
                self.try_restart_service()
            elif alive and self._was_down:
                self._was_down = False
                self.service_recovered.emit()