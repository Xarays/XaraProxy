# monitor thread
import psutil
from PyQt5.QtCore import QThread, pyqtSignal

class ConnectionsMonitorThread(QThread):
    result_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self.port = port

    def run(self) -> None:
        try:
            rows = []
            pid_name_cache = {}
            for conn in psutil.net_connections(kind="tcp"):
                if not conn.laddr or conn.laddr.port != self.port:
                    continue
                if not conn.raddr:
                    continue
                pid = conn.pid or -1
                if pid not in pid_name_cache:
                    try:
                        pid_name_cache[pid] = psutil.Process(pid).name() if pid > 0 else "unknown"
                    except Exception:
                        pid_name_cache[pid] = "unknown"
                rows.append((pid, pid_name_cache[pid], f"{conn.raddr.ip}:{conn.raddr.port}"))
            self.result_signal.emit(rows)
        except Exception as e:
            self.error_signal.emit(str(e))