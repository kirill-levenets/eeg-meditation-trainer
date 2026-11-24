"""The app's modals: the themed popup and file chooser, the in-screen modal card, and the message, list and confirm
popups built on them."""

from kivy.core.window import Window
from kivy.graphics import Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from app.ui.theme import C, Divider, F, S, ThemedColor, ThemedLabel, ThemedMixin, fill_background, fit_height_to_text
from app.ui.widgets.styled_button import StyledButton, cancel_button


def paint_panel(widget) -> None:
    """The modal panel every popup and in-screen modal card is drawn on: the screen colour, rounded, with a border
    edge, following the widget's size, position and theme switches."""
    with widget.canvas.before:
        ThemedColor(C.BG)
        fill = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[S.RADIUS])
        ThemedColor(C.BORDER)
        edge = Line(rounded_rectangle=[widget.x, widget.y, widget.width, widget.height, S.RADIUS], width=1)

    def _place(*_a):
        fill.pos, fill.size = widget.pos, widget.size
        edge.rounded_rectangle = [widget.x, widget.y, widget.width, widget.height, S.RADIUS]

    widget.bind(pos=_place, size=_place)


_MODAL_PAD = dp(12)  # Popup's frame padding, so in-screen modal cards match it


class ModalScrim(AnchorLayout):
    """The dimmed backdrop of an in-screen modal (session end, connection, loading): centres its ModalPanel and,
    like a popup's overlay, keeps taps from reaching the screen behind."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        fill_background(self, C.BG_OVERLAY)

    def on_touch_down(self, touch):
        if self.width <= 0 or self.height <= 0:  # collapsed (hidden): collide_point is still true at its origin
            return False
        return super().on_touch_down(touch) or self.collide_point(*touch.pos)


class ModalPanel(BoxLayout):
    """An in-screen modal card (session end, connection, loading): the popup panel, title and separator, so it looks
    like every ThemedPopup. Its height follows its content."""

    def __init__(self, title: str = "", **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("padding", _MODAL_PAD)
        kwargs.setdefault("spacing", S.GAP)
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))
        paint_panel(self)
        self.title_label = None
        if title:
            self.title_label = ThemedLabel(text=title, font_size=F.H3, bold=True, color=C.TEXT, halign="center",
                                           size_hint_y=None)
            fit_height_to_text(self.title_label, extra=dp(8))
            self.add_widget(self.title_label)
            self.add_widget(Divider())


class ThemedPopup(ThemedMixin, Popup):
    """The app's popup: the modal panel (paint_panel) over the theme's dimmed screen, with a bold centred title."""

    def __init__(self, **kwargs):
        kwargs.setdefault("background", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))  # paint_panel draws the window behind Popup's frame
        kwargs.setdefault("overlay_color", C.BG_OVERLAY)
        kwargs.setdefault("title_color", C.TEXT)
        kwargs.setdefault("title_size", F.H3)
        kwargs.setdefault("title_align", "center")
        kwargs.setdefault("separator_color", C.BORDER)
        kwargs.setdefault("separator_height", dp(1))
        fit = ((kwargs.get("size_hint", (1, 1))[1] is None or ("size_hint_y" in kwargs and kwargs["size_hint_y"] is None))
               and "height" not in kwargs)
        super().__init__(**kwargs)
        frame = self._container.parent  # the title / separator / content grid from Popup's kv rule
        paint_panel(frame)
        self._title_label = next(w for w in frame.children if isinstance(w, Label))
        self._title_label.bold = True
        self._fitted = None  # the content whose minimum_height the height follows
        if fit:  # size_hint=(w, None) and no height: as tall as the content, capped like make_scroll_popup
            self._title_label.bind(height=self._fit_height)
            self.bind(content=self._fit_height)
            self.bind(on_open=lambda *_a: Window.bind(size=self._fit_height),
                      on_dismiss=lambda *_a: Window.unbind(size=self._fit_height))
            self._fit_height()

    def _fit_height(self, *_a) -> None:
        content = self.content
        if content is not self._fitted:
            if self._fitted is not None:
                self._fitted.unbind(minimum_height=self._fit_height)
            self._fitted = content
            if content is not None and "minimum_height" in content.properties():
                content.bind(minimum_height=self._fit_height)
        if content is None or "minimum_height" not in content.properties():
            return
        frame = self._container.parent
        chrome = frame.padding[1] + frame.padding[3] + self._title_label.height + dp(4)  # + the separator row
        self.height = min(content.minimum_height + chrome, Window.height * 0.85)


class ThemedFileChooser(FileChooserListView):
    """FileChooserListView with its entries in the theme's text colour (Kivy draws them white, unreadable on a light
    panel)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for w in self.walk(restrict=True):  # the Name / Size column headers
            if isinstance(w, Label):
                w.color = C.TEXT_SECONDARY

    def on_entry_added(self, node, parent=None):
        node.color_selected = (*C.PRIMARY[:3], 0.3)  # Kivy's fixed grey made a selected name dark on dark
        for w in node.walk(restrict=True):
            if isinstance(w, Label):
                w.color = C.TEXT
        super().on_entry_added(node, parent)


def make_scroll_popup(title, rows, footer=None, *, width_hint=0.85, row_h=None,
                      est_rows=None, max_height_hint=0.85, auto_dismiss=True):
    """Popup with a vertically-scrolling list of fixed-height `rows` and an optional
    pinned `footer`. Sizes to content but caps at `max_height_hint` of the window so
    long lists scroll instead of overflowing the screen. `est_rows` overrides the
    row-count used for the height estimate (for a row that is itself a multi-row grid).
    Returns the Popup."""
    row_h = row_h or dp(44)
    inner = BoxLayout(orientation="vertical", spacing=S.GAP_SM, size_hint_y=None)
    inner.bind(minimum_height=inner.setter("height"))
    for w in rows:
        w.size_hint_y = None
        if not w.height:
            w.height = row_h
        inner.add_widget(w)
    scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
    scroll.add_widget(inner)
    body = BoxLayout(orientation="vertical", spacing=S.GAP_SM, padding=S.GAP)
    body.add_widget(scroll)
    if footer is not None:
        footer.size_hint_y = None
        if not footer.height:
            footer.height = row_h
        body.add_widget(footer)
    n = (est_rows if est_rows is not None else len(rows)) + (1 if footer is not None else 0)
    content_h = n * (row_h + S.GAP_SM) + dp(90)  # rows + title bar + padding chrome
    height = min(content_h, Window.height * max_height_hint)
    return ThemedPopup(title=title, content=body, size_hint=(width_hint, None),
                       height=height, auto_dismiss=auto_dismiss)


def make_message_popup(title, message, buttons, *, width_hint=0.85, auto_dismiss=True):
    """Message modal with a row of `buttons`; the text wraps and scrolls, so no line is ever silently dropped."""
    label = ThemedLabel(text=message, font_size=F.BODY, halign="center", valign="top",
                        color=C.TEXT, size_hint_y=None)
    # Measure the wrapped text now so the popup sizes to it (capped; beyond that it scrolls).
    label.text_size = (Window.width * width_hint - dp(48), None)
    label.texture_update()
    label.height = label.texture_size[1]
    fit_height_to_text(label)
    btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
    for btn in buttons:
        btn_row.add_widget(btn)
    return make_scroll_popup(title, [label], footer=btn_row, width_hint=width_hint,
                             est_rows=int(label.height // dp(44)) + 1, auto_dismiss=auto_dismiss)


def confirm_popup(title, message, ok_text, on_ok, *, ok_color=None, on_cancel=None):
    """The one confirm: OK runs on_ok; every other close (Cancel, a tap outside, Android back) runs on_cancel. It decides
    once, because Kivy still delivers taps to a popup while it fades out."""
    ok_btn = StyledButton(text=ok_text, bg_color=ok_color or C.ACCENT)
    cancel_btn = cancel_button()
    popup = make_message_popup(title, message, [ok_btn, cancel_btn])
    decided = []

    def _ok(*_a):
        if decided:
            return
        decided.append("ok")
        popup.dismiss()
        on_ok()

    def _closed(*_a):
        if not decided:
            decided.append("cancel")
            if on_cancel is not None:
                on_cancel()

    ok_btn.bind(on_release=_ok)
    cancel_btn.bind(on_release=popup.dismiss)
    popup.bind(on_dismiss=_closed)
    popup.open()
    return popup
