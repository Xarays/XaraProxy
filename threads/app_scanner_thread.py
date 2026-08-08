# app scanner thread
import os
import psutil
from PyQt5.QtCore import QThread, pyqtSignal
from resources.constants import SYSTEM_PROCESS_BLOCKLIST, SCAN_ROOTS
from resources.strings import _t

class AppScannerThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(list)

    def __init__(self, hidden_apps=None, parent=None):
        super().__init__(parent)
        self.hidden_apps = hidden_apps or []

    @staticmethod
    def guess_category(name, path):
        name_lower = name.lower()
        path_lower = (path or "").lower()
        if any(t in name_lower for t in ("steam", "epic", "battle.net", "origin", "uplay")):
            return _t("cat_games")
        if any(t in name_lower for t in ("chrome", "firefox", "edge", "opera", "brave")):
            return _t("cat_browsers")
        if any(t in name_lower for t in ("discord", "telegram", "whatsapp", "viber", "skype", "zoom", "signal", "teamspeak")):
            return _t("cat_messengers")
        if any(t in name_lower for t in ("office", "word", "excel", "powerpoint", "outlook", "adobe", "pdf")):
            return _t("cat_office")
        if any(t in name_lower for t in ("git", "vscode", "pycharm", "idea", "studio", "notepad++")):
            return _t("cat_dev")
        if any(t in name_lower for t in ("spotify", "vlc", "media player", "music", "video")):
            return _t("cat_media")
        if "games" in path_lower:
            return _t("cat_games")
        return _t("cat_other")

    def run(self):
        apps = []
        seen_paths = set()
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = (proc.info["name"] or "").strip()
                exe = proc.info["exe"] or ""
                if not name or not exe or not os.path.exists(exe):
                    continue
                if name.lower() in SYSTEM_PROCESS_BLOCKLIST:
                    continue
                if self._is_system_path(exe) or exe in seen_paths or exe in self.hidden_apps:
                    continue
                seen_paths.add(exe)
                apps.append({"name": name, "path": exe, "category": self.guess_category(name, exe)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        for root in SCAN_ROOTS:
            if not root or not os.path.isdir(root):
                continue
            self.progress_signal.emit(f"Scanning {root}...")
            try:
                for entry in os.scandir(root):
                    if not entry.is_dir():
                        continue
                    found_exe = None
                    try:
                        for f in os.listdir(entry.path):
                            if f.lower().endswith(".exe"):
                                full_path = os.path.join(entry.path, f)
                                if os.path.isfile(full_path):
                                    found_exe = full_path
                                    break
                    except (PermissionError, OSError):
                        continue
                    if found_exe and found_exe not in seen_paths and found_exe not in self.hidden_apps:
                        seen_paths.add(found_exe)
                        app_name = os.path.splitext(os.path.basename(found_exe))[0]
                        if app_name.lower() in ("application", "app", "program", "launcher"):
                            app_name = entry.name
                        apps.append({"name": app_name, "path": found_exe,
                                     "category": self.guess_category(app_name, found_exe)})
            except (PermissionError, OSError):
                continue

        unique = {}
        for app in apps:
            key = app["name"].lower()
            if key not in unique or len(app["path"]) < len(unique[key]["path"]):
                unique[key] = app
        self.finished_signal.emit(sorted(unique.values(), key=lambda x: x["name"].lower()))

    @staticmethod
    def _is_system_path(path):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        try:
            return os.path.normpath(path).lower().startswith(os.path.normpath(windir).lower())
        except Exception:
            return False