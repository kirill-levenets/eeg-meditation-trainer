# Graphs

`ScrollableGraphWidget`, the single time-series graph class: fit, threshold steps, drawing cost, touch routing and fullscreen.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## ScrollableGraphWidget

- Every live and session-detail graph is a `ScrollableGraphWidget` (`app/ui/raw_eeg_screen.py`).
- **Plot area.**
  `_label_pads` sizes the margins from the labels at each draw:
  left the axis's widest label, right the lines' end values and the scalar threshold's label (drawn in that margin), bottom the time rows, and either side at least half a time label (a mark at the plot's edge centres its label on it).
  They only grow while the data lasts (`_pads_floor`, reset by `clear_data` and a new session's `load_static_data`), so an auto-scaled peak crossing a power of ten or a value gaining a digit doesn't shift the plot sideways at 2 Hz.
  `_plot_rect()` is the one plot rectangle: drawing, glyphs and the pan code read it.
  A line's end label takes the nearest free slot between the plot's bottom and the widget's top (`_free_label_y`, upward first), since the top margin leaves no room above and the bottom one holds the time rows;
  a threshold step's label at the top of the scale goes under its line.
  The Y grid is bounded: a fixed `grid_step` that would draw more than `_MAX_Y_GRID_LINES` lines gives way to `_compute_nice_step`, since each line carries a label (a 200000 scale at the default 20-unit step would draw 10000).
- **Glyphs** sit inside the plot's corners (`_corner_rect`):
  the series picker top-left, expand top-right (in fullscreen the close cross, `set_expand_callback(cb, closes=True)`), fit bottom-right, hidden on a plot too short for it under expand.
  `AppManager._wire_graph_affordances` wires them on every graph (`_all_graphs()`), the one place for cross-graph affordances.
  They are strokes in `TC.TEXT` straight on the graph with no backing (`_draw_icon_backing` only sets the colour), so they contrast on every palette; a fixed backing reads as a grey box on light themes.
- **Glyph touches.**
  A glyph is a button over the data: `on_touch_down` grabs a touch on it like any other and records the glyph in the finger's record (`_glyph_at`);
  while the finger stays on it and within `_GLYPH_DRIFT_DP` of where it landed (a fingertip drifts), it stays pressed (a light disc, `_pressed_glyph`) and fires on release where a clean tap would place a marker;
  more drift or leaving the glyph turns the touch into an ordinary gesture, so a pan, pinch or vertical swipe that starts on a glyph still works.
  A second finger makes the gesture a pinch or a two-finger tap: no glyph fires and no marker is placed.
  The press is the lifted finger's own (`on_touch_up` reads the finger that lifted, not the one left down).
  The hit-test is in window coordinates (`_touch_in_window_rect`, see [Touch](#touch)), so the ScrollView can't starve a glyph the way it would an overlaid Kivy widget.
- **Fit the whole session** (#43):
  `set_fitted(True)` shows all of the data, never in a window narrower than the graph's default (a session just started would be a second stretched across the plot);
  `_fit_restore` keeps the width and scroll position to go back to.
  `_follow_fit` keeps it whole wherever the data's length changes:
  `add_point` / `add_points_batch` (a live session growing), `load_static_data` / `clear_data` (another session: going back then lands at its end).
  A tap fits the graph's zoom group together (`toggle_fit`, over its `_sync_group`), each graph to its own data: a fit is never propagated through the link.
  Raw EEG holds only its last minute, so fitted it shows that; a session longer than the 3 h buffer (`GRAPH_POINTS_MAX`) shows its last 3 h.
  Any `_set_viewport` (a pinch, the wheel, a linked graph's zoom) ends the fit;
  a zoom from a fit starts from the group's widest fitted span (`_zoom_base`), not the zoomed graph's own (raw EEG's is capped at its minute).
  A live session's reload after a screen lock is the same session (`load_static_data(..., new_session=False)`): the fit's way back and the margins carry on.
  A fitted long session redraws at about the cost of the default window: the fold (5) bounds what it draws by the graph's width and line.
- **Zoom groups.**
  `link_zoom` links graphs so a zoom on one zooms all:
  the requested window travels (each graph converts it through its own sample rate and clamps it to its own limits, so raw EEG's one-minute cap never narrows the others), and the group is aligned to the first graph's window as it is linked.
  There are two groups, the live graphs and the session detail's (`AppManager._link_graph_zoom` over `_live_graphs()` / `_detail_graphs()`):
  the saved zoom (`graph_zoom_seconds`) is the live metrics graph's `zoom_seconds`, its window before any fit, so a detail zoomed out over a long session must never reach it.
  Loading it (`AppManager._apply_saved_zoom`) starts both groups at it; only the live group's is ever saved.
  The window's mouse wheel reaches every graph; `_on_window_mouse_down` ignores one not attached to the window (`get_root_window()`), since a graph on a hidden screen or tab keeps its last geometry under the pointer.
- **Series names.**
  Each graph keeps its own copy of the `names` it is built with, so a rename (`set_series_name`: a formula slot's name, a program's line, a session's recorded formulas in the detail) never reaches another graph.
  `SERIES_NAMES` (`live_session.py`, read-only) is the defaults every metrics graph starts from, and what `ProgramRun.end` puts back when a program ends; the band graphs start from `band_spec.GROUP_NAMES`.
- **Series picker.**
  The picker is wired on every graph with more than one series (all but the two raw EEG graphs), since a single-series graph's picker could only blank the line.
  One presenter, `GraphSeries.present_picker(graph)` (`app/ui/graph_series.py`, the app's `_graph_series`, which also saves and restores each graph's selection), reads the graph's own catalog, labels and colours:
  `series_keys()` / `series_name()` / `series_color()`, no hardcoded metric list.
  It lists a program's line only on the live graph while its program runs and computes it (`ProgramRun.computes(key)`: the program's valid custom formulas).
  Each graph carries a `graph_id` (`live_metrics`, `live_band`, `diary_metrics`, `diary_freq`, …) and its selection persists per graph as `graph_series_<graph_id>` (JSON, per user);
  the live metrics graph migrates legacy `toggle_<key>` rows when it has no JSON yet, other graphs default to all visible.
  `set_visible` and `set_series_name` fire the graph's `on_series_change` hook, so the owning screen's legend (visible-filtered) follows any picker toggle, Choose…, restore or program segment;
  a fullscreen graph's legend follows it too ([Fullscreen](#fullscreen)).
  The formula slots' validity gate (`FormulaSlots.for_key(key).is_valid`) applies only to the live metrics graph: the detail's formula lines are recorded data and toggle freely.
- **Scored line colours** (#94, `app/ui/line_colours.py`):
  one series per graph, `set_gradient_series(key)`, is drawn coloured by its value instead of its own colour, in the profile's `LINE_COLOURS`:
  Mono (its own colour after all), Blue › Red (the default, HSV hue 240° › 0°), Viridis, Plasma, Turbo or Red › Green, the last four sampled from matplotlib's and ColorBrewer's palettes as colour stops (no matplotlib on Android).
  The gradient spans 0 → `GRADIENT_TOP` = 200, the metrics graph's axis.
  Every colour is drawn with `theme.with_contrast(rgb, graph background)`:
  as published where it reads 3:1 (WCAG's minimum for graphics), otherwise the nearest lightness of the same hue that does, so a gradient's dark or pale end can't vanish on any of the four themes (Blue › Red's yellow reads 1.1:1 on the light ones).
  Each gradient and background has one cached texture (`gradient_texture`); a theme switch redraws every graph, a new choice (`LINE_COLOURS.add_listener`) every graph with a gradient series.
  The Session screen colours the series being trained, `set_training_series(key)`, the one the legend marks with »: in a simple session the drive key, in a program its segment's;
  the series keeps its colours when the marker clears between sessions, and before the first session it is Shamatha.
  The session detail colours the metric the session was scored on (`recorded_score`); a key that is no series of the graph (a program session's "program", a session from before #51) colours none.
  Settings → Display shows the six as two `PresetRow`s, each gradient with a `GradientStrip` of itself as the graphs draw it on the current theme; the choice is the per-profile `line_colours` setting.
- `ScrollableGraphWidget.set_threshold_steps(steps)` draws the dashed threshold line piecewise, along a list of `(start_tick, target)` steps;
  steps take precedence over `set_threshold(value)`'s single line, and `set_threshold_steps(None)` reverts to it.
  The live metrics graph and the session detail's step it from the ticks' targets (#83), simple and program sessions alike.
  Live, `add_point(values, threshold=)` extends the steps with `extend_steps` at each point:
  the tick's target rides `_ui_update` and the mirror's `score_target`, so `LiveMirror.reload_into` rebuilds the same steps with `target_steps`;
  `_start_session_common` clears them (`_clear_live_display`), and a segment switch doesn't set the line.
  The detail's `detail_graph_data` returns `threshold_steps` (`target_steps` over the rows: None unless every row has a target) and the metrics fill applies them.
  A session from before #83 keeps what the open draws from its row: its program's steps (`sessions.session_program`, mapped through elapsed time) or one line at `threshold_used`.

## Drawing cost

- **Graph drawing cost**: `ScrollableGraphWidget._draw` rebuilds the graph from scratch on every `add_point` (2 Hz per live graph, within the budget of (6)), and GL re-renders it every frame.
  (1) Axis and value labels come from `_LABEL_CACHE`, an LRU of 512 `CoreLabel`s keyed by text, size and colour;
  the `CoreLabel` is kept, not just its texture, because it is the texture's reload observer after an Android GL context loss.
  (2) The X grid step is `_x_grid_step(graph_w, visible_seconds)`, the smallest of 10 s … 2 h that keeps time labels ≥70 dp apart.
  Each label is `elapsed_clock` (`app/session/manager.py`, the Session timer's too): `MM:SS` under an hour, `H:MM:SS` from one (`75:00` would read as minutes).
  (3) A gradient series (`set_gradient_series`, the scored line) is one `Mesh`, one draw call per frame:
  a quad per segment plus a square patch per vertex (Kivy's `Line.width` is the half-thickness, so the patch half-size is `dp(line_width)`);
  each vertex's texture v is its value over `GRADIENT_TOP` (200) in the 1×64 `gradient_texture(name, graph background)` (clamp-to-edge, refilled by a reload observer).
  It is split at `_MESH_MAX_QUADS` = 65535 // 6 = 10922 quads, because Kivy caps a Mesh at 65535 *indices* (GLES2, enforced on Android; 6 per quad);
  the fold (5) doesn't make the split moot for a thin line on a wide fullscreen graph.
  A stencil mask over a gradient doesn't work instead: Kivy counts overlapping mask fragments (wide-line joints), so `equal` leaves holes and `lequal` leaks outside an enclosing ScrollView's stencil;
  and `StencilUse(func_op=...)` in the constructor is silently ignored (only the property setter applies; the getter raises on Python 3).
  (4) `set_drawing_enabled(False)` pauses a graph its owner detached (`LiveSessionScreen._set_view`: the hidden Metrics/Raw view), which keeps its size and would redraw every tick unseen;
  data keeps accruing and the graph redraws once re-enabled.
  (5) A zoomed-out series draws each run of samples' min and max (MinMax; #70, #104):
  `_drawn_indices(key, values, start_idx, per_px)` folds once a run of `_MIN_RUN` (4) samples spans at most `_RUN_STROKES` (2/3) of the stroke (`2 × dp(line_width)`).
  A run is the longest power of two samples that fits, at a fixed absolute sample position (`_appended[key]` counts every sample added, so a buffer that drops its oldest samples doesn't shift the runs).
  Each run draws its min and max in sample order, and the series its first and last sample.
  Why this rule: a MinMax line looks like the full series from about 3 points per stroke width (Van Der Donckt et al., IEEE VIS 2023: the image metrics' curve has its elbow at canvas width × 3 / line width points).
  So a phone's thick stroke needs far fewer points than a desktop's thin one; of the selections they compared, MinMax is the most stable while data streams in.
  Runs at sample positions, not pixel columns, don't move as a fitted graph grows, so the line doesn't shimmer from tick to tick; the price is one change of the line's fine texture each time the zoom doubles and the run size steps.
  The folded line reaches every height the full line reaches, less than the stroke's width to the side, but is not pixel-exact (`tests/test_graph_decimation.py` checks it on the line's centre and on rendered pixels).
  `_RunExtremes` keeps each series' run extremes for its current run size as data arrives, as Audacity keeps its waveform summaries:
  a redraw scans only the runs completed since the last one, the runs a pan back brings into view and the part runs at the window's two ends.
  A new run size replaces the old one's; `load_static_data` and `clear_data` reset them.
  One step stays proportional to the buffered samples: each visible series' `list(deque)` copy, sliced to the window.
  Value labels, markers, the threshold and the time axis use the real indices.
  (6) New data redraws within a budget (#104):
  `add_point` / `add_points_batch` go through `_redraw_for_data`, which redraws at once unless the last redraw took at least `_SLOW_REDRAW_S` (25 ms) and less than `cost / _REDRAW_BUDGET` (10×) has passed since it ended;
  then one `Clock` event redraws at that time, showing every point that waited.
  Every other redraw (the user's zoom, scroll, fit, series toggle, a marker, a reload) draws at once and cancels the waiting one.
  The fold (5) bounds what a redraw draws, but not what it costs on a slow device, nor the slice copies; the budget keeps any graph to about a tenth of the main thread whatever it costs.
  Desktop redraws stay far below 25 ms and are never deferred.

## Touch

- **Glyph hit-testing is done in WINDOW coordinates** (`_touch_in_window_rect`):
  the touch's window position (`self.to_window(*touch.pos)`: `touch.pos` is in the graph's parent frame, and `touch.sx/sy` ignore Settings → Display's Rotate Screen) against the glyph's rect in window coordinates.
  `GraphAwareScrollView` delivers a touch in the graph's parent frame (`_dispatch_to_graph`, #66), since a graph's coordinates are content coordinates, not the view's parent's.
  The draw (`_draw_expand_icon` and the other glyphs') and the hit-test use the same rect (`_expand_icon_rect`, …), so the visible box is exactly the tap target.
  `app/ui/touch_utils.point_in_rect` is the shared rect test.
  The History and user-picker manual routers work with raw `collide_point` because their handlers are bound where the touch is already in the right frame: they're not under `GraphAwareScrollView`.
- **`GraphAwareScrollView._graph_under_touch` hit-tests in WINDOW coordinates**:
  `self.to_window(*touch.pos)` against each graph's rendered window rect (`_window_rect`, via `point_in_rect`), and only inside the viewport's own window rect.
  A ScrollView translates its canvas, so a child's `x`/`y` are content coordinates: a graph's `collide_point` against the touch lets a graph scrolled out of view claim taps on whatever sits in its unscrolled rect (#66).
  A touch on a graph goes straight to it (pan, pinch, tap, glyphs, with no ScrollView hold-to-decide delay), in the graph's parent frame, except a **vertical swipe**:
  `ScrollableGraphWidget._hand_off_vertical_swipe` hands a single-finger touch that moved >20 dp mostly vertically, before any pan or pinch in the gesture, to the view that routed it:
  `touch.ud[GraphAwareScrollView.ROUTED_BY]`, set by `_dispatch_to_graph`.
  `GraphAwareScrollView.scroll_with` takes it only if the page can scroll, isn't already scrolling under another finger and the finger is still inside it, otherwise the graph keeps the touch;
  the graph releases the touch and undoes any pan only on success.
  The view is never found by a walk up the tree: Kivy's `Window.parent` is the Window itself, so the walk never ends for a graph with no such ancestor (fullscreen).
  The graph has no vertical gesture, and in landscape scroll mode the live graph fills the viewport the user scrolls to reach the stats and Start/Stop.
  `_grabbed_touches` is uid → that finger's `start`/`pos` in the graph's parent frame:
  pinch reads positions from it (never another touch's `.pos`, whose frame depends on where it was last dispatched), each finger is measured from its own start, and when a pinch ends the remaining finger pans on from where it is.
  A move over 10 dp on either axis cancels the tap (`_tap_cancelled`), so a vertical drag the graph keeps places no marker.
  `tests/test_graph_scroll_touch.py` uses the session detail's real shape (notes above, graph at the bottom) and the live body's (graph filling a translated viewport):
  taps across the visible graph, vertical swipe scrolls, horizontal drag pans, pinch never scrolls.
  **`GraphAwareScrollView.on_touch_down`/`on_scroll_start` only intercept touches inside the ScrollView's own viewport** (`self.collide_point` guard):
  a graph's *logical* bounds extend past the visible viewport when the body overflows (scroll mode), so `_graph_under_touch` would otherwise match, and steal, touches aimed at widgets outside the scroll (e.g. the Metrics/Raw toggle above it).
  Regression-tested in `tests/test_ui_widgets.py::TestGraphAwareScrollViewGuard`.

## Fullscreen

- Fullscreen expand (`GraphFullscreen.present` in `app/ui/graph_fullscreen.py`, the app's `_fullscreen`, wired by `_wire_graph_affordances`) **reparents** the graph, not a clone:
  into a full-window `FloatLayout` overlay on `self._float_root` with `size_hint=(1,1)` + `pos_hint={"x":0,"y":0}`, so it reaches every edge, where a `Popup` insets its content with chrome.
  Reparenting keeps the single `Window.on_mouse_down` bind and the live `add_point` feed, so a running session's graph updates live in fullscreen.
  While fullscreen the expand glyph is the close cross (`closes=True`); it, Android back and Esc (`_on_keyboard` → `GraphFullscreen.close`) restore the graph to its original parent and index and give it the expand glyph back.
  While fullscreen, `GraphFullscreen` chains its own legend onto the graph's `on_series_change` (`_series_changed`: the owner's handler if one is wired, then `refresh_legend`) and wires the owner's handler back on close.
  A handler wired to the graph while it is fullscreen would be replaced on close: only the owning screen wires it, once at build.
  **Capture `list(size_hint)`/`list(size)` copies before overriding**: they are live `ReferenceListProperty`s, and a bare reference tracks the `(1,1)` you set and breaks restore.
