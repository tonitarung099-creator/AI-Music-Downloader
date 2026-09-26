from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _prepare_portable_tools() -> None:
    """Expose bundled command-line tools without requiring system installs."""
    tools = _application_root() / "tools"
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
        # Verify the frozen package can import the full UI and can see the
        # bundled external runtimes required for actual downloads.
        if window.windowTitle() != "AI Music Downloader":
            return 2
        if getattr(sys, "frozen", False):
            tools = _application_root() / "tools"
            if not (tools / "ffmpeg.exe").exists():
                return 3
            if not (tools / "deno.exe").exists():
                return 4
            if shutil.which("deno") is None:
                return 5
        window.close()
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
