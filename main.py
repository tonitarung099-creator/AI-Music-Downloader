from __future__ import annotations

import os
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

from app.services.runtime_self_test import RuntimeSelfTestError, run_portable_runtime_self_test
from app.ui.production_window import MainWindow
from app.version import APP_NAME, APP_VERSION, version_text


def _run_self_test(window: MainWindow) -> int:
    if window.windowTitle() != version_text():
        return 2

    if not getattr(sys, "frozen", False):
        window.close()
        return 0

    try:
        run_portable_runtime_self_test(_application_root(), timeout=15.0)
    except RuntimeSelfTestError:
        window.close()
        return 10

    window.close()
    return 0


def main() -> int:
    if "--version" in sys.argv:
        print(version_text())
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)

    window = MainWindow()

    if "--self-test" in sys.argv:
        return _run_self_test(window)

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
