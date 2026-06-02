from __future__ import annotations

from industrial_gateway.drivers import ModbusSerialDriver, ModbusTcpDriver, MqttInputDriver, OpcUaDriver
from industrial_gateway.registry import Registry
from industrial_gateway.sinks import MqttSink, MssqlSink, PostgresSink

driver_registry = Registry()
driver_registry.register("modbus_tcp", ModbusTcpDriver)
driver_registry.register("modbus_serial", ModbusSerialDriver)
driver_registry.register("opcua", OpcUaDriver)
driver_registry.register("mqtt", MqttInputDriver)

sink_registry = Registry()
sink_registry.register("mqtt", MqttSink)
sink_registry.register("postgresql", PostgresSink)
sink_registry.register("mssql", MssqlSink)
