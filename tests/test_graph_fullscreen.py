import unittest

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from app.ui.graph_fullscreen import GraphFullscreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import StyledButton


class TestGraphFullscreen(unittest.TestCase):
    """Reparent-into-overlay fullscreen present + restore round-trip."""

    def _make(self):
        app = GraphFullscreen(FloatLayout())
        parent = BoxLayout()
        g = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0})
        g.size_hint = (0.5, 0.5)
        g.set_expand_callback(app.present)
        parent.add_widget(g)
        return app, parent, g

    def test_present_reparents_and_fills(self):
        app, parent, g = self._make()
        app.present(g)
        self.assertIsNotNone(app._overlay)
        self.assertIn(app._overlay, app._root.children)
        self.assertIsNot(g.parent, parent)                 # reparented out
        self.assertTrue(g._expand_closes)                  # the corner glyph is the close cross in fullscreen
        self.assertFalse(any(isinstance(c, StyledButton) for c in app._overlay.children))  # no other close
        self.assertEqual(tuple(g.size_hint), (1, 1))       # fills the overlay slot
        self.assertEqual(g.pos_hint, {})                   # in a BoxLayout, not positioned

    def test_series_picker_survives_fullscreen(self):
        # The combobox (series picker) must keep working in fullscreen so custom
        # formulas can be toggled/chosen there too — only the expand glyph is hidden.
        app, parent, g = self._make()
        g.set_series_picker_callback(lambda _g: None)
        app.present(g)
        self.assertIsNotNone(g._series_callback)           # picker still wired in fullscreen
        g._expand_callback(g)                              # the close cross
        self.assertIsNotNone(g._series_callback)           # and after restore

    def test_close_restores(self):
        app, parent, g = self._make()
        orig_size_hint = tuple(g.size_hint)
        app.present(g)
        overlay = app._overlay
        g._expand_callback(g)                              # a tap on the close cross in the plot's corner
        self.assertIsNone(app._overlay)
        self.assertIs(g.parent, parent)                    # back in original parent
        self.assertFalse(g._expand_closes)                 # the expand glyph again
        self.assertEqual(g._expand_callback, app.present)
        self.assertEqual(tuple(g.size_hint), orig_size_hint)
        self.assertNotIn(overlay, app._root.children)

    def test_present_is_reentrant_guarded(self):
        app, parent, g = self._make()
        app.present(g)
        first = app._overlay
        app.present(g)                   # second call is a no-op
        self.assertIs(app._overlay, first)
