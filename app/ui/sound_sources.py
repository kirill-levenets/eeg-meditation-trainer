"""Which sounds a session and the Settings tests play: the feedback (below the threshold) and reward sources the settings
hold, a program's per-segment sources, the timer's gong, and one warning for the sound files that are missing."""
import os

from app.crash_handler import report_soft_error
from app.logger import logger
from app.ui.app_context import AppContext
from app.ui.theme import format_count

BUILTIN_SOURCES = ("noise", "tone", "heartbeat")


def source_spec(source_id: str) -> tuple[str, str]:
    """A source id as (kind, custom path): a built-in, a custom file's path, or "" / "none", the silent sentinel no
    player is made for."""
    if source_id in ("", "none"):
        return "none", ""
    if source_id in BUILTIN_SOURCES:
        return source_id, ""
    return "custom", source_id


def feedback_plan(program, global_id: str) -> tuple[dict, list[str], str]:
    """(distinct sources, per-segment ids, initial id) for a program; a segment with no sound of its own inherits the
    global source."""
    seg_ids = [s.get("feedback_sound", "") or global_id for s in program.segments]
    sources = {sid: source_spec(sid) for sid in [global_id, *seg_ids]}
    return sources, seg_ids, seg_ids[0] if seg_ids else global_id


def missing_sound_problems(sources: dict, timer_path: str = "") -> list[str]:
    """What the user is told about the custom files in `sources` and the timer's gong that aren't there."""
    problems = []
    missing = [path for kind, path in sources.values() if kind == "custom" and not (path and os.path.isfile(path))]
    if missing:
        problems.append(f"{format_count(len(missing), 'custom feedback file')} not found: "
                        + ", ".join(repr(p) for p in missing) + " - using rain noise instead.")
    if timer_path and not os.path.isfile(timer_path):
        problems.append(f"Custom timer sound not found: {timer_path!r} - using the default gong instead.")
    return problems


class SoundSources:
    """The sources as the settings hold them, resolved for a session's start and the Settings tests; a source chosen in
    Settings changes through the app's settings path."""

    def __init__(self, ctx: AppContext, audio, timer_state, timer_section) -> None:
        self._ctx = ctx
        self._audio = audio
        self._timer_state = timer_state
        self._timer_section = timer_section

    def global_feedback_id(self) -> str:
        """The feedback source; a custom one with no file falls back to the rain noise."""
        src = self._ctx.setting("feedback_source")
        if src in ("", "none"):
            return "none"
        if src == "custom":
            return self._ctx.setting("feedback_sound_path") or "noise"
        return src

    def reward_id(self) -> str:
        """The above-threshold reward source ("" = none); a custom one with no file is silent, not the rain noise."""
        src = self._ctx.setting("reward_source")
        if src in ("", "none"):
            return ""
        if src == "custom":
            return self._ctx.setting("reward_sound_path") or ""
        return src

    def prepare_session(self, program) -> list[str]:
        """The session's players: its feedback (a program's per-segment sources) and the reward channel, a missing file
        warned about; a program's per-segment source ids, for its run."""
        gid = self.global_feedback_id()
        if program:
            sources, seg_ids, initial = feedback_plan(program, gid)
        else:
            sources, seg_ids, initial = {gid: source_spec(gid)}, [], gid
        reward = self.reward_id()
        if reward:
            sources[reward] = source_spec(reward)
        timer = self._timer_state
        self.warn_missing(sources, timer.custom_sound_path if timer.enabled else "")
        self._audio.prepare_feedback(sources, initial)
        self._audio.set_reward(reward)
        return seg_ids

    def test_sources(self) -> tuple[dict, str, str]:
        """(sources, feedback id, reward id) for Settings' Test: the feedback and the reward source, so both preview."""
        gid = self.global_feedback_id()
        sources = {gid: source_spec(gid)}
        reward = self.reward_id()
        if reward:
            sources[reward] = source_spec(reward)
        return sources, gid, reward

    def warn_missing(self, sources: dict, timer_path: str = "", *, force: bool = False) -> None:
        """One report for the missing files; `force` for a check the user asked for (a Test button)."""
        problems = missing_sound_problems(sources, timer_path)
        if problems:
            report_soft_error("sound_files_missing", "\n".join(problems), force=force)

    def on_test_audio(self) -> None:
        """Sample the feedback and reward sources, then the alert channels."""
        if self._ctx.session.refused("testing the audio", why="The test plays through the session's sounds."):
            return
        sources, gid, reward = self.test_sources()
        self.warn_missing(sources, force=True)
        self._audio.prepare_feedback(sources, gid)
        self._audio.test_audio(reward)

    def on_feedback_source_change(self, source: str, path: str) -> None:
        """The feedback source chosen in Settings; its path first, so the source shows with it."""
        self._ctx.change_setting("feedback_sound_path", (path or "").strip())
        self._ctx.change_setting("feedback_source", source)
        logger.info(f"Feedback source -> {source} {self._ctx.setting('feedback_sound_path')!r}")

    def on_reward_source_change(self, source: str, path: str) -> None:
        """The reward source chosen in Settings; its path first, so the source shows with it."""
        self._ctx.change_setting("reward_sound_path", (path or "").strip())
        self._ctx.change_setting("reward_source", source)
        logger.info(f"Reward source -> {source} {self._ctx.setting('reward_sound_path')!r}")

    def on_timer_sound_change(self, path: str) -> None:
        """The custom timer-gong path ("" for the default bell), persisted once typing settles."""
        self._ctx.change_setting("timer_sound", path)

    def on_test_timer_sound(self) -> None:
        path = self._timer_state.custom_sound_path
        logger.debug(f"Test timer sound, path='{path}'")
        self.warn_missing({}, path, force=True)
        # The gong's end flips the Test button back from Stop (the engine calls it on Kivy's thread).
        played = self._audio.play_timer_sound(path, on_end=self._timer_section.notify_timer_sound_test_ended)
        if not played:
            report_soft_error("timer_sound_unplayable", "The timer sound can't be played.", force=True)
        elif path and played != path and os.path.isfile(path):
            report_soft_error("timer_sound_unplayable",
                              f"Custom timer sound can't be played: {path!r} - using the default gong instead.",
                              force=True)

    def on_stop_test_timer_sound(self) -> None:
        logger.debug("Stop timer test sound")
        self._audio.stop_timer_bell()
