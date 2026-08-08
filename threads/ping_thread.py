# ping thread
from PyQt5.QtCore import QThread, pyqtSignal
import requests
from utils.network import ping_region, ping_dns, parse_cf_trace, requests_proxies
from resources.constants import DNS_SERVERS, REGION_HOSTS, POPULAR_ENDPOINTS

class PingThread(QThread):
    result_signal = pyqtSignal(dict)

    def __init__(self, hosts: dict, parent=None):
        super().__init__(parent)
        self.hosts = hosts

    def run(self) -> None:
        results = {region: ping_region(host) for region, host in self.hosts.items()}
        self.result_signal.emit(results)

class DNSCheckThread(QThread):
    result_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self) -> None:
        best, best_time = None, float("inf")
        for server, _ in DNS_SERVERS:
            t = ping_dns(server)
            if t is not None and t < best_time:
                best_time, best = t, server
        if best:
            self.result_signal.emit(best)

class EndpointPingThread(QThread):
    result_signal = pyqtSignal(dict)

    def __init__(self, endpoints: list, parent=None):
        super().__init__(parent)
        self.endpoints = endpoints

    def run(self) -> None:
        results = {}
        for ep in self.endpoints:
            host = ep.split(":")[0]
            results[ep] = ping_region(host, port=443, timeout=1.5)
        self.result_signal.emit(results)

class TraceCheckThread(QThread):
    result_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, mode: str, port: int, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.port = port

    def run(self) -> None:
        try:
            if self.mode == "proxy":
                proxies = requests_proxies(self.port)
                resp = requests.get("https://www.cloudflare.com/cdn-cgi/trace", proxies=proxies, timeout=8)
            else:
                resp = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=8)
            self.result_signal.emit(parse_cf_trace(resp.text))
        except Exception as e:
            self.error_signal.emit(str(e))