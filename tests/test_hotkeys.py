import pytest

from horizon.hotkeys import DEFAULT_HOTKEYS, parse_binding, validate_bindings


def test_binding_parses_modifiers_and_function_key():
    assert parse_binding("Ctrl+Alt+F9") == (3, 0x78)


@pytest.mark.parametrize("key", ["H", "Ctrl+Alt", "Ctrl+Banana", "Alt+F4"])
def test_unsafe_or_unknown_binding_rejected(key):
    with pytest.raises(ValueError):
        parse_binding(key)


def test_duplicate_bindings_rejected():
    with pytest.raises(ValueError, match="重复"):
        validate_bindings({**DEFAULT_HOTKEYS, "toggle": DEFAULT_HOTKEYS["quit"]})
