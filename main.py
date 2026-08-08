# main
import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.widgets import apply_strict_dark_theme
from resources.strings import set_language
from utils.config import load_config

def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    apply_strict_dark_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()