import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows display metrics", allow_module_level=True)

from horizon import metrics, win32


def test_refresh_rate_uses_the_overlay_monitor_device(monkeypatch):
    opened = []
    deleted = []
    monkeypatch.setattr(win32.user32, "MonitorFromWindow", lambda h, flag: 77, raising=False)

    def monitor_info(handle, pointer):
        info = pointer._obj
        assert handle == 77
        info.szDevice = r"\\.\DISPLAY2"
        return True

    def create_dc(driver, device, output, data):
        opened.append((driver, device))
        return 88

    monkeypatch.setattr(win32.user32, "GetMonitorInfoW", monitor_info)
    monkeypatch.setattr(win32.gdi32, "CreateDCW", create_dc, raising=False)
    monkeypatch.setattr(win32.gdi32, "GetDeviceCaps", lambda h, index: 240 if h == 88 else 60)
    monkeypatch.setattr(win32.gdi32, "DeleteDC", deleted.append)
    assert metrics.refresh_rate_hz(hwnd=42) == 240
    assert opened == [("DISPLAY", r"\\.\DISPLAY2")]
    assert deleted == [88]


def test_monitor_lookup_failure_does_not_report_primary_rate(monkeypatch):
    monkeypatch.setattr(win32.user32, "MonitorFromWindow", lambda *args: 0, raising=False)
    assert metrics.refresh_rate_hz(hwnd=42) == 0


def test_default_refresh_rate_hides_unknown_hardware_value(monkeypatch):
    released = []
    monkeypatch.setattr(win32.user32, "GetDC", lambda hwnd: 99)
    monkeypatch.setattr(win32.gdi32, "GetDeviceCaps", lambda *args: 1)
    monkeypatch.setattr(win32.user32, "ReleaseDC", lambda *args: released.append(args))
    assert metrics.refresh_rate_hz() == 0
    assert released == [(None, 99)]
