from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
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
    from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QFileDialog,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTableView,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    class _MissingQt:
        DisplayRole = 0
        TextAlignmentRole = 1
        Horizontal = 1
        AlignCenter = 0
        Orientation = object

    QAbstractTableModel = object
    QModelIndex = object
    Qt = _MissingQt()
    QMainWindow = object
    QTableView = object


class RuntimeTagStatusModel(QAbstractTableModel):
    HEADERS = ["Device", "Tag", "NodeId", "Mode", "Updated", "Age", "Status"]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self.row_by_key: dict[tuple[str, str], int] = {}

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.TextAlignmentRole}:
            return None
        row = self.rows[index.row()]
        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter if index.column() in {3, 5, 6} else None
        key = self.HEADERS[index.column()].lower()
        return row.get(key, "")

    def reset_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.row_by_key = {row["key"]: index for index, row in enumerate(rows)}
        self.endResetModel()

    def apply_update(self, item: dict[str, Any]) -> None:
        key = _runtime_tag_key(str(item.get("device", "")), str(item.get("tag", "")), str(item.get("node_id", "")))
        row = self.row_by_key.get(key)
        if row is None:
            row = len(self.rows)
            self.beginInsertRows(QModelIndex(), row, row)
            self.row_by_key[key] = row
            self.rows.append(
                {
                    "key": key,
                    "device": str(item.get("device", "")),
                    "tag": str(item.get("tag", "")),
                    "nodeid": str(item.get("node_id", "")),
                    "mode": str(item.get("mode", "")),
                    "updated": "",
                    "age": "",
                    "status": "NO DATA",
                    "updated_at": None,
                    "disconnected": False,
                }
            )
            self.endInsertRows()
        row_data = self.rows[row]
        parsed = _parse_timestamp(str(item.get("timestamp", "")))
        row_data.update(
            {
                "device": str(item.get("device", "")),
                "tag": str(item.get("tag", "")),
                "nodeid": str(item.get("node_id", "")),
                "mode": str(item.get("mode", "")),
                "updated": str(item.get("timestamp", "")),
                "age": "0.0s",
                "status": "ERROR" if item.get("quality") == "bad" or item.get("error") else "OK",
                "updated_at": parsed,
                "disconnected": False,
            }
        )
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.HEADERS) - 1), [Qt.DisplayRole])

    def refresh_ages(self, stale_after: int) -> None:
        now = datetime.now(timezone.utc)
        for row, row_data in enumerate(self.rows):
            if row_data.get("disconnected"):
                continue
            updated = row_data.get("updated_at")
            if updated is None:
                if row_data.get("age") or row_data.get("status") != "NO DATA":
                    row_data["age"] = ""
                    row_data["status"] = "NO DATA"
                    self.dataChanged.emit(self.index(row, 5), self.index(row, 6), [Qt.DisplayRole])
                continue
            age = max(0.0, (now - updated.astimezone(timezone.utc)).total_seconds())
            status = row_data["status"]
            if status != "ERROR":
                status = "STALE" if age > stale_after else "OK"
            age_text = f"{age:.1f}s"
            if row_data.get("age") != age_text or row_data.get("status") != status:
                row_data["age"] = age_text
                row_data["status"] = status
                self.dataChanged.emit(self.index(row, 5), self.index(row, 6), [Qt.DisplayRole])

    def mark_disconnected(self) -> None:
        for row, row_data in enumerate(self.rows):
            row_data["age"] = ""
            row_data["status"] = "disconnect"
            row_data["updated_at"] = None
            row_data["disconnected"] = True
            self.dataChanged.emit(self.index(row, 5), self.index(row, 6), [Qt.DisplayRole])


_TAG_CSV_FIELDS = [
    "tag_group",
    "name",
    "node_id",
    "address",
    "function",
    "data_type",
    "scale",
    "enabled",
    "word_count",
    "byte_order",
    "word_order",
]

_DEVICE_CSV_FIELDS = [
    "device_group",
    "device_name",
    "driver_type",
    "enabled",
    "poll_interval_ms",
    "host",
    "port",
    "unit_id",
    "max_block_gap",
    "max_registers_per_read",
    "max_bits_per_read",
    "baudrate",
    "parity",
    "stopbits",
    "bytesize",
    "timeout",
    "endpoint",
    "mode",
    "subscription_interval_ms",
    "tag_group",
    "tag_name",
    "node_id",
    "address",
    "function",
    "data_type",
    "scale",
    "tag_enabled",
    "word_count",
    "byte_order",
    "word_order",
]

_MAX_STATUS_QUEUE_DRAIN_PER_TICK = 5000
_MAX_RUNTIME_TABLE_UPDATES_PER_TICK = 1000


class MainWindow(QMainWindow):
    def __init__(self, store_path: str | Path) -> None:
        if QMainWindow is object:
            raise RuntimeError("PySide6 is required to start the GUI")
        super().__init__()
        self.store = ConfigStore(store_path)
        self.store.initialize()
        self.result_queue: Queue[ReadResult] = Queue()
        self.status_queue: Queue[Any] = Queue()
        self.log_display_queue: Queue[str] = Queue()
        self.pollers: list[DriverPoller] = []
        self.subscription_workers: list[OpcUaSubscriptionWorker] = []
        self.publisher: SinkPublisher | None = None
        self.current_tags: list[TagSpec] = []
        self.runtime_tag_model = RuntimeTagStatusModel()
        self.pending_runtime_tag_updates: dict[tuple[str, str], dict[str, Any]] = {}
        self.runtime_running = False
        self.server_statuses: dict[str, dict[str, Any]] = {}
        self.plugin_inputs: dict[str, Any] = {}
        self.logger = AsyncLogWorker(
            self.log_display_queue,
            debug_enabled=False,
            log_dir=Path(store_path).parent / "industrial_gateway_log",
        )
        self.logger.start()
        self.setWindowTitle("Industrial Gateway")
        self.resize(980, 680)
        self._build_ui()
        self._load_from_store()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._drain_status)
        self.status_timer.start(500)
        self.age_timer = QTimer(self)
        self.age_timer.timeout.connect(self._refresh_runtime_tag_ages)
        self.age_timer.start(1000)
        self._allow_exit = False

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.gathering_status_label = QLabel("Gathering: Stopped")
        self.server_status_label = QLabel("OPC UA Server: Not checked")
        self.health_check_interval = QSpinBox()
        self.health_check_interval.setRange(1, 3600)
        self.health_check_interval.setValue(10)
        self.health_check_interval.setSuffix(" sec")
        self.health_check_interval.valueChanged.connect(self._update_health_interval)
        top.addWidget(self.gathering_status_label)
        top.addWidget(self.server_status_label, 1)
        top.addWidget(QLabel("Server check"))
        top.addWidget(self.health_check_interval)
        tabs = QTabWidget()
        tabs.addTab(self._device_tab(), "Devices")
        tabs.addTab(self._plugin_tab(), "Plugins")
        tabs.addTab(self._runtime_tab(), "Runtime")
        layout.addLayout(top)
        layout.addWidget(tabs)
        self.setCentralWidget(root)

    def _device_tab(self) -> QWidget:
        widget = QWidget()
        root = QHBoxLayout(widget)

        device_box = QWidget()
        device_box.setMaximumWidth(220)
        device_layout = QVBoxLayout(device_box)
        device_layout.addWidget(QLabel("Devices"))
        self.device_list = QListWidget()
        self.device_list.currentRowChanged.connect(self._select_device)
        device_layout.addWidget(self.device_list)
        device_csv_buttons = QHBoxLayout()
        import_devices = QPushButton("Import CSV")
        import_devices.clicked.connect(self._import_devices_csv)
        export_devices = QPushButton("Export CSV")
        export_devices.clicked.connect(self._export_devices_csv)
        device_csv_buttons.addWidget(import_devices)
        device_csv_buttons.addWidget(export_devices)
        device_layout.addLayout(device_csv_buttons)
        root.addWidget(device_box, 1)

        tag_box = QWidget()
        tag_layout = QVBoxLayout(tag_box)
        tag_layout.addWidget(QLabel("Tags for selected device"))
        self.tag_list = QTableWidget()
        self.tag_list.setColumnCount(8)
        self.tag_list.setHorizontalHeaderLabels(
            ["Tag Group", "Tag Name", "NodeId", "Data Type", "Scale", "Words", "Function", "Enabled"]
        )
        self.tag_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tag_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tag_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tag_list.verticalHeader().setVisible(False)
        self.tag_list.horizontalHeader().setStretchLastSection(False)
        self.tag_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tag_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.tag_list.currentCellChanged.connect(lambda row, _col, _prev_row, _prev_col: self._select_tag(row))
        tag_layout.addWidget(self.tag_list)
        root.addWidget(tag_box, 4)

        editor_tabs = QTabWidget()
        editor_tabs.setMaximumWidth(390)
        editor_tabs.addTab(self._device_editor_tab(), "Device Settings")
        editor_tabs.addTab(self._tag_editor_tab(), "Tag Editor")
        root.addWidget(editor_tabs, 2)
        return widget

    def _device_editor_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.device_group = QLineEdit()
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
            ("Group", self.device_group),
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
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.tag_group = QLineEdit()
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
        import_tags = QPushButton("Import CSV")
        import_tags.clicked.connect(self._import_tags_csv)
        export_tags = QPushButton("Export CSV")
        export_tags.clicked.connect(self._export_tags_csv)
        for label, control in [
            ("Tag group", self.tag_group),
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
        csv_buttons = QHBoxLayout()
        csv_buttons.addWidget(import_tags)
        csv_buttons.addWidget(export_tags)
        layout.addLayout(form)
        layout.addLayout(csv_buttons)
        layout.addStretch()
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
        self.runtime_tag_status = QTableView()
        self.runtime_tag_status.setModel(self.runtime_tag_model)
        self.runtime_tag_status.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runtime_tag_status.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runtime_tag_status.verticalHeader().setVisible(False)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.runtime_tag_status.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.runtime_tag_status.setColumnWidth(0, 140)
        self.runtime_tag_status.setColumnWidth(1, 160)
        self.runtime_tag_status.setColumnWidth(3, 95)
        self.runtime_tag_status.setColumnWidth(4, 240)
        self.runtime_tag_status.setColumnWidth(5, 80)
        self.runtime_tag_status.setColumnWidth(6, 90)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.NoWrap)
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addLayout(controls)
        layout.addWidget(self.runtime_status)
        layout.addWidget(self.runtime_tag_status, 1)
        layout.addWidget(self.log)
        return widget

    def _load_from_store(self) -> None:
        self.devices = self.store.list_devices()
        self.device_list.clear()
        for device in self.devices:
            group = f"{device.device_group} / " if device.device_group else ""
            self.device_list.addItem(f"{group}{device.name} ({device.driver_type})")
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
        self.device_group.setText(device.device_group)
        self.device_name.setText(device.name)
        self.device_driver.setCurrentText(device.driver_type)
        self.device_enabled.setChecked(device.enabled)
        self.device_poll.setValue(device.poll_interval_ms)
        self._set_connection_values(device.driver_type, device.connection)
        self._load_tags_for_selected_device()

    def _load_tags_for_selected_device(self) -> None:
        row = self.device_list.currentRow()
        self.tag_list.setRowCount(0)
        self.current_tags = []
        if row < 0 or row >= len(self.devices):
            return
        device = self.devices[row]
        self.current_tags = self.store.list_tags(device.id or 0)
        self.tag_list.setRowCount(len(self.current_tags))
        for index, tag in enumerate(self.current_tags):
            values = [
                tag.tag_group,
                tag.name,
                tag.node_id or "",
                tag.data_type,
                str(tag.scale),
                str(tag.word_count or ""),
                tag.function,
                "Yes" if tag.enabled else "No",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {4, 5, 7}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.tag_list.setItem(index, column, item)
        if self.current_tags:
            self.tag_list.selectRow(0)

    def _select_tag(self, row: int) -> None:
        if row < 0 or row >= len(self.current_tags):
            return
        tag = self.current_tags[row]
        self.tag_group.setText(tag.tag_group)
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
        self.tag_list.setRowCount(0)
        self.current_tags = []
        self._append_log("Device deleted")

    def _save_device(self, device_id: int | None) -> None:
        try:
            device = DeviceSpec(
                id=device_id,
                device_group=self.device_group.text().strip(),
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

    def _import_devices_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import devices CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            count = self._import_devices_csv_path(Path(path))
            self._load_from_store()
            self._append_log(f"Imported {count} devices")
        except Exception as exc:
            QMessageBox.critical(self, "CSV import", str(exc))

    def _export_devices_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export devices CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            count = self._export_devices_csv_path(Path(path))
            self._append_log(f"Exported {count} devices")
        except Exception as exc:
            QMessageBox.critical(self, "CSV export", str(exc))

    def _import_devices_csv_path(self, path: Path) -> int:
        devices_by_key = self._existing_devices_by_import_key()
        imported_tags = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV header is required")
            for row in reader:
                driver_type = (row.get("driver_type") or "modbus_tcp").strip()
                connection = {}
                for field in connection_fields_for_driver(driver_type):
                    value = row.get(field.key)
                    if value is not None and str(value).strip() != "":
                        connection[field.key] = _csv_connection_value(field, value)
                device_name = (row.get("device_name") or row.get("name") or "").strip()
                device = DeviceSpec(
                    id=None,
                    device_group=(row.get("device_group") or "").strip(),
                    name=device_name,
                    driver_type=driver_type,
                    enabled=_csv_bool(row.get("enabled"), True),
                    poll_interval_ms=int(row.get("poll_interval_ms") or 1000),
                    connection=connection,
                )
                key = _device_import_key(device)
                existing = devices_by_key.get(key)
                if existing is None:
                    device_id = self.store.save_device(device)
                    devices_by_key[key] = device
                    device = DeviceSpec(
                        id=device_id,
                        device_group=device.device_group,
                        name=device.name,
                        driver_type=device.driver_type,
                        enabled=device.enabled,
                        poll_interval_ms=device.poll_interval_ms,
                        connection=device.connection,
                    )
                    devices_by_key[key] = device
                else:
                    _validate_same_device_config(existing, device)
                    device_id = existing.id or 0
                tag_name = (row.get("tag_name") or row.get("name") or "").strip()
                if not tag_name:
                    continue
                tag = TagSpec(
                    device_id=device_id,
                    tag_group=(row.get("tag_group") or "").strip(),
                    name=tag_name,
                    node_id=(row.get("node_id") or "").strip() or None,
                    address=int(row.get("address") or 0),
                    function=(row.get("function") or tag_function_choices_for_driver(driver_type)[0]).strip(),
                    data_type=(row.get("data_type") or tag_type_choices_for_driver(driver_type)[0]).strip(),
                    scale=float(row.get("scale") or 1.0),
                    enabled=_csv_bool(row.get("tag_enabled"), True),
                    word_count=_csv_optional_int(row.get("word_count")),
                    byte_order=(row.get("byte_order") or "big").strip(),
                    word_order=(row.get("word_order") or "big").strip(),
                )
                self.store.save_tag(tag)
                imported_tags += 1
        return imported_tags

    def _existing_devices_by_import_key(self) -> dict[tuple[str, str], DeviceSpec]:
        return {_device_import_key(device): device for device in self.store.list_devices()}

    def _export_devices_csv_path(self, path: Path) -> int:
        devices = self.store.list_devices()
        rows_written = 0
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_DEVICE_CSV_FIELDS)
            writer.writeheader()
            for device in devices:
                tags = self.store.list_tags(device.id or 0)
                if not tags:
                    writer.writerow(_device_csv_row(device, None))
                    rows_written += 1
                    continue
                for tag in tags:
                    writer.writerow(_device_csv_row(device, tag))
                    rows_written += 1
        return rows_written

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
                tag_group=self.tag_group.text().strip(),
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

    def _import_tags_csv(self) -> None:
        row = self.device_list.currentRow()
        if row < 0 or row >= len(self.devices):
            QMessageBox.warning(self, "CSV import", "Select a device first")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import tags CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            count = self._import_tags_csv_path(Path(path), self.devices[row].id or 0)
            self._load_tags_for_selected_device()
            self._append_log(f"Imported {count} tags")
        except Exception as exc:
            QMessageBox.critical(self, "CSV import", str(exc))

    def _export_tags_csv(self) -> None:
        row = self.device_list.currentRow()
        if row < 0 or row >= len(self.devices):
            QMessageBox.warning(self, "CSV export", "Select a device first")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export tags CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            count = self._export_tags_csv_path(Path(path), self.devices[row].id or 0)
            self._append_log(f"Exported {count} tags")
        except Exception as exc:
            QMessageBox.critical(self, "CSV export", str(exc))

    def _import_tags_csv_path(self, path: Path, device_id: int) -> int:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV header is required")
            count = 0
            for row in reader:
                tag = TagSpec(
                    device_id=device_id,
                    tag_group=(row.get("tag_group") or "").strip(),
                    name=(row.get("name") or "").strip(),
                    node_id=(row.get("node_id") or "").strip() or None,
                    address=int(row.get("address") or 0),
                    function=(row.get("function") or self.tag_function.currentText()).strip(),
                    data_type=(row.get("data_type") or self.tag_type.currentText()).strip(),
                    scale=float(row.get("scale") or 1.0),
                    enabled=_csv_bool(row.get("enabled"), True),
                    word_count=_csv_optional_int(row.get("word_count")),
                    byte_order=(row.get("byte_order") or "big").strip(),
                    word_order=(row.get("word_order") or "big").strip(),
                )
                self.store.save_tag(tag)
                count += 1
        return count

    def _export_tags_csv_path(self, path: Path, device_id: int) -> int:
        tags = self.store.list_tags(device_id)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_TAG_CSV_FIELDS)
            writer.writeheader()
            for tag in tags:
                writer.writerow(
                    {
                        "tag_group": tag.tag_group,
                        "name": tag.name,
                        "node_id": tag.node_id or "",
                        "address": tag.address,
                        "function": tag.function,
                        "data_type": tag.data_type,
                        "scale": tag.scale,
                        "enabled": int(tag.enabled),
                        "word_count": tag.word_count or "",
                        "byte_order": tag.byte_order,
                        "word_order": tag.word_order,
                    }
                )
        return len(tags)

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
        self._clear_runtime_queues()
        self._reset_runtime_tag_status()
        self.server_statuses = {}
        self.runtime_running = True
        self.gathering_status_label.setText("Gathering: Running")
        self.server_status_label.setText("OPC UA Server: Checking")
        health_interval = self.health_check_interval.value()
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
                    status_outbox=self.status_queue,
                    health_interval_s=health_interval,
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
                    status_outbox=self.status_queue,
                    health_interval_s=health_interval,
                )
                poller.start()
                self.pollers.append(poller)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.runtime_status.setText(f"Running: {len(self.pollers) + len(self.subscription_workers)} devices")
        self._append_log("Runtime started")

    def _stop_runtime(self) -> None:
        self._log("INFO", "button", "Stop clicked", {})
        self.runtime_running = False
        for poller in self.pollers:
            poller.stop()
        for worker in self.subscription_workers:
            worker.stop()
        if self.publisher is not None:
            self.publisher.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.runtime_status.setText("Stopped")
        self.gathering_status_label.setText("Gathering: Stopped")
        self.server_status_label.setText("OPC UA Server: Not checked")
        self.pending_runtime_tag_updates = {}
        self._clear_runtime_queues()
        self.runtime_tag_model.mark_disconnected()
        self._append_log("Runtime stopped")

    def _drain_status(self) -> None:
        for _ in range(_MAX_STATUS_QUEUE_DRAIN_PER_TICK):
            try:
                item = self.status_queue.get_nowait()
            except Empty:
                break
            if isinstance(item, dict) and item.get("type") == "tag_update":
                if not self.runtime_running:
                    continue
                key = _runtime_tag_key(
                    str(item.get("device", "")),
                    str(item.get("tag", "")),
                    str(item.get("node_id", "")),
                )
                self.pending_runtime_tag_updates[key] = item
            elif isinstance(item, dict) and item.get("type") == "server_status":
                if not self.runtime_running:
                    continue
                self._update_server_status(item)
            else:
                self._append_log(str(item))
        self._flush_runtime_tag_updates()
        while not self.log_display_queue.empty():
            self._append_log(self.log_display_queue.get())

    def _reset_runtime_tag_status(self) -> None:
        self.pending_runtime_tag_updates = {}
        rows = []
        for device in self.store.list_devices():
            if not device.enabled:
                continue
            mode = _device_runtime_mode(device)
            for tag in self.store.list_tags(device.id or 0):
                if not tag.enabled:
                    continue
                key = _runtime_tag_key(device.name, tag.name, tag.node_id or "")
                rows.append(
                    {
                        "key": key,
                        "device": device.name,
                        "tag": tag.name,
                        "nodeid": tag.node_id or "",
                        "mode": mode,
                        "updated": "",
                        "age": "",
                        "status": "NO DATA",
                        "updated_at": None,
                        "disconnected": False,
                    }
                )
        self.runtime_tag_model.reset_rows(rows)

    def _flush_runtime_tag_updates(self) -> None:
        if not self.runtime_running:
            self.pending_runtime_tag_updates = {}
            return
        if not self.pending_runtime_tag_updates:
            return
        keys = list(self.pending_runtime_tag_updates)[:_MAX_RUNTIME_TABLE_UPDATES_PER_TICK]
        for key in keys:
            item = self.pending_runtime_tag_updates.pop(key)
            self._update_runtime_tag_status(item)

    def _clear_runtime_queues(self) -> None:
        self._drain_queue(self.result_queue)
        self._drain_queue(self.status_queue)

    def _drain_queue(self, queue: Queue[Any]) -> None:
        while True:
            try:
                queue.get_nowait()
            except Empty:
                break

    def _update_runtime_tag_status(self, item: dict[str, Any]) -> None:
        self.runtime_tag_model.apply_update(item)

    def _refresh_runtime_tag_ages(self) -> None:
        stale_after = max(3, self.health_check_interval.value() * 2)
        self.runtime_tag_model.refresh_ages(stale_after)

    def _update_server_status(self, item: dict[str, Any]) -> None:
        device = str(item.get("device", ""))
        self.server_statuses[device] = item
        errors = [name for name, status in self.server_statuses.items() if status.get("status") != "OK"]
        if errors:
            self.server_status_label.setText(f"OPC UA Server: ERROR ({', '.join(errors)})")
        elif self.server_statuses:
            self.server_status_label.setText(f"OPC UA Server: OK ({len(self.server_statuses)} device)")

    def _update_health_interval(self, value: int) -> None:
        for poller in self.pollers:
            poller.health_interval_s = value
        for worker in self.subscription_workers:
            worker.health_interval_s = value

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
        if plugin_type == "mqtt":
            self._wire_mqtt_dynamic_topic_controls()

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

    def _wire_mqtt_dynamic_topic_controls(self) -> None:
        enabled = self.plugin_inputs.get("dynamic_topic_enabled")
        if enabled is None:
            return
        enabled.toggled.connect(self._update_mqtt_dynamic_topic_controls)
        self._update_mqtt_dynamic_topic_controls()

    def _update_mqtt_dynamic_topic_controls(self, *_args: Any) -> None:
        enabled = self.plugin_inputs.get("dynamic_topic_enabled")
        base_topic = self.plugin_inputs.get("base_topic")
        mac_address = self.plugin_inputs.get("mac_address")
        use_dynamic = bool(enabled.isChecked()) if enabled is not None else False
        if base_topic is not None:
            base_topic.setEnabled(not use_dynamic)
        if mac_address is not None:
            mac_address.setEnabled(use_dynamic)

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
        self.age_timer.stop()
        self.logger.stop()


def _csv_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _csv_connection_value(field: ConnectionField, value: Any) -> Any:
    if field.kind == "int":
        return int(value)
    if field.kind == "float":
        return float(value)
    return str(value)


def _device_import_key(device: DeviceSpec) -> tuple[str, str]:
    return (
        device.device_group,
        device.name,
    )


def _validate_same_device_config(existing: DeviceSpec, imported: DeviceSpec) -> None:
    if (
        existing.driver_type != imported.driver_type
        or existing.enabled != imported.enabled
        or existing.poll_interval_ms != imported.poll_interval_ms
        or existing.connection != imported.connection
    ):
        group = imported.device_group or "default"
        raise ValueError(
            f"device '{imported.name}' in group '{group}' already exists with different connection/settings"
        )


def _device_csv_row(device: DeviceSpec, tag: TagSpec | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "device_group": device.device_group,
        "device_name": device.name,
        "driver_type": device.driver_type,
        "enabled": int(device.enabled),
        "poll_interval_ms": device.poll_interval_ms,
    }
    for key in _DEVICE_CSV_FIELDS:
        if key not in row and key in device.connection:
            row[key] = device.connection[key]
    if tag is not None:
        row.update(
            {
                "tag_group": tag.tag_group,
                "tag_name": tag.name,
                "node_id": tag.node_id or "",
                "address": tag.address,
                "function": tag.function,
                "data_type": tag.data_type,
                "scale": tag.scale,
                "tag_enabled": int(tag.enabled),
                "word_count": tag.word_count or "",
                "byte_order": tag.byte_order,
                "word_order": tag.word_order,
            }
        )
    return row


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _runtime_tag_key(device_name: str, tag_name: str, node_id: str) -> tuple[str, str]:
    return (device_name, node_id or tag_name)


def _device_runtime_mode(device: DeviceSpec) -> str:
    if device.driver_type == "opcua" and device.connection.get("mode") == "subscription":
        return "Subscription"
    return "Polling"
