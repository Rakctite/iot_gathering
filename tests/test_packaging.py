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


def test_runtime_dependencies_do_not_include_database_clients_by_default():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert not any(dependency.startswith("psycopg") for dependency in dependencies)
    assert not any(dependency.startswith("pyodbc") for dependency in dependencies)


def test_postgres_extra_includes_postgres_client_without_mssql():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert any(dependency.startswith("psycopg") for dependency in optional_dependencies["postgres"])
    assert all(not dependency.startswith("pyodbc") for dependency in optional_dependencies["postgres"])
