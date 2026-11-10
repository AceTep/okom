from app.config import DecisionConfig
from app.decision import ScreenDecider
from shared.protocol import GazeMessage

CFG = DecisionConfig(dwell_s=0.4, cooldown_s=0.8, min_conf=0.6, max_gap_s=0.5)
DT = 1 / 30


def msg(t: float, screen: int | None, **kw) -> GazeMessage:
    base = dict(t=t, face=True, users=1, screen=screen, x=0.5, y=0.5, conf=0.9, blink=False)
    base.update(kw)
    return GazeMessage(**base)


def run(decider: ScreenDecider, start: float, end: float, screen: int | None, **kw) -> list:
    """Feed samples at 30 Hz in [start, end) and return (t, switch) for every switch."""
    out = []
    n = round((end - start) / DT)
    for i in range(n):
        t = start + i * DT
        result = decider.update(msg(t, screen, **kw))
        if result is not None:
            out.append((t, result))
    return out


def test_switch_after_dwell() -> None:
    d = ScreenDecider(CFG, current=0)
    switches = run(d, 0.0, 1.0, 1)
    assert len(switches) == 1
    t, screen = switches[0]
    assert screen == 1
    assert 0.4 <= t < 0.4 + DT + 1e-9
    assert d.current == 1


def test_short_glance_does_not_switch() -> None:
    d = ScreenDecider(CFG, current=0)
    assert run(d, 0.0, 0.3, 1) == []
    assert run(d, 0.3, 0.6, 0) == []
    assert run(d, 0.6, 0.9, 1) == []  # dwell restarted, 0.3 s is not enough
    assert d.current == 0


def test_looking_at_current_screen_never_switches() -> None:
    d = ScreenDecider(CFG, current=0)
    assert run(d, 0.0, 3.0, 0) == []


def test_blink_does_not_reset_dwell() -> None:
    d = ScreenDecider(CFG, current=0)
    assert run(d, 0.0, 0.2, 1) == []
    assert run(d, 0.2, 0.35, 1, blink=True) == []
    switches = run(d, 0.35, 0.6, 1)
    assert switches and switches[0][1] == 1
    assert switches[0][0] < 0.45  # dwell counted from 0.0, not from after the blink


def test_unusable_samples_are_ignored() -> None:
    d = ScreenDecider(CFG, current=0)
    assert run(d, 0.0, 2.0, 1, face=False) == []
    assert run(d, 2.0, 4.0, None) == []
    assert run(d, 4.0, 6.0, 1, conf=0.3) == []
    assert d.current == 0


def test_long_gap_restarts_dwell() -> None:
    d = ScreenDecider(CFG, current=0)
    assert run(d, 0.0, 0.3, 1) == []
    # face lost for 2 s, then back on screen 1: dwell starts again from 2.3
    switches = run(d, 2.3, 3.0, 1)
    assert switches and switches[0][0] >= 2.7 - 1e-9


def test_cooldown_delays_switch_back() -> None:
    d = ScreenDecider(CFG, current=0)
    ((t1, _),) = run(d, 0.0, 0.5, 1)
    switches = run(d, 0.5, 2.0, 0)
    assert switches and switches[0][1] == 0
    assert switches[0][0] - t1 >= CFG.cooldown_s - 1e-9


def test_unknown_start_switches_to_first_settled_screen() -> None:
    d = ScreenDecider(CFG, current=None)
    switches = run(d, 0.0, 1.0, 0)
    assert [s for _, s in switches] == [0]


def test_switches_once_per_change() -> None:
    d = ScreenDecider(CFG, current=0)
    assert len(run(d, 0.0, 5.0, 1)) == 1


def test_manual_focus_change_updates_current() -> None:
    d = ScreenDecider(CFG, current=0)
    assert run(d, 0.0, 0.3, 1) == []  # dwelling towards screen 1...
    assert d.set_current(1) is True  # ...when the user clicks a window there
    assert d.current == 1
    assert run(d, 0.3, 2.0, 1) == []  # already there: no switch
    assert d.set_current(1) is False  # no change, nothing to report
    switches = run(d, 2.0, 3.0, 0)  # looking back at screen 0 still works
    assert [s for _, s in switches] == [0]
