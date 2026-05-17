from __future__ import annotations

from pathlib import Path
from queue import Queue
from typing import Any

from industrial_gateway.defaults import driver_registry, sink_registry
from industrial_gateway.gui.connection_forms import (
    ConnectionField,
    connection_fields_for_driver,
    normalize_connection_for_driver,
    tag_function_choices_for_driver,
    tag_type_choices_for_driver,
)
from industrial_gateway.gui.plugin_forms import (
    PluginField,
    normalize_plugin_config,
    plugin_fields,
)
from industrial_gateway.logging_worker import AsyncLogWorker
from industrial_gateway.models import DeviceSpec, MqttConfig, SinkConfig, TagSpec
from industrial_gateway.store import ConfigStore
from industrial_gateway.workers import DriverPoller, OpcUaSubscriptionWorker, ReadResult, SinkPublisher

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    QMainWindow = object


class MainWindow(QMainWindow):
    def __init__(self, store_path: str | Path) -> None:
        if QMainWindow is object:
            raise RuntimeError("PySide6 is required to start the GUI")
        super().__init__()
        self.store = ConfigStore(store_path)
        self.store.initialize()
        self.result_queue: Queue[ReadResult] = Queue()
        self.status_queue: Queue[str] = Queue()
        self.log_display_queue: Queue[str] = Queue()
        self.pollers: list[DriverPoller] = []
        self.subscription_workers: list[OpcUaSubscriptionWorker] = []
        self.publisher: SinkPublisher | None = None
        self.current_tags: list[TagSpec] = []
        self.plugin_inputs: dict[str, Any] = {}
        self.logger = AsyncLogWorker(self.log_display_queue, debug_enabled=False)
        self.logger.start()
        self.setWindowTitle("Industrial Gateway")
        self.resize(980, 680)
        self._build_ui()
        self._load_from_store()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._drain_status)
        self.status_timer.start(500)
        self._allow_exit = False

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._device_tab(), "Devices")
        tabs.addTab(self._plugin_tab(), "Plugins")
        tabs.addTab(self._runtime_tab(), "Runtime")
        self.setCentralWidget(tabs)

    def _device_tab(self) -> QWidget:
        widget = QWidget()
        root = QHBoxLayout(widget)

        device_box = QWidget()
        device_layout = QVBoxLayout(device_box)
        device_layout.addWidget(QLabel("Devices"))
        self.device_list = QListWidget()
        self.device_list.currentRowChanged.connect(self._select_device)
        device_layout.addWidget(self.device_list)
        root.addWidget(device_box, 1)

        tag_box = QWidget()
        tag_layout = QVBoxLayout(tag_box)
        tag_layout.addWidget(QLabel("Tags for selected device"))
        self.tag_list = QListWidget()
        self.tag_list.currentRowChanged.connect(self._select_tag)
        tag_layout.addWidget(self.tag_list)
        root.addWidget(tag_box, 1)

        editor_tabs = QTabWidget()
        editor_tabs.addTab(self._device_editor_tab(), "Device Settings")
        editor_tabs.addTab(self._tag_editor_tab(), "Tag Editor")
        root.addWidget(editor_tabs, 2)
        return widget

    def _device_editor_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.device_name = QLineEdit()
        self.device_driver = QComboBox()
        self.device_driver.addItems(driver_registry.keys())
        self.device_driver.currentTextChanged.connect(self._rebuild_connection_form)
        self.device_driver.currentTextChanged.connect(self._update_tag_choices)
        self.device_enabled = QCheckBox()
        self.device_enabled.setChecked(True)
        self.device_poll = QSpinBox()
        self.device_poll.setRange(100, 60000)
        self.device_poll.setValue(1000)
        self.connection_form_widget = QWidget()
        self.connection_form = QFormLayout(self.connection_form_widget)
        self.connection_inputs: dict[str, Any] = {}
        self.tag_name = QLineEdit("temperature")
        add_device = QPushButton("Add Device")
        add_device.clicked.connect(self._add_device)
        update_device = QPushButton("Update Device")
        update_device.clicked.connect(self._update_device)
        delete_device = QPushButton("Delete Device")
        delete_device.clicked.connect(self._delete_device)
        test_device = QPushButton("Test Connection")
        test_device.clicked.connect(self._test_connection)
        for label, control in [
            ("Name", self.device_name),
            ("Driver", self.device_driver),
            ("Enabled", self.device_enabled),
            ("Poll ms", self.device_poll),
            ("Connection", self.connection_form_widget),
        ]:
            form.addRow(label, control)
        form.addRow(add_device)
        form.addRow(update_device)
        form.addRow(delete_device)
        form.addRow(test_device)
        layout.addLayout(form)
        layout.addStretch()
        self._rebuild_connection_form()
        return widget

    def _tag_editor_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.tag_name = QLineEdit("temperature")
        self.tag_node_id = QLineEdit()
        self.tag_address = QSpinBox()
        self.tag_address.setRange(0, 999999)
        self.tag_function = QComboBox()
        self.tag_type = QComboBox()
        self.tag_scale = QLineEdit("1.0")
        self.tag_words = QSpinBox()
        self.tag_words.setRange(1, 128)
        self.tag_words.setValue(1)
        self.tag_byte_order = QComboBox()
        self.tag_byte_order.addItems(["big", "little"])
        self.tag_word_order = QComboBox()
        self.tag_word_order.addItems(["big", "little"])
        add_tag = QPushButton("Add Tag")
        add_tag.clicked.connect(self._add_tag)
        update_tag = QPushButton("Update Tag")
        update_tag.clicked.connect(self._update_tag)
        delete_tag = QPushButton("Delete Tag")
        delete_tag.clicked.connect(self._delete_tag)
        for label, control in [
            ("Tag name", self.tag_name),
            ("OPC UA NodeId", self.tag_node_id),
            ("Tag address", self.tag_address),
            ("Tag function", self.tag_function),
            ("Tag type", self.tag_type),
            ("Tag scale", self.tag_scale),
            ("Tag words", self.tag_words),
            ("Byte order", self.tag_byte_order),
            ("Word order", self.tag_word_order),
        ]:
            form.addRow(label, control)
        form.addRow(add_tag)
        form.addRow(update_tag)
        form.addRow(delete_tag)
        self._update_tag_choices()
        return widget

    def _plugin_tab(self) -> QWidget:
        widget = QWidget()
        root = QHBoxLayout(widget)
        plugin_box = QWidget()
        plugin_layout = QVBoxLayout(plugin_box)
        plugin_layout.addWidget(QLabel("Plugins"))
        self.plugin_list = QListWidget()
        self.plugin_list.addItems(sink_registry.keys())
        self.plugin_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.plugin_list.currentTextChanged.connect(self._select_plugin)
        self.plugin_list.setCurrentRow(0)
        plugin_layout.addWidget(self.plugin_list)
        root.addWidget(plugin_box, 1)

        settings_box = QWidget()
        settings_layout = QVBoxLayout(settings_box)
        self.plugin_enabled = QCheckBox("Enabled")
        self.plugin_enabled.setChecked(True)
        self.plugin_form_widget = QWidget()
        self.plugin_form = QFormLayout(self.plugin_form_widget)
        save = QPushButton("Save Plugin")
        save.clicked.connect(self._save_plugin)
        settings_layout.addWidget(self.plugin_enabled)
        settings_layout.addWidget(self.plugin_form_widget)
        settings_layout.addWidget(save)
        settings_layout.addStretch()
        root.addWidget(settings_box, 2)
        self._select_plugin("mqtt")
        return widget

    def _runtime_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.debug_logs = QCheckBox("Debug logs")
        self.debug_logs.toggled.connect(self.logger.set_debug_enabled)
        self.start_button.clicked.connect(self._start_runtime)
        self.stop_button.clicked.connect(self._stop_runtime)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.debug_logs)
        self.runtime_status = QLabel("Stopped")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addLayout(controls)
        layout.addWidget(self.runtime_status)
        layout.addWidget(self.log)
        return widget

    def _load_from_store(self) -> None:
        self.devices = self.store.list_devices()
        self.device_list.clear()
        for device in self.devices:
            self.device_list.addItem(f"{device.name} ({device.driver_type})")
        if self.devices and self.device_list.currentRow() < 0:
            self.device_list.setCurrentRow(0)
        if hasattr(self, "plugin_list"):
            selected_sink = self.store.get_selected_sink_type()
            matches = self.plugin_list.findItems(selected_sink, Qt.MatchExactly)
            if matches:
                self.plugin_list.setCurrentItem(matches[0])

    def _select_device(self, row: int) -> None:
        if row < 0 or row >= len(self.devices):
            return
        device = self.devices[row]
        self.device_name.setText(device.name)
        self.device_driver.setCurrentText(device.driver_type)
        self.device_enabled.setChecked(device.enabled)
        self.device_poll.setValue(device.poll_interval_ms)
        self._set_connection_values(device.driver_type, device.connection)
        self._load_tags_for_selected_device()

    def _load_tags_for_selected_device(self) -> None:
        row = self.device_list.currentRow()
        self.tag_list.clear()
        self.current_tags = []
        if row < 0 or row >= len(self.devices):
            return
        device = self.devices[row]
        self.current_tags = self.store.list_tags(device.id or 0)
        for tag in self.current_tags:
            words = f" words={tag.word_count}" if tag.word_count else ""
            node = f" node={tag.node_id}" if tag.node_id else ""
            self.tag_list.addItem(f"{tag.name}: {tag.function} {tag.address}{node} {tag.data_type}{words} x{tag.scale}")

    def _select_tag(self, row: int) -> None:
        if row < 0 or row >= len(self.current_tags):
            return
        tag = self.current_tags[row]
        self.tag_name.setText(tag.name)
        self.tag_node_id.setText(tag.node_id or "")
        self.tag_address.setValue(tag.address)
        self.tag_function.setCurrentText(tag.function)
        self.tag_type.setCurrentText(tag.data_type)
        self.tag_scale.setText(str(tag.scale))
        self.tag_words.setValue(tag.word_count or 1)
        self.tag_byte_order.setCurrentText(tag.byte_order)
        self.tag_word_order.setCurrentText(tag.word_order)

    def _add_device(self) -> None:
        self._save_device(None)

    def _update_device(self) -> None:
        selected = self.device_list.currentRow()
        if selected < 0 or selected >= len(self.devices):
            QMessageBox.warning(self, "Device error", "Select a device first")
            return
        self._save_device(self.devices[selected].id)

    def _delete_device(self) -> None:
        selected = self.device_list.currentRow()
        if selected < 0 or selected >= len(self.devices):
            QMessageBox.warning(self, "Device error", "Select a device first")
            return
        device = self.devices[selected]
        reply = QMessageBox.question(self, "Delete device", f"Delete device '{device.name}' and its tags?")
        if reply != QMessageBox.Yes:
            return
        self._log("INFO", "button", "Delete Device clicked", {"device": device.__dict__})
        self.store.delete_device(device.id or 0)
        self._load_from_store()
        self.tag_list.clear()
        self.current_tags = []
        self._append_log("Device deleted")

    def _save_device(self, device_id: int | None) -> None:
        try:
            device = DeviceSpec(
                id=device_id,
                name=self.device_name.text(),
                driver_type=self.device_driver.currentText(),
                enabled=self.device_enabled.isChecked(),
                poll_interval_ms=self.device_poll.value(),
                connection=self._connection_values_from_form(),
            )
            self._log(
                "INFO",
                "button",
                "Update Device clicked" if device_id is not None else "Add Device clicked",
                {"device": device.__dict__},
            )
            self.store.save_device(device)
            self._load_from_store()
            self._append_log("Device saved")
        except Exception as exc:
            QMessageBox.critical(self, "Device error", str(exc))

    def _add_tag(self) -> None:
        self._save_tag(None)

    def _update_tag(self) -> None:
        row = self.tag_list.currentRow()
        if row < 0 or row >= len(self.current_tags):
            QMessageBox.warning(self, "Tag error", "Select a tag first")
            return
        self._save_tag(self.current_tags[row].id)

    def _delete_tag(self) -> None:
        row = self.tag_list.currentRow()
        if row < 0 or row >= len(self.current_tags):
            QMessageBox.warning(self, "Tag error", "Select a tag first")
            return
        tag = self.current_tags[row]
        reply = QMessageBox.question(self, "Delete tag", f"Delete tag '{tag.name}'?")
        if reply != QMessageBox.Yes:
            return
        self._log("INFO", "button", "Delete Tag clicked", {"tag": tag.__dict__})
        self.store.delete_tag(tag.id or 0)
        self._load_tags_for_selected_device()
        self._append_log("Tag deleted")

    def _save_tag(self, tag_id: int | None) -> None:
        row = self.device_list.currentRow()
        if row < 0 or row >= len(self.devices):
            QMessageBox.warning(self, "Tag error", "Select a device first")
            return
        try:
            tag = TagSpec(
                id=tag_id,
                device_id=self.devices[row].id,
                name=self.tag_name.text(),
                address=self.tag_address.value(),
                function=self.tag_function.currentText(),
                data_type=self.tag_type.currentText(),
                scale=float(self.tag_scale.text()),
                word_count=self.tag_words.value() if self.tag_type.currentText() == "string" else None,
                byte_order=self.tag_byte_order.currentText(),
                word_order=self.tag_word_order.currentText(),
                node_id=self.tag_node_id.text() or None,
            )
            self.store.save_tag(
                tag
            )
            self._log(
                "INFO",
                "button",
                "Update Tag clicked" if tag_id is not None else "Add Tag clicked",
                {"tag": tag.__dict__},
            )
            self._load_tags_for_selected_device()
            self._append_log("Tag saved")
        except Exception as exc:
            QMessageBox.critical(self, "Tag error", str(exc))

    def _save_plugin(self) -> None:
        sink_config = SinkConfig(
            sink_type=self.plugin_list.currentItem().text(),
            enabled=self.plugin_enabled.isChecked(),
            config=self._plugin_values_from_form(),
        )
        self._log("INFO", "button", "Save Plugin clicked", {"sink": sink_config.__dict__})
        self.store.save_sink_config(sink_config)
        self._append_log("Plugin config saved")

    def _test_connection(self) -> None:
        row = self.device_list.currentRow()
        if row < 0 or row >= len(self.devices):
            QMessageBox.warning(self, "Connection test", "Select a device first")
            return
        device = self.devices[row]
        self._log("INFO", "button", "Test Connection clicked", {"device": device.__dict__})
        driver_class = driver_registry.get(device.driver_type)
        driver = driver_class(device, [])
        try:
            driver.connect()
            QMessageBox.information(self, "Connection test", "Connection succeeded")
        except Exception as exc:
            QMessageBox.critical(self, "Connection test", str(exc))
        finally:
            driver.disconnect()

    def _start_runtime(self) -> None:
        self._log("INFO", "button", "Start clicked", {})
        self._save_plugin()
        sink_config = self.store.get_sink_config()
        sink_class = sink_registry.get(sink_config.sink_type)
        sink = sink_class({**sink_config.config, "enabled": sink_config.enabled})
        message_config = MqttConfig(
            base_topic=sink_config.config.get("base_topic", "industrial"),
            qos=int(sink_config.config.get("qos", 0)),
        )
        self.publisher = SinkPublisher(
            sink,
            message_config,
            self.result_queue,
            self.status_queue,
            log_queue=self.logger.input_queue,
        )
        self.publisher.start()
        self.pollers = []
        self.subscription_workers = []
        for device in self.store.list_devices():
            if not device.enabled:
                continue
            driver_class = driver_registry.get(device.driver_type)
            tags = self.store.list_tags(device.id or 0)
            if device.driver_type == "opcua" and device.connection.get("mode") == "subscription":
                worker = OpcUaSubscriptionWorker(
                    driver_class,
                    device,
                    tags,
                    self.result_queue,
                    log_queue=self.logger.input_queue,
                )
                worker.start()
                self.subscription_workers.append(worker)
            else:
                poller = DriverPoller(
                    driver_class,
                    device,
                    tags,
                    self.result_queue,
                    log_queue=self.logger.input_queue,
                )
                poller.start()
                self.pollers.append(poller)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.runtime_status.setText(f"Running: {len(self.pollers) + len(self.subscription_workers)} devices")
        self._append_log("Runtime started")

    def _stop_runtime(self) -> None:
        self._log("INFO", "button", "Stop clicked", {})
        for poller in self.pollers:
            poller.stop()
        for worker in self.subscription_workers:
            worker.stop()
        if self.publisher is not None:
            self.publisher.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.runtime_status.setText("Stopped")
        self._append_log("Runtime stopped")

    def _drain_status(self) -> None:
        while not self.status_queue.empty():
            self._append_log(self.status_queue.get())
        while not self.log_display_queue.empty():
            self._append_log(self.log_display_queue.get())

    def _append_log(self, message: str) -> None:
        self.log.append(message)

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        self.logger.log(level, source, message, data)

    def _select_plugin(self, plugin_type: str) -> None:
        if not hasattr(self, "plugin_form"):
            return
        sink_config = self.store.get_sink_config(plugin_type)
        self.plugin_enabled.setChecked(sink_config.enabled)
        self._rebuild_plugin_form(plugin_type, normalize_plugin_config(plugin_type, sink_config.config))

    def _rebuild_plugin_form(self, plugin_type: str, values: dict[str, Any]) -> None:
        while self.plugin_form.count():
            item = self.plugin_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.plugin_inputs = {}
        for field in plugin_fields(plugin_type):
            control = self._create_plugin_control(field, values[field.key])
            self.plugin_inputs[field.key] = control
            self.plugin_form.addRow(field.label, control)

    def _set_plugin_values(self, plugin_type: str, values: dict[str, Any]) -> None:
        self._rebuild_plugin_form(plugin_type, normalize_plugin_config(plugin_type, values))

    def _plugin_values_from_form(self) -> dict[str, Any]:
        plugin_type = self.plugin_list.currentItem().text()
        values = {}
        for field in plugin_fields(plugin_type):
            control = self.plugin_inputs[field.key]
            if field.kind == "bool":
                values[field.key] = control.isChecked()
            elif field.kind == "int":
                values[field.key] = control.value()
            else:
                values[field.key] = control.text()
        return values

    def _create_plugin_control(self, field: PluginField, value: Any) -> Any:
        if field.kind == "bool":
            control = QCheckBox()
            control.setChecked(bool(value))
            return control
        if field.kind == "int":
            control = QSpinBox()
            control.setRange(field.minimum or 0, field.maximum or 9999999)
            control.setValue(int(value))
            return control
        control = QLineEdit(str(value or ""))
        if field.kind == "password":
            control.setEchoMode(QLineEdit.Password)
        return control

    def _update_tag_choices(self) -> None:
        if not hasattr(self, "tag_function"):
            return
        driver_type = self.device_driver.currentText()
        self._replace_combo_items(self.tag_function, tag_function_choices_for_driver(driver_type))
        self._replace_combo_items(self.tag_type, tag_type_choices_for_driver(driver_type))

    def _rebuild_connection_form(self) -> None:
        if not hasattr(self, "connection_form"):
            return
        while self.connection_form.count():
            item = self.connection_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        driver_type = self.device_driver.currentText()
        values = default_values = normalize_connection_for_driver(driver_type, None)
        self.connection_inputs = {}
        for field in connection_fields_for_driver(driver_type):
            control = self._create_connection_control(field, default_values[field.key])
            self.connection_inputs[field.key] = control
            self.connection_form.addRow(field.label, control)

    def _set_connection_values(self, driver_type: str, connection: dict[str, Any]) -> None:
        if self.device_driver.currentText() != driver_type:
            self.device_driver.setCurrentText(driver_type)
        values = normalize_connection_for_driver(driver_type, connection)
        for field in connection_fields_for_driver(driver_type):
            control = self.connection_inputs.get(field.key)
            if control is None:
                continue
            self._set_connection_control_value(control, values[field.key])

    def _connection_values_from_form(self) -> dict[str, Any]:
        values = {}
        for field in connection_fields_for_driver(self.device_driver.currentText()):
            control = self.connection_inputs[field.key]
            values[field.key] = self._connection_control_value(field, control)
        return values

    def _create_connection_control(self, field: ConnectionField, value: Any) -> Any:
        if field.kind == "choice":
            control = QComboBox()
            control.addItems(field.choices)
            control.setCurrentText(str(value))
            return control
        if field.kind == "int":
            control = QSpinBox()
            control.setRange(field.minimum or 0, field.maximum or 9999999)
            control.setValue(int(value))
            return control
        control = QLineEdit(str(value))
        return control

    def _set_connection_control_value(self, control: Any, value: Any) -> None:
        if isinstance(control, QComboBox):
            control.setCurrentText(str(value))
        elif isinstance(control, QSpinBox):
            control.setValue(int(value))
        else:
            control.setText(str(value))

    def _connection_control_value(self, field: ConnectionField, control: Any) -> Any:
        if field.kind == "choice":
            return control.currentText()
        if field.kind == "int":
            return control.value()
        if field.kind == "float":
            return float(control.text())
        return control.text()

    def _replace_combo_items(self, combo: QComboBox, values: list[str]) -> None:
        current = combo.currentText()
        combo.clear()
        combo.addItems(values)
        if current in values:
            combo.setCurrentText(current)

    def closeEvent(self, event: Any) -> None:
        if self._allow_exit:
            self.shutdown()
            event.accept()
            return
        event.ignore()
        self.hide()
        self._append_log("Window hidden to system tray")

    def show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def request_exit(self) -> None:
        self._allow_exit = True
        self.close()
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.quit()
        except ImportError:
            pass

    def shutdown(self) -> None:
        self._stop_runtime()
        self.status_timer.stop()
        self.logger.stop()
