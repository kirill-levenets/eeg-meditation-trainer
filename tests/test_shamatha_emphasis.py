from app.ui.app_manager import EEGMeditationApp


def test_shamatha_transition_enters_after_sustained_above():
    fn = EEGMeditationApp._shamatha_transition
    # Three consecutive above-threshold ticks (1.5s @ 2Hz) flip the zone on.
    a, s = fn(False, True, 0)
    assert (a, s) == (False, 1)
    a, s = fn(a, True, s)
    assert (a, s) == (False, 2)
    a, s = fn(a, True, s)
    assert (a, s) == (True, 0)


def test_shamatha_transition_below_tick_resets_enter_streak():
    fn = EEGMeditationApp._shamatha_transition
    # A single below tick zeroes a partial enter streak (no premature flip).
    assert fn(False, False, 2) == (False, 0)


def test_shamatha_transition_exits_after_sustained_below():
    fn = EEGMeditationApp._shamatha_transition
    a, s = fn(True, False, 0)
    assert (a, s) == (True, 1)
    a, s = fn(a, False, s)
    assert (a, s) == (True, 2)
    a, s = fn(a, False, s)
    assert (a, s) == (False, 0)


def test_shamatha_transition_above_tick_resets_exit_streak():
    fn = EEGMeditationApp._shamatha_transition
    # While active, a single above tick cancels a partial exit streak.
    assert fn(True, True, 2) == (True, 0)


def test_set_shamatha_overrides_status_text_and_chip():
    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    screen.update_state("Stable Focus")
    assert screen._state_label.text == "Stable Focus"
    assert screen._shamatha_active is False
    assert screen._shamatha_bg.a == 0

    screen.set_shamatha(True)
    assert screen._state_label.text == "SHAMATHA"
    assert screen._shamatha_active is True
    assert screen._shamatha_bg.a > 0

    # While active, classified-state ticks must NOT overwrite the chip.
    screen.update_state("Sinking")
    assert screen._state_label.text == "SHAMATHA"

    screen.set_shamatha(False)
    assert screen._state_label.text == "Sinking"
    assert screen._shamatha_active is False
    assert screen._shamatha_bg.a == 0
