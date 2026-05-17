import pytest

from industrial_gateway.registry import Registry


class FakePlugin:
    pass


def test_registry_returns_registered_plugin_by_key():
    registry = Registry()

    registry.register("fake", FakePlugin)

    assert registry.get("fake") is FakePlugin
    assert registry.keys() == ["fake"]


def test_registry_rejects_unknown_key():
    registry = Registry()

    with pytest.raises(KeyError, match="missing"):
        registry.get("missing")
