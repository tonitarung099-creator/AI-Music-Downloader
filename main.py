from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window_v2 import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AI Music Downloader")
    app.setOrganizationName("AI Music Downloader")

    window = MainWindow()

    if "--self-test" in sys.argv:
        # Used by the Windows portable build to verify that the frozen EXE can
        # load Qt plus all application imports without entering the event loop.
        if window.windowTitle() != "AI Music Downloader":
            return 2
        window.close()
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
