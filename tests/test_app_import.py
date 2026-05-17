def test_app_modules_import_without_starting_gui():
    import industrial_gateway.app
    import industrial_gateway.gui.main_window

    assert industrial_gateway.app.main is not None
    assert industrial_gateway.app.install_tray_icon is not None
    assert hasattr(industrial_gateway.gui.main_window.MainWindow, "request_exit")
    assert hasattr(industrial_gateway.gui.main_window.MainWindow, "show_from_tray")
