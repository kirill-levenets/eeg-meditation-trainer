"""A run's phase: ENDED is terminal, and only the call that marked it ended claims the ending."""
from unittest.mock import MagicMock

import pytest

import app.session.session_run as session_run
from app.session.session_run import Phase, SessionRun
from tests._noted_lock import NotedLock


def test_only_the_first_mark_claims_the_ending_and_ended_sticks(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(session_run, "logger", log)
    run = SessionRun(1)
    run.phase = Phase.CONNECTING
    run.phase = Phase.STARTED  # the phases before the ending stay writable
    assert run.phase is Phase.STARTED
    assert run.mark_ended() and not run.mark_ended()
    run.phase = Phase.STARTED  # a tick that passed its check before the ending began
    assert run.phase is Phase.ENDED and "not set" in log.debug.call_args.args[0]


def test_the_claim_and_the_setter_take_the_lock_and_log_outside_it(monkeypatch):
    run, lock, held_at_log = SessionRun(1), NotedLock(), []
    run._phase_lock = lock
    monkeypatch.setattr(session_run, "logger", MagicMock(debug=lambda _msg: held_at_log.append(lock.held)))
    run.phase = Phase.STARTED
    assert run.mark_ended() and lock.takes == 2
    run.phase = Phase.STARTED  # refused, logged
    assert lock.takes == 3 and held_at_log == [False]


def test_a_run_ends_only_through_its_claim():
    run = SessionRun(1)
    with pytest.raises(ValueError):
        run.phase = Phase.ENDED
    assert run.phase is Phase.STARTING and run.mark_ended()
