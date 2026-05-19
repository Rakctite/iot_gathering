from __future__ import annotations

import sys
from pathlib import Path


def _preload_opcua_imports() -> None:
    try:
        import dateutil.tz  # noqa: F401
    except ImportError:
        pass


def main() -> int:
    _preload_opcua_imports()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError("PySide6 is required to run the GUI. Install project dependencies first.") from exc
    from industrial_gateway.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    store_path = Path.home() / ".industrial_gateway" / "gateway.sqlite3"
    window = MainWindow(store_path)
    tray = install_tray_icon(app, window)
    app._industrial_gateway_tray = tray
    window.show()
    return app.exec()


def install_tray_icon(app, window):
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon

    icon = app.style().standardIcon(QStyle.SP_ComputerIcon)
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Industrial Gateway")

    menu = QMenu()
    show_action = QAction("Show Window", menu)
    exit_action = QAction("Exit", menu)
    show_action.triggered.connect(window.show_from_tray)
    exit_action.triggered.connect(window.request_exit)
    menu.addAction(show_action)
    menu.addSeparator()
    menu.addAction(exit_action)

    tray.setContextMenu(menu)

    def on_activated(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            window.show_from_tray()

    tray.activated.connect(on_activated)
    app.aboutToQuit.connect(tray.hide)
    tray.show()
    return tray


if __name__ == "__main__":
    raise SystemExit(main())
