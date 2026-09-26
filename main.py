from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_portable_tools() -> None:
    """Expose bundled command-line tools without requiring system installs."""
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parent

    tools = root / "tools"
    if not tools.exists():
        return

    current_path = os.environ.get("PATH", "")
    tools_text = str(tools)
    path_parts = current_path.split(os.pathsep) if current_path else []
    if tools_text not in path_parts:
        os.environ["PATH"] = tools_text + (os.pathsep + current_path if current_path else "")


_prepare_portable_tools()

from PySide6.QtWidgets import QApplication

from app.ui.main_window_v3 import MainWindow


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
