# UI foundation: theme, widgets, modals

Navigation, the theme system and its runtime switches (colour role, text size), shared widgets, and the one modal style.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Navigation and theme

**Navigation:** 3-tab bottom bar (Session / History / Settings) via `BottomNav` in `theme.py`.
With no active user the first-run popup (the user gate) is shown.

- **Theme system** (`theme.py`): the `C` colour accessor (4 palettes: Dark Blue, Dark Green, Light Cream, Light Green), `F` font sizes, `S` spacing.
  `format_duration(seconds)` shows seconds under 1 min, minutes under 1 h, hours otherwise.
  `make_scroll_popup(title, rows, footer=None, *, est_rows=None, ...)` builds every list-style select dialog (series picker, saved-formula chooser, a segment's formula, sound source picker, program picker, duration picker):
  the `rows` scroll inside a `ScrollView` with the `footer` pinned below, sized to content but capped at 85% of the window so long lists scroll instead of overflowing;
  `est_rows` overrides the height estimate when a row is itself a multi-row grid.
  `make_message_popup` is the one message modal, built on it (see **Modals**).
  Custom widgets: `StyledButton` (rounded, press feedback, MDI icons, outline mode; `vertical=True` for icon over text), `Card`, `Divider`, `ThemedAccordion`, `PresetRow`, `RevealBox`, `BottomNav`.
  A theme switch repaints everything live, with no screen rebuild, by colour role (see **Theme colours** below).
  `StyledButton` resolves its text/icon colour by **role**, re-applied on a bg or theme change:
  no `text_color` (or `text_color = None`, which returns to it) is **AUTO**, `readable_fg(bg_color)`, the light or dark glyph with the higher WCAG contrast against *that button's* background;
  that is at least ~3.9:1 on the palette's fills (the lowest are its mid-tones, Light Cream `PRIMARY` and Dark Green `PRIMARY_DIM`).
  A palette `text_color` (`C.X`) follows the theme through `ThemedMixin`; any other colour is fixed.
  A **selected** state is an accent fill with AUTO (`text_color=None`): `C.TEXT` on a bright fill is 1.5–2:1 in the dark themes.
  **Disabled** dims label and icon to a 60/40 blend of `readable_fg(bg)` into the disabled `C.BG_CARD` fill, at least ~4:1 in every theme (the theme's `C.TEXT_MUTED` washes out on light cards).
  The dimmed colour goes to the labels' **`disabled_color`** as well as `color`: Kivy's `Label` draws `disabled_color` (default white@.3, invisible on light cards) whenever the widget is disabled.
  **Pressed** darkens the background (glyph colour unchanged) **and** raises an edge-visible press ring (issue #33), since a darker fill alone is hidden under the fingertip:
  `on_state` snaps `_ring_alpha` to `_RING_MAX` on `down` and `Animation`-fades it to 0 over `_RING_FADE` on release, so the cue lingers after the finger lifts.
  The ring is a `Line` drawn in `_redraw` at `_ring_rgb()` = `C.TEXT`: its contrast derives from the **surrounding surface** (light on dark themes, dark on light), NOT the button fill, the same rule as the graph expand glyph;
  `readable_fg(fill)` would give a dark ring on a bright accent button that vanishes on a dark theme.
  `flash_confirm(text="Saved", icon=None, confirm_color=None, duration=1.1)` is the action-confirmation cue (issue #33 E):
  it morphs the label (and optionally the icon / fill) to a success state, then `Clock`-reverts to the **true** original (reentrancy-safe: a repeat tap restarts the timer without capturing the intermediate state).
  Main-thread only.
  On a text-only button the icon is drawn inline in `Icons`-font markup, and only when the font loaded (a bare `[font=Icons]` tag is tofu).
  The program **Save** success path uses it: `ProgramSettings._save` → `TimerSection.confirm_program_saved()`, "Saved" with a check on a `C.SHAMATHA` green fill.
  **`RevealBox(content_height)`** is the touch-safe way to show a row conditionally: `set_content(*widgets)` once, then `reveal(bool)`;
  it **detaches** the children when hidden (an empty box at height 0) rather than collapsing them in place.
  Never hide interactive content with `height=0`/`opacity=0`/`disabled=True`:
  Kivy's `Widget.on_touch_down` does `if self.disabled and self.collide_point(...): return True`, so a hidden-but-attached disabled widget *consumes* taps on whatever it overlaps (a known Kivy bug, unfixed in 2.3.x);
  `on_touch_up`/`on_touch_move` ignore it without consuming.
  `tests/test_touch_regression.py` enforces this:
  it mounts screens in a real window and flags actual dead zones, the collapse-in-place anti-pattern (a disabled, collapsed container still holding interactive children) and attached invisible interactive widgets.
- **Theme colours** follow a runtime switch by role, not by snapshot (#38).
  `C` is a `_ColorAccessor`; every colour read from it (`C.BG_CARD`) is a `ThemeColor`, a tuple that also carries its `role`; `list()` or a slice of it is a plain, fixed colour.
  A widget colour property given one records the role and is re-applied from the new palette on every `C.set_theme(name)`;
  applying the theme already active is a no-op (every profile activation applies its stored theme).
  Any other value stays fixed, and assigning a literal later drops the role.
  `ThemedMixin.__setattr__` records the roles; it is mixed into `ThemedLabel`, `ThemedTextInput`/`CenteredTextInput`, `StyledButton`, `Card`, `Divider` and `ThemedPopup`, and covers these properties:
  `color`, `disabled_color`, `bg_color`, `bg_pressed`, `text_color`, `background_color`, `foreground_color`, `cursor_color`, `hint_text_color`, `selection_color`, `title_color`, `separator_color`, `overlay_color`.
  A role resolves in the current palette at assignment, so a `C.X` stored before a switch (e.g. `PresetRow`'s selected colour) still paints the new one.
  Every Label and TextInput in `app/ui` is the themed one: `tests/test_theme_switch.py` fails on an import from `kivy.uix.label`/`kivy.uix.textinput` outside `theme.py`.
  Canvas: `ThemedColor(C.X, alpha=None)` is a `Color` instruction that re-reads its role on a switch, and `fill_background(widget, C.X)` is the one background fill for screens and overlays.
  Widgets that rebuild their canvas from the palette on redraw register that redraw with `C.add_listener` (once however often registered):
  `ScrollableGraphWidget`, the History calendar and 14-day bars, `StyledButton`'s disabled/outline fill and press ring, `BandTotalsView`, the duration picker.
  Listeners run after the roles are re-applied; a bound method is held weakly and its entry drops itself when the widget dies; a failing listener or widget repaint is logged without stopping the switch.
  To save and restore a themed colour use `widget.assigned_color(prop)`: a `list()` copy freezes it (`flash_confirm` restores its fill this way).
  Code that keeps colours and unpacks them into canvas `Color`s draws `C.resolve(color)`, a palette colour in the current palette and anything else as it is:
  module-level series dicts like `live_session.METRICS_COLORS` are read once at import, and `ScrollableGraphWidget.series_color` resolves them, so a line and its legend swatch agree.
  The Settings → Theme highlight is a listener, so it also follows a theme applied by a profile switch.
  `build()` builds the UI in `startup_theme(db)`, the startup profile's theme (see [storage.md](storage.md#per-user-settings)), so loading that profile applies the theme already showing.
  `tests/test_theme_switch.py` shows each screen in one palette from its default view (each screen is built once per module and handed back reset to that view, `tests/_shared_screens.py`);
  it switches and checks every widget colour property and canvas `Color` for a colour from the old palette:
  after the switch and after each state reachable later (every Settings section opened, the summary card, select mode, both History views, every session-detail tab).

- **Text size** (`F`, #76) follows a runtime change the way colours follow a theme switch.
  Every font size comes from `F`:
  the roles (`F.BODY`, `F.SMALL`, …) and `F.px(n)` for a size off them (a graph's canvas labels through `_make_text_texture(size=…)`, Kivy's own defaults: `ThemedLabel` and `ThemedTextInput` default to `F.px(15)`, Kivy's 15 sp).
  Each is a `FontSize`, a float that also carries its `base` (its size at the normal text size) and its `cap`; arithmetic on it is a plain, fixed size.
  `ThemedMixin.__setattr__` records a `font_size` or `title_size` given one in `F._sized` (widget → {property: (base, cap)}) and stores the plain size:
  Kivy's numeric properties reject a float subclass, so a `FontSize` given to a widget that isn't themed raises at once.
  Any other value drops the record and stays fixed: `F.glyph(n)` is an icon in fixed chrome (the bottom nav's 46 dp bar).
  A size read before a change (a `LegendBar`'s stored `F.TINY`) still resolves at the size in use.
  `F.set_scale(scale)` (a no-op for the size in use, which a profile load applies at startup) re-sets the roles, re-applies every recorded size, then calls the listeners registered with `F.add_listener`:
  `Listeners`, the registry `C.add_listener` uses, with the same rules.
  The listeners are what was sized from text when drawn:
  the graphs redraw (their labels and the margins those take), the band table re-renders, History's charts redraw, the saved card re-lays its notes field, the Session screen's status line re-fits, the Settings picker selects the size in use.
  A `StyledButton`'s text and icon labels are plain Kivy labels that follow its `font_size` and `bold`.
  `text_size` is a per-profile registry setting whose getter and setter are `F.SCALE` and `F.set_scale`, so the picker and a profile switch both apply it at once (the sizes on offer are `TEXT_SIZES`, 100 / 125 / 150 %);
  `build()` builds at `startup_text_size(db)`, the startup profile's size, so loading that profile changes nothing it just laid out.
  `tests/test_text_size.py` fails on a size given directly (`font_size=dp(…)`, `sp(…)`, a bare number, Kivy's string units), which would ignore the setting.
  The app doesn't follow Android's system font size: every size is `dp`.
- **Boxes that hold text follow it; text in a box that can't stops growing.** At 150 % a fixed box cuts text off or wraps it, so:
  - a multi-line label takes its text's height (`fit_height_to_text(label)`; the same test fails on a multi-line `ThemedLabel` with a fixed height);
    a row of a wrapping label beside fixed-height controls is as tall as the label, at least its old height, with the controls centred (`fit_row_to_text(row, label, min_height)`: Settings' checkbox rows, Marker Hotkey, History's list heading);
  - a box sized for its text takes `F.box(n)` (a plain `dp(n) * F.SCALE`, up to a cap when its text is capped) and re-reads it in an `F.add_listener`:
    the band table's rows and columns, the 14-day chart's margins and label boxes, the saved card's notes field, the Session screen's status line;
    a box whose text changes as well sizes itself to it (the timer length beside Start, `_fit_width`: as wide as its capped text, "105m", at least 20 dp);
  - a `StyledButton` fits its sides to its text (`_fit_padding`):
    `S.BTN_PAD` (12 dp) when its text (or icon) fits on one line, narrower down to `S.BTN_PAD_NARROW` (2 dp) when the button is too narrow for it, leaving 2 dp spare;
    it is measured (`text_width`, also the saved card title's cut) once per text, icon, size and weight, and `set_icon` swaps the glyph before `icon` changes, so the sides fit the glyph shown.
    Fixed 12 dp sides would leave a 40 dp button 16 dp: History's Cal / 14d, the duration presets and a segment's End cue / Feedback would wrap, an icon-only `FoldChevron` would crop its glyph.
    A text measured with nothing spare wraps on the phone, whose whole pixels round differently.
    `padding=` fixes the sides instead;
  - where the box can't grow with its text (a fixed strip of columns, a status line), the text is `F.capped(size)`: it follows the text size up to `F.CAPPED_MAX` (120 %), or a cap of its own.
    Capped: the Session screen's status line and timer length (the bottom bar's width is fixed: grown to 150 %, "105m" would squeeze Start onto two lines on the phone);
    its stat strip's titles (110 %, "Distraction" in a fifth of a 360 dp phone) and LIVE toggle; a program's segment row and its header.
    Everything else grows to 150 %.
    A cap is added only where a test fails without it.

  `test_no_text_outgrows_a_box_at_the_largest_size_that_it_fits_at_normal` builds the main screens at both sizes in a 360 dp frame and fails on any text that fits its box at the normal size and not at the largest:
  the Session screen, with no timer and a 105 min one, and its saved card; History in both views, with a day picked; every Settings section, a program's segments, a filled profile list and the locked-screen row; the session detail; the bottom nav.
  It measures the text, not the label's texture, which is exactly the box when the text area is pinned to it (and cut).
  A centred line has room above and below its letters, so a box up to 0.3 em shorter only trims that; a pinned label must also fit 1 dp narrower, since a text with nothing spare wraps at another density.
  A text field must hold its text or hint (wrapped when multi-line, from the top down, so no room is allowed).
  A label also mustn't reach past its parent (a chart's axis label).
  `test_the_timer_pill_holds_every_timer_on_one_line` checks every length from 1 to 120 min, no timer and a program's P, at both sizes.
  `test_the_largest_size_also_fits_at_a_phones_pixel_density` (slow) runs those two and the narrow-button test again in a process at 2.75 px per dp, the test phone's:
  a text that just fits at 1 px per dp can wrap there (History's Cal, the 14-day chart's "100", the stat titles).
  `test_a_screen_switched_to_a_size_is_laid_out_as_one_built_at_it` builds each screen at the normal size, switches to the largest, and compares every widget's text, font and size with the same screen built at the largest:
  switched before a state is reached (a Settings section opened while its content was detached) and, in its slow variant, while it is shown.

## Widgets

- **Icons** (`app/assets/fonts/materialdesignicons-webfont.ttf`): Material Design Icons font, registered as `'Icons'`; the `ICONS_AVAILABLE` flag allows a graceful fallback if the font is missing.
- **App icons** (`app/assets/icons/`): Generated EEG brainwave icon (512/192/128/48 PNG + ICO + ICNS), presplash for Android.
- **Shared widgets** (`widgets/`): `UserPickerForm` (the first-run popup and Settings → User Profile): the existing profiles, a name input, and for a duplicate name an inline "Use existing 'X'" / "Change name" choice.
  `LoadingOverlay` (`widgets/loading_overlay.py`) is the app-global modal spinner (status + animated dots on the theme's `ModalPanel` over a dim);
  it is mounted by wrapping the app root in a `FloatLayout` and shown via `EEGMeditationApp.show_loading(text, delay=0.0)`/`hide_loading()`.
  With a `delay` it takes taps at once and paints only once the delay has passed, so a job that ends sooner never flashes it.
  It animates via `Clock`, so the caller must move the long work off the main thread or the overlay can't paint.
- All legends are one wrapping `LegendBar` (`app/ui/widgets/legend.py`, a `StackLayout` flow):
  `set_items([(text, rgba)])` sizes each label to its text and wraps to extra rows, so many series (7 metrics, 3 custom formulas, 3 program lines) stay readable instead of overlapping in one row.
  Used by the live metrics/band legends, the diary legend, and the fullscreen legend.
- `_AccordionSection` (`app/ui/theme.py`) binds `_content.minimum_height` to `_update_height`, so its `_scroll.height` follows content added after the section opened (`populate_bt_devices` in an open Device section);
  without it such a list is clipped to the height the content had when the section opened.
- `theme.CenteredTextInput`: a `ThemedTextInput` with `halign="center"` (native Kivy 2.3) and vertical centring by padding (`_recenter` sets `padding[1]`/`padding[3]` to `(height - line_height) / 2` on each resize, since Kivy has no `valign`).
  All single-line inputs use it; the two multi-line fields (diary notes, the end card's quick notes) are plain `ThemedTextInput`s.
- **Linux clipboard**: importing `theme` limits Kivy's clipboard to SDL2 (`_clipboard_without_commands`: `kivy_options["clipboard"] = ("sdl2",)`, `kivy_options["cutbuffer"] = ()`), before any text input asks for one.
  Kivy otherwise picks xclip or xsel by running them and waits with no timeout: bare `xsel` reads its stdin when that isn't a terminal and asks the X selection's owner,
  so an open stdin or an owner that never answers hung the first text input (#118), and a stdin that isn't a terminal cleared the user's selection.
  `KIVY_CLIPBOARD=sdl2` alone isn't enough: the cut buffer is picked from xclip and xsel whatever it says.
  SDL2 reads the clipboard itself, with a 1 s timeout (SDL 2.28.5, bundled with the Kivy 2.3.0 wheel).
  The cost: no cut buffer, so no middle-click paste or select-to-copy in text inputs, and Kivy logs one CRITICAL "no Cutbuffer provider" line per start;
  SDL2 holds a copy only while the app runs, so without a clipboard manager it is gone at exit.
  `tests/test_linux_clipboard.py` builds the first text input with stand-in commands that never answer.
- **Hooks** (`app/ui/hooks.py`): a handler the app plugs into a widget is a `Hook` declared on the widget's class (`on_test_audio = Hook()`; a query takes a default: `device_state = Hook(default=(None, None))`), and the widget calls it directly:
  unset, or set to None, it does nothing and returns its default, so no call needs a None guard.
  The app plugs handlers in with `wire(widget, on_x=handler, …)`, one call per widget, which raises at once on a name that isn't a hook: a misspelt wiring fails at `build()` instead of never firing.
  `is_wired(widget, name)` serves a call whose behaviour depends on a handler being there: the session detail's CSV export opens its file chooser only when a handler can take the file.
  A default must be immutable, since every widget of the class shares it; `Hook` refuses a list, dict or set.
  A hook named `on_<property>` on a Kivy widget would be called by Kivy on every change of that property, and one named after a registered event (`on_touch_down`) on every dispatch of it;
  `tests/test_hooks.py` fails on either, inherited ones included.
  A widget that forwards to a hook of its own child wraps the call in a lambda, since reading a hook returns the handler wired at that moment.
  Not hooks: the graph's glyph setters (`set_expand_callback`, `set_series_picker_callback`, `set_fit_callback`), where setting a handler shows the glyph and None hides it;
  and callbacks passed to a constructor (`WhatIfPanel`, `UserPickerForm`, `BandTotalsView`).

## Modals

- **One modal style, in the active theme.** Every popup is a `ThemedPopup` (a `Popup` subclass, so `isinstance(w, Popup)` checks hold):
  Kivy's always-dark 9-patch chrome is turned off (`background=""`, transparent `background_color`);
  `paint_panel` draws the window behind Popup's kv frame (the screen colour `C.BG`, rounded, with a `C.BORDER` edge) over a `C.BG_OVERLAY` dim, with a bold centred `C.TEXT` title (`F.H3`) and a thin `C.BORDER` separator;
  body text is `C.TEXT` and rows/cards keep their `BG_CARD`, so a modal reads like a small screen.
  The in-screen modal cards (the session-end card, the connection overlay and the `LoadingOverlay`) are a `ModalPanel` (the same `paint_panel`, title and separator) on a `ModalScrim`:
  the `C.BG_OVERLAY` dim, which like a popup's overlay keeps taps from reaching the screen behind (Start/Stop/Mark under the end card or the connection card).
  The end card is as tall as its content when that fits and otherwise the space there is, scrolling the rest (centred, a taller card would push OK off screen);
  in two columns, 260 dp with its margin, it fits the ~314 dp a 360 dp landscape phone has above the bottom nav (`test_the_session_end_card_fits_a_landscape_phone_above_the_bottom_bar`).
  The connection card attaches Retry only on failure (a hidden one leaves a blank slot).
  A toast is `C.TEXT` on `paint_panel`.
  The diagnostic dialog (`CrashDialog`) is built from the themed widgets;
  if that raises (the crash may be in the theme layer), from stock Kivy ones (`_plain_makers`, the one `# plain-ok:` exception to the popup-import guardrail);
  if both fail it resets `in_dialog`, so later reports aren't dropped as re-entrant.
  Every Cancel/Close is `cancel_button()` (`C.TEXT_SECONDARY` on `C.BG_CARD`).
  A `ThemedPopup` with `size_hint=(w, None)` and no `height` is as tall as its content, capped at 85% of the window like `make_scroll_popup` (a fixed `size_hint` height leaves a half-empty panel);
  list pickers go through `make_scroll_popup`, messages through `make_message_popup`.
  `ThemedTextInput` defaults to the theme's input colours.
  `ThemedFileChooser` draws its entries and column headers in the theme's text colours and tints a selected entry from `C.PRIMARY`:
  Kivy draws white names, unreadable on a light panel, and a fixed grey selection that puts a selected name dark on dark.
  `tests/test_modal_style.py` opens each kind of modal in all four themes:
  it checks every visible label against the surface it is drawn on (its button, card, input or the panel) for 3:1 and that each is drawn with `paint_panel`;
  it fails on an import from `kivy.uix.popup`/`kivy.uix.filechooser` anywhere in `app/` outside `theme.py`.
- `theme.make_message_popup` is the one message modal, built on `make_scroll_popup`.
  It serves `_info_popup`, the profile-delete confirm, the locked-screen alert, the diary export result and `theme.confirm_popup`, the one confirm:
  History's delete confirm and `_confirm_action(title, message, ok_text, on_ok, ok_color=None, on_cancel=None)` (program save-overwrite / load / delete, a saved formula's delete, Restore, Stop, the end card's Delete).
  The message label is measured wrapped (`text_size` + `texture_update`) so the popup sizes to it, capped at 85% of the window and scrolling beyond:
  a label with `text_size` bound to a fixed-height popup makes Kivy silently drop the lines that don't fit.
  Body text is `C.TEXT` on the modal panel (see **One modal style**).
