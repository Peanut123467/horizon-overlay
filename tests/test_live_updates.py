from types import SimpleNamespace

from horizon import ipc, win32
from horizon.config import default_config
from horizon.overlay import TIMER_APPLY, HorizonApp


def test_continuous_patches_do_not_postpone_the_next_live_redraw(monkeypatch):
    app = HorizonApp(default_config())
    app.main = SimpleNamespace(hwnd=123)
    scheduled, drawn = [], []
    incoming = {}
    monkeypatch.setattr(ipc, "read_payload", lambda _: incoming)
    monkeypatch.setattr(win32, "set_timer", lambda hwnd, timer, ms: scheduled.append((timer, ms)))
    monkeypatch.setattr(win32, "kill_timer", lambda *args: None)
    monkeypatch.setattr(app, "_on_display_change", lambda: None)
    monkeypatch.setattr(app, "redraw", lambda **kwargs: drawn.append(app.cfg.frame.width))
    monkeypatch.setattr(app, "_sync_hud", lambda: None)
    for width in (11, 15, 19):
        incoming = {"patch": {"frame": {"width": width}}}
        assert app._on_copydata(0) == 1
    assert scheduled == [(TIMER_APPLY, 80)], "new input must not restart the pending redraw timer"
    app._on_timer(TIMER_APPLY)
    assert drawn == [19], "the scheduled draw must use the latest state"
    incoming = {"patch": {"frame": {"width": 24}}}
    app._on_copydata(0)
    assert scheduled == [(TIMER_APPLY, 80), (TIMER_APPLY, 80)]
