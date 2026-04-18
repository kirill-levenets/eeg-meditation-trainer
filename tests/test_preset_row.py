import unittest

from app.ui.theme import C, PresetRow


class TestPresetRow(unittest.TestCase):
    def test_values_api_still_works(self):
        row = PresetRow(values=[5, 10, 15], fmt="{} min")
        self.assertEqual(len(row.children), 3)
        labels = [btn.text for btn in reversed(row.children)]
        self.assertEqual(labels, ["5 min", "10 min", "15 min"])

    def test_items_api_accepts_label_value_tuples(self):
        row = PresetRow(items=[("5 min", 5), ("Free", None)])
        labels = [btn.text for btn in reversed(row.children)]
        self.assertEqual(labels, ["5 min", "Free"])
        self.assertIn(5, row._buttons)
        self.assertIn(None, row._buttons)

    def test_callback_receives_stored_value_not_label(self):
        received = []
        row = PresetRow(
            items=[("Free", None), ("5 min", 5)],
            callback=received.append,
        )
        row._buttons[None].dispatch("on_release")
        row._buttons[5].dispatch("on_release")
        self.assertEqual(received, [None, 5])

    def test_set_selected_highlights_matching_button(self):
        row = PresetRow(items=[("5 min", 5), ("10 min", 10)])
        row.set_selected(10)
        self.assertTrue(row._buttons[10].bold)
        self.assertFalse(row._buttons[5].bold)
        self.assertEqual(list(row._buttons[10].bg_color), list(C.ACCENT))

    def test_set_selected_none_clears_all_when_none_not_a_key(self):
        row = PresetRow(items=[("5 min", 5), ("10 min", 10)])
        row.set_selected(10)
        row.set_selected(None)
        self.assertFalse(row._buttons[5].bold)
        self.assertFalse(row._buttons[10].bold)

    def test_set_selected_none_highlights_free_when_present(self):
        row = PresetRow(items=[("5 min", 5), ("Free", None)])
        row.set_selected(None)
        self.assertTrue(row._buttons[None].bold)
        self.assertFalse(row._buttons[5].bold)

    def test_set_selected_unknown_value_clears_all(self):
        row = PresetRow(items=[("5 min", 5), ("10 min", 10)])
        row.set_selected(10)
        row.set_selected(25)
        self.assertFalse(row._buttons[5].bold)
        self.assertFalse(row._buttons[10].bold)


if __name__ == "__main__":
    unittest.main()
