"""History's session list: one row per shown session (row widgets only for those on screen), select mode, the inline
rename, and one touch router for the rows."""
import weakref

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from app.ui.history_sections.common import score_colour
from app.ui.hooks import Hook
from app.ui.session_labels import session_label, session_notes_line, session_stats_line, session_title
from app.ui.theme import ICONS_AVAILABLE, C, Card, F, Icons, S, ThemedLabel, text_fills_box
from app.ui.widgets.rows import RenameRow
from app.ui.widgets.styled_button import StyledButton


class _StableScrollView(ScrollView):
    """A ScrollView whose content height changes while it may be scrolled: a change keeps the pixel offset from the top."""

    def _update_effect_y_bounds(self, *args):
        # Kivy 2.3 rescales the fraction (max * scroll_y): past an edge the overscroll grew with every height change
        # until the list ran out of view (#56). Keep the offset from the top, where the list starts.
        effect = self.effect_y
        if not self._viewport or not effect:
            return
        new_max = self.height - self.viewport_size[1]
        if new_max == effect.max:  # the touch start/stop resync: keep Kivy's own overscroll bounce
            super()._update_effect_y_bounds(*args)
            return
        from_top = effect.max * (self.scroll_y - 1)
        effect.min = 0 if new_max < 0 else new_max
        effect.max = new_max
        effect.value = new_max + from_top


_ROW_H = dp(56)
_ROW_H_NOTES = dp(76)  # a row with a notes line
_RENAME_H = dp(40)  # the inline editor under a row being renamed


def _checkbox_glyph(selected: bool) -> str:
    if ICONS_AVAILABLE:
        return Icons.CHECKBOX_MARKED if selected else Icons.CHECKBOX_BLANK
    return "[x]" if selected else "[ ]"


class _SessionRow(RecycleDataViewBehavior, BoxLayout):
    """One History row, reused for whichever session scrolls into it: every refresh sets everything it shows."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.sid = None
        self._card = Card(orientation="horizontal", size_hint_y=None, height=_ROW_H, bg_color=C.BG_CARD,
                          spacing=S.GAP_SM, padding=0)
        self._checkbox = ThemedLabel(font_name="Icons" if ICONS_AVAILABLE else "Roboto", font_size=F.H2,
                                     size_hint_x=None, width=dp(36), halign="center", valign="middle")
        score_bar = Widget(size_hint_x=None, width=dp(4))
        with score_bar.canvas:
            self._score_color = Color(1, 1, 1, 1)
            rect = RoundedRectangle(pos=score_bar.pos, size=score_bar.size, radius=[dp(2)])
        score_bar.bind(pos=lambda w, v: setattr(rect, "pos", v), size=lambda w, v: setattr(rect, "size", v))
        self._info = info = BoxLayout(orientation="vertical", padding=[dp(6), 0])
        # One line each, cut with an ellipsis: a long name or note never wraps out of its row.
        self._name_label = ThemedLabel(font_size=F.BODY, color=C.TEXT, halign="left", valign="middle",
                                       size_hint_y=0.55, shorten=True, shorten_from="right")
        self._stats_label = ThemedLabel(font_size=F.TINY, color=C.TEXT_MUTED, halign="left", valign="middle",
                                        size_hint_y=0.45, shorten=True, shorten_from="right")
        self._notes_label = ThemedLabel(font_size=F.TINY, color=C.TEXT_MUTED, halign="left", valign="middle",
                                        size_hint_y=0.45, shorten=True, shorten_from="right")
        for label in (self._name_label, self._stats_label, self._notes_label):
            text_fills_box(label)
        info.add_widget(self._name_label)
        info.add_widget(self._stats_label)
        # Rename + delete are drawn only: the list's router hit-tests the strip (see SessionList._list_touch_down).
        self._actions = BoxLayout(orientation="horizontal", size_hint_x=None, width=dp(80), spacing=dp(2))
        for icon, color in ((Icons.PENCIL, C.PRIMARY), (Icons.DELETE, C.DANGER)):
            self._actions.add_widget(StyledButton(text="", icon=icon, bg_color=color, text_color=color,
                                                  font_size=F.SMALL, size_hint_y=1, bold=False, outline=True))
        for w in (score_bar, info, self._actions):
            self._card.add_widget(w)
        self.add_widget(self._card)

    def on_parent(self, _row, parent):
        ref = getattr(self, "_owner", None)
        owner = ref() if ref is not None else None
        if owner is None:
            return
        if parent is not None:
            # Back at the position it last showed, Kivy reuses a row without refresh_view_attrs: it may have
            # missed a select-mode, selection or rename change while it was off screen.
            self.sync(owner)
        elif owner._rename_row.parent is self:
            # Scrolled off, a row keeps its widgets until it is reused: it mustn't keep the editor. A relayout also
            # removes and re-adds every row, so the focus (the keyboard) is dropped only if no row takes it back.
            self.remove_widget(owner._rename_row)
            owner._rename_focus_check()

    def refresh_view_attrs(self, rv, index, data):
        # Size and position come from the layout; nothing else in the data is a view property.
        self._owner = weakref.ref(rv.owner)  # weak: Kivy keeps unused rows in a global cache, which mustn't keep the list
        self.sid = data["sid"]
        self._name_label.text = data["name"]
        self._stats_label.text = data["stats"]
        self._notes_label.text = data["notes"]
        if bool(data["notes"]) != (self._notes_label.parent is not None):
            if data["notes"]:
                self._info.add_widget(self._notes_label, index=0)
            else:
                self._info.remove_widget(self._notes_label)
        self._card.height = data["card_h"]
        self._score_color.rgba = data["color"]
        self.sync(rv.owner)

    def sync(self, owner: "SessionList") -> None:
        """Show the list's state for this row's session: select mode, its checkbox, the rename editor."""
        select = owner._select_mode
        if select != (self._checkbox.parent is not None):
            if select:
                self._card.add_widget(self._checkbox, index=len(self._card.children))
                self._card.remove_widget(self._actions)
            else:
                self._card.remove_widget(self._checkbox)
                self._card.add_widget(self._actions)
        selected = self.sid in owner._selected_ids
        self._checkbox.text = _checkbox_glyph(selected)
        self._checkbox.color = C.ACCENT if selected else C.TEXT_SECONDARY
        editor = owner._rename_row
        if owner._renaming_sid == self.sid and self.sid is not None:
            if editor.parent is not self:
                if editor.parent is not None:
                    editor.parent.remove_widget(editor)
                self.add_widget(editor)
        elif editor.parent is self:
            self.remove_widget(editor)


class _SessionRecycleView(_StableScrollView, RecycleView):
    """One data item per shown session, row widgets only for the rows on screen."""

    def __init__(self, owner: "SessionList", **kwargs):
        super().__init__(**kwargs)
        self.owner = owner
        rows = RecycleBoxLayout(orientation="vertical", size_hint_y=None, default_size=(None, _ROW_H),
                                default_size_hint=(1, None), spacing=S.GAP_SM, padding=[0, S.GAP_SM])
        rows.bind(minimum_height=rows.setter("height"))
        self.add_widget(rows)
        self.viewclass = _SessionRow  # stored on the layout manager, so only once there is one


class SessionList(BoxLayout):
    """The sessions its screen shows, select mode and its selection, and the one rename editor under the row of the
    session being renamed; a row's tap opens, renames, deletes or (in select mode) selects."""

    on_open = Hook()  # a row tapped: its session id
    on_rename = Hook()  # (session id, name): a rename saved, already in the session's dict
    on_delete = Hook()  # [session id]: a row's delete, to confirm
    on_selection = Hook()  # the selection changed: how many are selected

    def __init__(self, **kwargs) -> None:
        super().__init__(orientation="vertical", **kwargs)
        self._shown: list[dict] = []
        self._select_mode = False
        self._selected_ids: set[int] = set()
        self._renaming_sid: int | None = None
        self._build_rename_row()
        self._empty_label = ThemedLabel(text="No sessions on this day", font_size=F.BODY, color=C.TEXT_MUTED,
                                        size_hint_y=None, height=dp(40))
        self._rv = _SessionRecycleView(self)
        self._rv.layout_manager.bind(on_touch_down=self._list_touch_down)
        self.add_widget(self._rv)

    # ── The sessions shown ──

    @property
    def shown(self) -> list[dict]:
        return self._shown

    def show(self, sessions: list[dict]) -> None:
        """A new list, from the top: one data item per session, rows built only for what fits on screen."""
        # A new list starts at the top, at rest: reset the effect itself (pixels, velocity, overscroll) —
        # setting scroll_y alone was overwritten by a fling still in flight.
        self._rv.effect_y.reset(self._rv.effect_y.max)
        self._rv.scroll_y = 1
        self.close_rename()
        self._shown = sessions
        self._show_items()

    def remove(self, gone: set) -> None:
        """Drop deleted sessions in place: the scroll position stays."""
        if self._renaming_sid in gone:
            self.close_rename()
        self._shown = [s for s in self._shown if s.get("id") not in gone]
        self.keep_selected(self._selected_ids - gone)
        self._show_items()

    def update(self, sid) -> None:
        """Re-derive one session's row after its dict changed in place (a rename, notes), or its editor opened or closed."""
        for i, s in enumerate(self._shown):
            if s.get("id") == sid:
                self._rv.data[i] = self._item(s)
                return

    def session_by_id(self, sid) -> dict | None:
        """A listed session's dict, as History holds it (kept current by in-place updates)."""
        return next((s for s in self._shown if s.get("id") == sid), None)

    def _item(self, session: dict) -> dict:
        sid = session.get("id", 0)
        notes = session_notes_line(session)
        card_h = _ROW_H_NOTES if notes else _ROW_H
        return {
            "sid": sid,
            "name": session_title(session),
            "stats": session_stats_line(session),
            "notes": notes,
            "color": score_colour(session.get("avg_shamatha", 0) or 0),
            "card_h": card_h,
            "height": card_h + (_RENAME_H if sid == self._renaming_sid else 0),
        }

    def _show_items(self) -> None:
        self._rv.data = [self._item(s) for s in self._shown]
        empty = not self._shown
        if empty and self._empty_label.parent is None:
            self.add_widget(self._empty_label, index=len(self.children))
        elif not empty and self._empty_label.parent is not None:
            self.remove_widget(self._empty_label)

    def _sync_rows(self) -> None:
        for view in self._rv.layout_manager.children:
            if isinstance(view, _SessionRow):
                view.sync(self)

    def state_text(self) -> str:
        """Its rows, heights and scroll state, for a device log of where a list ended up (#56)."""
        rv, ey = self._rv, self._rv.effect_y
        views = sum(1 for w in rv.layout_manager.children if isinstance(w, _SessionRow))
        return (f"sessions={len(rv.data)} row_widgets={views} list_h={rv.layout_manager.height:.0f} "
                f"viewport_h={rv.height:.0f} scroll_y={rv.scroll_y:.3f} effect={ey.value:.1f} "
                f"bounds=({ey.min:.1f},{ey.max:.1f}) v={ey.velocity:.1f}")

    # ── Select mode ──

    @property
    def select_mode(self) -> bool:
        return self._select_mode

    @property
    def selected_ids(self) -> set:
        return self._selected_ids

    def set_select_mode(self, on: bool) -> None:
        """Enter or leave select mode; leaving drops the selection. The rows on screen gain or lose their checkbox."""
        self._select_mode = bool(on)
        self.close_rename()
        self.keep_selected(self._selected_ids if on else set())

    def toggle_selection(self, sid) -> None:
        self.keep_selected(self._selected_ids ^ {sid})

    def select_all(self) -> None:
        self.keep_selected({s.get("id") for s in self._shown if s.get("id") is not None})

    def keep_selected(self, ids: set) -> None:
        """The one change of the selection: the rows show it, the screen hears its size."""
        self._selected_ids = set(ids)
        self._sync_rows()
        self.on_selection(len(self._selected_ids))

    # ── Inline rename: one editor, shown under the row of the session being renamed ──

    def _build_rename_row(self) -> None:
        self._rename_row = RenameRow(self._do_rename, height=_RENAME_H, padding=[dp(10), dp(2)])
        self._rename_input = self._rename_row.input
        self._rename_focus_check = Clock.create_trigger(self._drop_rename_focus_if_hidden)

    def _drop_rename_focus_if_hidden(self, _dt) -> None:
        if self._rename_row.parent is None:
            self._rename_input.focus = False

    def _toggle_rename(self, sid) -> None:
        """Open the editor on this session's row, or close it if it is already open there."""
        reopen = self._renaming_sid != sid
        self.close_rename()
        session = self.session_by_id(sid)
        if not reopen or session is None:
            return
        self._renaming_sid = sid
        self._rename_input.text = session_label(session)
        self.update(sid)
        self._sync_rows()
        self._rename_row.focus_soon()

    def close_rename(self) -> None:
        sid, self._renaming_sid = self._renaming_sid, None
        if sid is None:
            return
        self._rename_row.close()
        self.update(sid)

    def _do_rename(self) -> None:
        sid = self._renaming_sid
        session = self.session_by_id(sid)
        txt = self._rename_input.text.strip()
        if txt and session is not None and txt != session_label(session):  # unchanged: the stored name stays
            session["session_name"] = txt  # the model row this list shows
            self.on_rename(sid, txt)
        self.close_rename()

    def _list_touch_down(self, rows, touch) -> bool:
        """The one touch router for the rows.

        Bypasses Kivy's flaky nested dispatch for row actions: find the visible row the tap landed in and route to
        select / rename / delete / open by position.
        """
        if not rows.collide_point(*touch.pos):
            return False
        for view in rows.children:
            if not isinstance(view, _SessionRow) or not view.collide_point(*touch.pos):
                continue
            if self._select_mode:
                self.toggle_selection(view.sid)
                return True
            # The open editor (its input and Save) gets the touch the normal way.
            if self._rename_row.parent is view and self._rename_row.collide_point(*touch.pos):
                return False
            actions_left = view.right - dp(80)
            if touch.x >= actions_left:
                if touch.x < actions_left + dp(40):
                    self._toggle_rename(view.sid)
                else:
                    self.on_delete([view.sid])
                return True
            self.on_open(view.sid)
            return True
        return False
