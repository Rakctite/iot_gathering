import os
import csv

import pytest

from industrial_gateway.gui.main_window import MainWindow
from industrial_gateway.models import DeviceSpec, TagSpec


def test_main_window_exports_and_imports_tag_and_device_csv(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    store_path = tmp_path / "gateway.sqlite3"
    window = MainWindow(store_path)
    try:
        device_id = window.store.save_device(
            DeviceSpec(
                id=None,
                name="opc",
                driver_type="opcua",
                enabled=True,
                poll_interval_ms=1000,
                connection={"endpoint": "opc.tcp://localhost:4840"},
            )
        )
        window.store.save_tag(
            TagSpec(
                device_id=device_id,
                tag_group="PHH08",
                name="PV_CUR_MOLD_N11",
                address=0,
                function="opcua_node",
                data_type="auto",
                node_id="ns=2;s=PHH08.MC01.PV_CUR_MOLD_N11",
            )
        )
        csv_path = tmp_path / "tags.csv"

        assert window._export_tags_csv_path(csv_path, device_id) == 1
        device_csv_path = tmp_path / "devices.csv"
        assert window._export_devices_csv_path(device_csv_path) == 1
        with device_csv_path.open("r", encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        assert row["device_name"] == "opc"
        assert row["endpoint"] == "opc.tcp://localhost:4840"
        assert row["tag_name"] == "PV_CUR_MOLD_N11"
        assert row["node_id"] == "ns=2;s=PHH08.MC01.PV_CUR_MOLD_N11"

        imported_store_path = tmp_path / "imported.sqlite3"
        imported = MainWindow(imported_store_path)
        try:
            assert imported._import_devices_csv_path(device_csv_path) == 1
            imported_device = imported.store.list_devices()[0]
            imported_device_id = imported_device.id or 0
            assert imported_device.name == "opc"
            assert imported_device.connection["endpoint"] == "opc.tcp://localhost:4840"
            tag = imported.store.list_tags(imported_device_id)[0]
            assert tag.tag_group == "PHH08"
            assert tag.name == "PV_CUR_MOLD_N11"
            assert tag.node_id == "ns=2;s=PHH08.MC01.PV_CUR_MOLD_N11"

            tag_only_store_path = tmp_path / "tag_only.sqlite3"
            tag_only = MainWindow(tag_only_store_path)
            try:
                tag_only_device_id = tag_only.store.save_device(
                    DeviceSpec(
                        id=None,
                        name="opc",
                        driver_type="opcua",
                        enabled=True,
                        poll_interval_ms=1000,
                        connection={"endpoint": "opc.tcp://localhost:4840"},
                    )
                )
                assert tag_only._import_tags_csv_path(csv_path, tag_only_device_id) == 1
            finally:
                tag_only.shutdown()
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                tag_row = next(csv.DictReader(handle))
            assert tag_row["name"] == "PV_CUR_MOLD_N11"
            assert tag_row["node_id"] == "ns=2;s=PHH08.MC01.PV_CUR_MOLD_N11"
            assert tag_row["data_type"] == "auto"
            assert tag_row["scale"] == "1.0"
            assert "word_count" in tag_row
        finally:
            imported.shutdown()
    finally:
        window.shutdown()
        app.processEvents()


def test_device_tag_csv_import_reuses_same_device_and_blocks_conflicting_settings(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    store_path = tmp_path / "gateway.sqlite3"
    window = MainWindow(store_path)
    csv_path = tmp_path / "devices_tags.csv"
    csv_path.write_text(
        "\n".join(
            [
                "device_group,device_name,driver_type,enabled,poll_interval_ms,endpoint,mode,subscription_interval_ms,tag_group,tag_name,node_id,address,function,data_type,scale,tag_enabled,word_count,byte_order,word_order",
                "LINE,CKP_OPCUA,opcua,1,1000,opc.tcp://localhost:4840,subscription,250,PHH01,TAG_A,ns=2;s=PHH01.MC01.TAG_A,0,opcua_node,auto,1.0,1,,big,big",
                "LINE,CKP_OPCUA,opcua,1,1000,opc.tcp://localhost:4840,subscription,250,PHH02,TAG_A,ns=2;s=PHH02.MC01.TAG_A,0,opcua_node,auto,1.0,1,,big,big",
            ]
        ),
        encoding="utf-8",
    )
    try:
        assert window._import_devices_csv_path(csv_path) == 2
        devices = window.store.list_devices()
        assert len(devices) == 1
        assert len(window.store.list_tags(devices[0].id or 0)) == 2

        conflict_path = tmp_path / "conflict.csv"
        conflict_path.write_text(
            "\n".join(
                [
                    "device_group,device_name,driver_type,enabled,poll_interval_ms,endpoint,mode,subscription_interval_ms,tag_group,tag_name,node_id,address,function,data_type,scale,tag_enabled,word_count,byte_order,word_order",
                    "LINE,CKP_OPCUA,opcua,1,1000,opc.tcp://other:4840,subscription,250,PHH03,TAG_B,ns=2;s=PHH03.MC01.TAG_B,0,opcua_node,auto,1.0,1,,big,big",
                ]
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="different connection"):
            window._import_devices_csv_path(conflict_path)
    finally:
        window.shutdown()
        app.processEvents()
