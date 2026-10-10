"""Text size: one scale for every font in the app, chosen per profile. A change reaches every widget already built, as a
theme switch does."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from kivy.base import EventLoop
from kivy.core.text import Label as CoreLabel
from kivy.core.text.markup import MarkupLabel
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from app.settings.registry import Setting, SettingsStore
from app.storage.database import DatabaseManager
from app.ui.app_manager import startup_text_size, text_size_setting
from app.ui.diary_screen import DiaryScreen
from app.ui.history_screen import HistoryScreen
from app.ui.live_session import LiveSessionScreen
from app.ui.profile_screen import ProfileScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import (
    TEXT_SIZES,
    BottomNav,
    F,
    FoldChevron,
    Icons,
    PresetRow,
    S,
    StyledButton,
    ThemedLabel,
    ThemedPopup,
    ThemedTextInput,
    fit_height_to_text,
    fit_row_to_text,
    text_width,
)
from app.ui.widgets.band_totals import _BAND_ROW_H, _W_NAME, BandTotalsView
from app.ui.wizard_screen import WizardScreen

APP_DIR = Path(__file__).resolve().parents[1] / "app"  # the source tree, from wherever pytest runs
ROLES = {"DISPLAY": 48, "H1": 22, "H2": 16, "H3": 14, "BODY": 13, "SMALL": 11, "TINY": 9}
LARGEST = max(scale for scale, _name in TEXT_SIZES)


@pytest.fixture(autouse=True)
def normal_size():
    yield
    F.set_scale(1.0)


@pytest.fixture
def db(tmp_path):
    database = DatabaseManager(db_path=str(tmp_path / "t.db"))
    yield database
    database.close()


def test_the_sizes_on_offer_are_normal_large_and_larger():
    assert TEXT_SIZES == ((1.0, "Normal"), (1.25, "Large"), (1.5, "Larger"))


def test_every_font_role_follows_the_scale():
    F.set_scale(1.2)
    assert {role: getattr(F, role) for role in ROLES} == pytest.approx({r: dp(s) * 1.2 for r, s in ROLES.items()})
    assert F.px(8) == pytest.approx(dp(8) * 1.2)
    F.set_scale(1.0)
    assert {role: getattr(F, role) for role in ROLES} == pytest.approx({r: dp(s) for r, s in ROLES.items()})


def test_widgets_built_after_the_scale_take_it_even_by_default():
    F.set_scale(1.2)
    assert StyledButton(text="x").font_size == pytest.approx(dp(13) * 1.2)
    assert ThemedLabel(text="x").font_size == pytest.approx(dp(15) * 1.2)  # Kivy's own default size, 15
    assert ThemedTextInput().font_size == pytest.approx(dp(15) * 1.2)


def test_a_graphs_labels_follow_the_scale():
    graph = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0})
    normal = graph._make_text_texture("123", size=8).height
    F.set_scale(1.2)
    assert graph._make_text_texture("123", size=8).height > normal  # not the cached normal-size texture


def test_no_font_size_bypasses_the_scale():
    """A size in dp() or sp(), or Kivy's string units, would stay the same whatever the setting."""
    bypass = re.compile(r"(font_size|title_size)\s*=\s*(dp\(|sp\(|['\"]\d|\d)")
    hits = [f"{p}:{n}" for p in APP_DIR.rglob("*.py")
            for n, line in enumerate(p.read_text().splitlines(), 1) if bypass.search(line)]
    assert hits == []


def test_no_multi_line_label_has_a_fixed_height():
    """A fixed height cuts a larger text off: such a label takes its text's height (fit_height_to_text)."""
    fixed = []
    for path in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ThemedLabel":
                kw = {k.arg: k.value for k in node.keywords}
                text = kw.get("text")
                literal = "".join(c.value for c in ast.walk(text) if isinstance(c, ast.Constant)
                                  and isinstance(c.value, str)) if text is not None else ""
                if "height" in kw and "\n" in literal:
                    fixed.append(f"{path}:{node.lineno}")
    assert fixed == []


def test_a_label_fitted_to_its_text_grows_with_the_text_size():
    heights = []
    for scale in (1.0, 1.2):
        F.set_scale(scale)
        label = ThemedLabel(text="one\ntwo\nthree", size_hint_y=None)
        fit_height_to_text(label)
        label.width = 200
        label.texture_update()
        heights.append(label.height)
    assert heights[1] > heights[0] > 0


def _fits(text: str, font_size: float, width: float, padding: float, bold: bool = False) -> bool:
    label = CoreLabel(text=text, font_size=font_size, bold=bold)
    label.refresh()
    return label.texture.size[0] <= width - 2 * padding


def test_narrow_buttons_keep_their_text_on_one_line_at_the_largest_size():
    """Their sides narrow to make room (a fixed 12 dp left a 40 dp button 16 dp), and their text grows no further than
    their width allows: History's Cal / 14d (40 dp), a duration preset (eight across a 360 dp phone) and a program
    segment's End cue / Feedback columns."""
    F.set_scale(LARGEST)
    history = HistoryScreen()
    history.set_view_mode("bars")  # Cal unselected: drawn regular, and measured so
    preset = PresetRow(items=[("1h30", 90)]).children[0]
    settings = SettingsScreen()
    settings._add_segment_row({"minutes": 10, "target": 60, "formula": "shamatha_score", "end_sound": "warble"})
    row = settings._segments_box.children[0]
    column = 0.16 * (dp(360) - 2 * S.PAGE_PAD - 5 * S.GAP_SM)
    end_cue = next(w for w in row.children if getattr(w, "text", "") == "Warble")
    for btn, width in ((history._btn_calendar, dp(40)), (history._btn_bars, dp(40)), (preset, dp(38)),
                       (end_cue, column), (row._feedback_btn, column)):
        btn.size_hint_x, btn.width = None, width
        assert _fits(btn.text, btn._label.font_size, width, btn.padding[0], btn._label.bold), btn.text


def test_a_button_draws_its_text_bold_as_it_is_set_after_it_is_built():
    btn = StyledButton(text="Cal", bold=True)
    btn.bold = False
    assert btn._label.bold is False
    btn.bold = True
    assert btn._label.bold is True


def test_a_capped_size_grows_with_the_text_size_up_to_its_cap():
    capped = ThemedLabel(text="Cal", font_size=F.capped(F.SMALL))
    free = ThemedLabel(text="Notes", font_size=F.SMALL)
    F.set_scale(1.1)
    assert capped.font_size == pytest.approx(dp(11) * 1.1)
    F.set_scale(LARGEST)
    assert capped.font_size == pytest.approx(dp(11) * F.CAPPED_MAX)
    assert free.font_size == pytest.approx(dp(11) * LARGEST)
    assert F.capped(F.TINY) == pytest.approx(dp(9) * F.CAPPED_MAX)  # read at the size in use, like a role
    F.set_scale(1.0)
    assert capped.font_size == pytest.approx(dp(11))


def test_an_icon_and_text_button_leaves_room_for_both_and_the_gap_between():
    F.set_scale(max(scale for scale, _name in TEXT_SIZES))
    btn = StyledButton(text="Save", icon=Icons.CHECK, spacing=dp(10), font_size=F.SMALL, size_hint_x=None, width=dp(84))
    text = CoreLabel(text="Save", font_size=F.SMALL, bold=True)
    text.refresh()
    room = btn.width - 2 * btn.padding[0] - btn._icon_label.width - btn.spacing
    assert text.texture.size[0] <= room


def test_a_wide_button_keeps_its_12_dp_sides():
    assert StyledButton(text="Save", size_hint_x=None, width=dp(200)).padding[0] == S.BTN_PAD


def test_an_icon_only_button_leaves_room_for_its_glyph():
    F.set_scale(max(scale for scale, _name in TEXT_SIZES))
    chevron = FoldChevron()
    glyph = CoreLabel(text=chevron.icon, font_name="Icons", font_size=chevron._icon_label.font_size)
    glyph.refresh()
    assert glyph.texture.size[0] <= chevron.width - 2 * chevron.padding[0]


@pytest.mark.parametrize("scale", [1.0, LARGEST])
def test_the_timer_pill_holds_every_timer_on_one_line(scale):
    """Every length the slider sets (1 to 120 min), no timer and a program's P: the pill is as wide as its text."""
    F.set_scale(scale)
    screen = LiveSessionScreen()
    pill, label = screen._btn_duration_expand, screen._btn_duration_expand._text_label
    for timer in [(False, 20, False), (True, 20, True), *((True, minutes, False) for minutes in range(1, 121))]:
        screen.refresh_duration_preset(*timer)
        assert text_width(label.text, label.font_size, label.bold, label.font_name) <= pill.width - dp(1), label.text


def test_a_swapped_icon_is_measured_for_the_padding():
    swapped = StyledButton(text="", icon=Icons.CHEVRON_DOWN, size_hint_x=None, width=dp(40))
    swapped.set_icon(Icons.CHEVRON_DOWN * 2)
    built = StyledButton(text="", icon=Icons.CHEVRON_DOWN * 2, size_hint_x=None, width=dp(40))
    assert swapped.padding == built.padding


def test_a_row_keeps_its_label_centred_beside_its_controls_and_grows_when_it_wraps(phone):
    rows = []
    for text in ("Use Mock Data", "Use Mock Data (uncheck for real device) " * 3):
        row = BoxLayout(size_hint_y=None, height=dp(36))
        check = Widget(size_hint=(0.15, None), height=dp(36))
        label = ThemedLabel(text=text, size_hint_x=0.85)
        row.add_widget(check)
        row.add_widget(label)
        fit_row_to_text(row, label, dp(36))
        rows.append((row, check, label))
    stack = BoxLayout(orientation="vertical")
    for row, _check, _label in rows:
        stack.add_widget(row)
    phone.add_widget(stack)
    _frames()
    (short, short_check, short_label), (long_row, long_check, long_label) = rows
    assert short.height == dp(36)
    assert short_label.center_y == pytest.approx(short.center_y, abs=1)  # level with its checkbox
    assert long_row.height == pytest.approx(long_label.height) and long_row.height > dp(36)
    assert long_check.center_y == pytest.approx(long_row.center_y, abs=1)


def test_the_history_heading_takes_the_rows_room_up_to_select(phone):
    """Without a day picked there is no Show All beside it: "All sessions (242 sessions)" fits one line at the largest
    size on a 392 dp phone."""
    F.set_scale(LARGEST)
    phone.width = dp(392)
    history = HistoryScreen()
    phone.add_widget(history)
    history.load_sessions([{"id": i, "date_time": "2026-10-03T07:30:00", "duration": 600, "avg_shamatha": 60,
                            "session_name": f"Mock {i}"} for i in range(242)])
    _frames()
    label, select = history._date_label, history._btn_select
    assert label.text == "All sessions (242 sessions)"
    assert label.right == pytest.approx(select.x - history._date_row.spacing, abs=1)
    one_line = CoreLabel(text="Ag", font_size=label.font_size)
    one_line.refresh()
    assert label.height == pytest.approx(one_line.texture.size[1], abs=2)


def test_applying_the_size_in_use_redoes_nothing():
    calls = []

    class Probe:
        def redraw(self):
            calls.append(F.SCALE)

    probe = Probe()
    F.add_listener(probe.redraw)
    F.set_scale(F.SCALE)  # a profile load applying the size the screens were built at
    assert calls == []
    F.set_scale(1.25)
    assert calls == [1.25]


def test_a_button_can_take_a_narrower_padding():
    assert StyledButton(text="x", padding=[dp(2), 0]).padding == [dp(2), 0, dp(2), 0]
    assert StyledButton(text="x").padding[0] == dp(12)


def test_the_ui_is_built_at_the_startup_profiles_size(db):
    uid = db.create_user("me")
    db.set_setting("last_user_id", str(uid))
    assert startup_text_size(db) == 1.0  # none chosen yet
    db.set_user_setting(uid, "text_size", "1.5")
    assert startup_text_size(db) == 1.5
    db.set_user_setting(uid, "text_size", "3")  # not on offer
    assert startup_text_size(db) == 1.0


def test_the_size_is_saved_per_profile(db):
    me, other = db.create_user("me"), db.create_user("other")
    store = SettingsStore(db, [text_size_setting()])
    F.set_scale(1.25)
    store.save(me)
    store.load(other)
    assert F.SCALE == 1.0  # the other profile's own size, applied as it loads
    store.load(me)
    assert F.SCALE == 1.25
    assert isinstance(store._by_key["text_size"], Setting)


def test_picking_a_size_applies_it_at_once():
    screen = SettingsScreen()
    label = ThemedLabel(text="built before", font_size=F.SMALL)
    picked = []
    screen.set_text_size_callback(picked.append)
    screen._text_size_presets.children[0].dispatch("on_release")  # Larger (children run right to left)
    assert picked == [LARGEST] and F.SCALE == LARGEST
    assert label.font_size == pytest.approx(dp(11) * LARGEST)


def test_the_picker_shows_the_size_in_use_whoever_set_it():
    screen = SettingsScreen()
    F.set_scale(1.25)  # a profile's settings load
    selected = {btn._preset_value: btn.bold for btn in screen._text_size_presets.children}
    assert selected == {1.0: False, 1.25: True, 1.5: False}


# ---- a change reaches what is already built ----


def test_a_change_reaches_every_text_already_built_even_detached():
    label = ThemedLabel(text="a", font_size=F.SMALL)
    field = ThemedTextInput(font_size=F.BODY)
    default = ThemedLabel(text="Kivy's size")
    button = StyledButton(text="Save", icon=Icons.CHECK)
    popup = ThemedPopup(title="t")
    F.set_scale(1.2)
    assert label.font_size == pytest.approx(dp(11) * 1.2)
    assert field.font_size == pytest.approx(dp(13) * 1.2)
    assert default.font_size == pytest.approx(dp(15) * 1.2)
    assert button._label.font_size == pytest.approx(dp(13) * 1.2)
    assert button._icon_label.font_size == pytest.approx(dp(13) * 1.2 + dp(4))
    assert popup.title_size == pytest.approx(dp(14) * 1.2)


def test_a_size_not_from_the_roles_stays_fixed():
    glyph = ThemedLabel(text="x", font_size=F.glyph(20))
    reset = ThemedLabel(text="y", font_size=F.SMALL)
    reset.font_size = dp(12)  # a plain size given later drops the scaled one
    F.set_scale(1.2)
    assert glyph.font_size == dp(20) and reset.font_size == dp(12)


def test_a_size_read_before_a_change_is_used_at_the_size_in_use():
    small = F.SMALL
    F.set_scale(1.2)
    assert ThemedLabel(text="x", font_size=small).font_size == pytest.approx(dp(11) * 1.2)


def test_a_change_redraws_the_graphs():
    redraws = []

    class Graph(ScrollableGraphWidget):
        def _redraw(self, *args):
            redraws.append(1)
            super()._redraw(*args)

    _graph = Graph(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0})  # held: a listener doesn't keep it alive
    redraws.clear()
    F.set_scale(1.2)
    assert redraws


def test_the_band_table_takes_the_new_size():
    view = BandTotalsView()
    F.set_scale(1.2)
    name_column = next(iter(view._range_labels.values())).parent
    assert name_column.width == pytest.approx(dp(_W_NAME) * 1.2)
    assert name_column.parent.height == pytest.approx(dp(_BAND_ROW_H) * 1.2)


# ---- every screen ----



def _frames(n: int = 6) -> None:
    for _ in range(n):
        EventLoop.idle()


def _session_states(screen):
    yield "", None
    yield " a 105 min timer", lambda: screen.refresh_duration_preset(True, 105)
    yield " saved card", lambda: screen.show_summary(
        1, {"duration": 1500, "threshold_used": 60, "avg_shamatha": 72, "time_above_threshold": 610,
            "longest_streak": 270}, title="2026-10-10 07:30 - Mock with a name too long for one line")


def _history_states(screen):
    yield "", lambda: screen.load_sessions(
        [{"id": i, "date_time": f"2026-10-0{i}T07:30:00", "duration": 1200, "avg_shamatha": 60 + 10 * i,
          "session_name": f"2026-10-0{i} 07:30 - Mock", "notes": "Calm start, drowsy after ten minutes."}
         for i in (1, 2, 3)])
    yield " a day picked", lambda: screen._on_day_tap("2026-10-03")
    yield " 14 days", lambda: screen.set_view_mode("bars")


def _settings_states(screen):
    yield "", None
    for k, section in enumerate(screen._accordion._sections):
        yield f" section {k}", section.open
    yield " program", lambda: (screen.set_program_mode("program"), screen.load_program(PROGRAM, "program"),
                               screen._accordion._sections[1].open())


PROGRAM = [{"minutes": 10, "formula": "shamatha_score", "target": 60, "end_sound": "warble"},
           {"minutes": 15, "formula": {"name": "Alpha calm", "formula": "alpha1 / (beta1 + 1)"}, "target": 70}]


def _detail_states(screen):
    yield "", lambda: screen.set_band_totals(
        {"delta": 4e6, "theta": 2e6, "alpha1": 8e5, "alpha2": 6e5, "beta1": 4e5, "beta2": 3e5, "gamma1": 1e5,
         "gamma2": 6e4})


def _profile_states(screen):
    yield "", lambda: screen.populate_users([{"id": 1, "name": "Mock"}, {"id": 2, "name": "Second mock"}], 1)


def _only_state(_widget):
    yield "", None


def _wizard_states(screen):
    yield " step 1", None

    def step_2():  # an existing profile picked in the wizard: its text size applies as step 2 shows
        screen._user_name = "Mock"
        screen._advance_to_step2()

    yield " step 2", step_2


# (where, build, states): each screen, and the states it is checked in, one after another on the same build.
VIEWS = [
    ("session", LiveSessionScreen, _session_states),
    ("history", HistoryScreen, _history_states),
    ("settings", SettingsScreen, _settings_states),
    ("session detail", DiaryScreen, _detail_states),
    ("profiles", ProfileScreen, _profile_states),
    ("wizard", WizardScreen, _wizard_states),
    ("bottom nav", lambda: BottomNav(tabs=[("Session", "session"), ("History", "history"), ("Settings", "settings")],
                                     callback=lambda *_a: None), _only_state),
]


@pytest.fixture
def phone():
    """A 360 dp wide phone screen to show the views on."""
    EventLoop.ensure_window()
    holder = FloatLayout(size_hint=(None, None), size=(dp(360), dp(740)))
    Window.add_widget(holder)
    yield holder
    Window.remove_widget(holder)


def _check_views(holder, check, switch: str = "", to: float = 1.0) -> list:
    """check(widget, where) on every state of every view. switch="before": each view switches to the size `to` once
    shown, before its states; "after": each state is reached at the size in use, then switched to `to` and back."""
    found = []
    for where, build, states in VIEWS:
        start = F.SCALE
        widget = build()
        holder.clear_widgets()
        holder.add_widget(widget)
        _frames()
        if switch == "before":
            F.set_scale(to)
            _frames()
        for name, action in states(widget):
            if action:
                action()
                _frames()
            if switch == "after":
                F.set_scale(to)
                _frames()
            found.append(check(widget, where + name))
            if switch == "after":
                F.set_scale(start)
                _frames()
        F.set_scale(start)
    return found


def _text_size_needed(label: Label) -> tuple[float, float]:
    """The size `label`'s text takes, wrapped at its width when it wraps. Its texture won't say: when its text area is
    pinned to its box, the texture is the box, and text too large for it is cut. Pinned, it wraps 1 dp inside: a text
    that fits with nothing to spare wraps on another screen density (a fitted label just takes the extra line)."""
    width, height = label.text_size
    wrap_at = (width - dp(1) if height else width) if width else None
    core = (MarkupLabel if label.markup else CoreLabel)(
        text=label.text, font_size=label.font_size, font_name=label.font_name, bold=label.bold, italic=label.italic,
        padding=label.padding, line_height=label.line_height, shorten=label.shorten, max_lines=label.max_lines,
        text_size=(wrap_at, None))
    core.refresh()
    return core.texture.size


def _outgrown(root, where: str) -> set[tuple[str, str]]:
    """(where, text) of each label whose text its box cuts, or whose box reaches past its parent's (a chart's axis
    label past the chart's edge is cut off). A line's height has room above and below its letters: a box up to 0.3 em
    shorter cuts only that. Sizes are whole pixels: 1.5 px either way is rounding."""
    out = set()
    for w in root.walk():
        if isinstance(w, Label) and w.text.strip() and w.width > 1 and w.height > 1:
            needed_w, needed_h = _text_size_needed(w)
            if needed_h > w.height + 0.3 * w.font_size + 1.5 or needed_w > w.width + 1.5:
                out.add((where, w.text))
            parent = w.parent
            if parent is not None and parent is not root and not isinstance(parent, ScrollView) and (
                    w.top > parent.top + 1.5 or w.y < parent.y - 1.5):
                out.add((where, w.text))
        elif isinstance(w, TextInput) and (w.text or w.hint_text) and w.width > 1 and w.height > 1:
            text = w.text or w.hint_text  # a field shows its hint until it has text
            inner_w, inner_h = w.width - w.padding[0] - w.padding[2], w.height - w.padding[1] - w.padding[3]
            core = CoreLabel(text=text, font_size=w.font_size, font_name=w.font_name,
                             text_size=(inner_w if w.multiline else None, None))
            core.refresh()
            needed_w, needed_h = core.texture.size  # from the top down: what doesn't fit cuts the last line's letters
            if needed_h > inner_h + 1.5 or (not w.multiline and needed_w > inner_w + 1.5):
                out.add((where, text))
    return out


def test_no_text_outgrows_a_box_at_the_largest_size_that_it_fits_at_normal(phone):
    """On a 360 dp phone. A box some text already outgrows at the normal size (the Session screen's 10 dp header row)
    is a choice of that screen's, not something the text size broke."""
    found = {}
    for scale in (1.0, LARGEST):
        F.set_scale(scale)
        found[scale] = set().union(*_check_views(phone, _outgrown))
    assert found[LARGEST] - found[1.0] == set()


def _layout(root, where: str) -> list[tuple]:
    """Each widget's kind, text, font and size, in tree order."""
    return [(where, type(w).__name__, str(getattr(w, "text", "")), round(float(getattr(w, "font_size", 0)), 2),
             round(w.width, 1), round(w.height, 1)) for w in root.walk()]


@pytest.mark.parametrize("switch", ["before", "after"])
def test_a_screen_switched_to_a_size_is_laid_out_as_one_built_at_it(phone, switch):
    """Whether the size changes before a section is opened (its content detached) or while it is shown."""
    F.set_scale(LARGEST)
    built_at = _check_views(phone, _layout)
    F.set_scale(1.0)
    switched = _check_views(phone, _layout, switch=switch, to=LARGEST)
    assert switched == built_at


PHONE_DENSITY = "2.75"  # px per dp on the test phone


@pytest.mark.skipif(os.environ.get("KIVY_METRICS_DENSITY") == PHONE_DENSITY, reason="the phone-density run itself")
def test_the_largest_size_also_fits_at_a_phones_pixel_density():
    """Text is drawn in whole pixels: a text that just fits at 1 px per dp can wrap at 2.75 (History's Cal, the 14-day
    chart's 100). The density is fixed when Kivy starts, so the checks run again in a process of their own."""
    checks = [f"{__file__}::{name}" for name in ("test_no_text_outgrows_a_box_at_the_largest_size_that_it_fits_at_normal",
                                                 "test_narrow_buttons_keep_their_text_on_one_line_at_the_largest_size",
                                                 "test_the_timer_pill_holds_every_timer_on_one_line")]
    # On this run's display (no second Xvfb to start); only the density differs.
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xvfb", *checks],
                         env={**os.environ, "KIVY_METRICS_DENSITY": PHONE_DENSITY}, capture_output=True, text=True,
                         timeout=600)
    assert run.returncode == 0, run.stdout[-4000:]
