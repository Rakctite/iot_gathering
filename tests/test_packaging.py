from pathlib import Path
import tomllib


def test_runtime_dependencies_include_pyserial_for_modbus_serial():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("pyserial") for dependency in dependencies)


def test_runtime_dependencies_include_asyncua_for_opcua():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("asyncua") for dependency in dependencies)


def test_runtime_dependencies_include_database_clients():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("psycopg") for dependency in dependencies)
    assert any(dependency.startswith("pyodbc") for dependency in dependencies)
