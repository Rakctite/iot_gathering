from pathlib import Path


def test_mssql_sink_code_is_removed():
    database_source = Path("src/industrial_gateway/sinks/database.py").read_text()

    assert "MssqlSink" not in database_source
    assert "pyodbc" not in database_source
    assert "mssql" not in database_source.lower()
