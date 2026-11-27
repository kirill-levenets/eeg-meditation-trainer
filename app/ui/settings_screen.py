"""The Settings screen: its folds in order, each a section in settings_sections/ that builds its own content and
reports the user's actions through its hooks."""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from app.ui.settings_sections.audio import AudioSection
from app.ui.settings_sections.backup import BackupSection
from app.ui.settings_sections.developer import DeveloperSection
from app.ui.settings_sections.device import DeviceSection
from app.ui.settings_sections.display import DisplaySection
from app.ui.settings_sections.formulas import FormulaSection
from app.ui.settings_sections.help import HelpSection
from app.ui.settings_sections.profile import ProfileSection
from app.ui.settings_sections.theme_choice import ThemeSection
from app.ui.settings_sections.threshold import MetricPicker, ThresholdSlider
from app.ui.settings_sections.timer import TimerSection
from app.ui.theme import C, fill_background
from app.ui.widgets.accordion import ThemedAccordion


class SettingsScreen(Screen):
    """The folds, each its section; Threshold holds two, the slider and the sound's metric, which two owners use."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
        root = BoxLayout(orientation="vertical")
        fill_background(root, C.BG)
        self._settings_scroll = ScrollView()
        self._accordion = ThemedAccordion()
        fold = self._accordion.add_section
        self.profile = ProfileSection(fold("User Profile", collapsed=False))
        self.timer = TimerSection(fold("Timer / Program"), saved_formulas=lambda: self.formulas.saved)
        self.device = DeviceSection(fold("Device"), scroll=self._settings_scroll)
        self.backup = BackupSection(fold("Data Backup"))
        threshold = fold("Threshold")
        self.threshold = ThresholdSlider(threshold)
        self.metric = MetricPicker(threshold)
        self.audio = AudioSection(fold("Audio"))
        self.display = DisplaySection(fold("Display"))
        self.formulas = FormulaSection(fold("Custom Formula"))
        self.theme = ThemeSection(fold("Theme"))
        DeveloperSection(fold("Developer Tools"))
        HelpSection(fold("Help & Troubleshooting"))
        self._settings_scroll.add_widget(self._accordion)
        root.add_widget(self._settings_scroll)
        self.add_widget(root)

    def on_pre_enter(self, *args) -> None:
        # The link may have dropped between sessions, with nothing on screen to report it.
        self.device.mark_bt_devices()
        self.profile.refresh_counts()  # sessions saved or deleted since the list was drawn
