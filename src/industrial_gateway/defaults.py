from __future__ import annotations

from industrial_gateway.drivers import ModbusSerialDriver, ModbusTcpDriver, MqttInputDriver, OpcUaDriver
from industrial_gateway.config_schema import enabled_plugin_types
from industrial_gateway.registry import Registry
from industrial_gateway.sinks import MqttSink, PostgresSink

driver_registry = Registry()
driver_registry.register("modbus_tcp", ModbusTcpDriver)
driver_registry.register("modbus_serial", ModbusSerialDriver)
driver_registry.register("opcua", OpcUaDriver)
driver_registry.register("mqtt", MqttInputDriver)

sink_registry = Registry()
sink_registry.register("mqtt", MqttSink)
if "postgresql" in enabled_plugin_types():
    sink_registry.register("postgresql", PostgresSink)
