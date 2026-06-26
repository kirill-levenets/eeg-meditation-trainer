from app.session.session_program import SessionProgram


def _prog():
    return SessionProgram([
        {"minutes": 10, "target": 50, "formula": "shamatha_score"},
        {"minutes": 10, "target": 70, "formula": "meditation_score"},
        {"minutes": 5,  "target": 90, "formula": {"name": "X", "formula": "alpha1"}},
    ])


def test_total_seconds():
    assert _prog().total_seconds == 25 * 60


def test_segment_at_boundaries():
    p = _prog()
    assert p.segment_at(0)[0] == 0
    assert p.segment_at(599)[0] == 0
    assert p.segment_at(600)[0] == 1          # exactly at the 10-min boundary
    assert p.segment_at(1199)[0] == 1
    assert p.segment_at(1200)[0] == 2


def test_segment_at_past_total_clamps_to_last():
    p = _prog()
    idx, seg = p.segment_at(99999)
    assert idx == 2 and seg["target"] == 90


def test_boundaries():
    assert _prog().boundaries == [600, 1200, 1500]


def test_threshold_steps_tick_space():
    # sample_rate 2 Hz: 10 min = 1200 ticks, 20 min = 2400 ticks
    steps = _prog().threshold_steps(2.0)
    assert steps == [(0, 50.0), (1200, 70.0), (2400, 90.0)]


def test_empty_and_malformed():
    assert not SessionProgram([])
    assert SessionProgram([]).total_seconds == 0
    assert SessionProgram([]).segment_at(0) == (-1, None)
    # malformed entries (non-dict / zero minutes) are dropped
    p = SessionProgram([{"minutes": 0, "target": 1}, "junk", {"minutes": 5, "target": 60}])
    assert len(p.segments) == 1 and p.total_seconds == 300


def test_truthiness():
    assert bool(_prog()) is True
    assert bool(SessionProgram(None)) is False


def test_time_above_threshold_follows_active_goal():
    from app.session.manager import SessionManager, SessionState
    sm = SessionManager()
    sm._state = SessionState.RUNNING
    sm.set_active_goal("custom_formula", 60)
    sm.add_metric({"meditation_score": 10, "shamatha_score": 10, "custom_formula": 80})
    sm.add_metric({"meditation_score": 99, "shamatha_score": 99, "custom_formula": 20})
    # only the first tick is above the *custom_formula* goal of 60
    assert sm.compute_statistics()["time_above_threshold"] == 0  # 0.5s rounds to int 0
    sm.add_metric({"meditation_score": 0, "shamatha_score": 0, "custom_formula": 90})
    assert sm._time_above_threshold == 1.0  # two ticks @ 0.5s above goal
