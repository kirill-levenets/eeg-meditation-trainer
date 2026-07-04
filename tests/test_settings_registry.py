"""Registry engine: load always fills defaults (no cross-user leak), save serializes,
persist is a single-key write suppressed during load."""
from app.settings.registry import BOOL, FLOAT, INT, STR, Setting, SettingsStore


class _FakeDB:
    def __init__(self, values=None):
        self.store = dict(values or {})   # (uid, key) -> raw str
        self.writes = []

    def get_user_setting(self, uid, key):
        return self.store.get((uid, key))

    def set_user_setting(self, uid, key, value):
        self.store[(uid, key)] = value
        self.writes.append((uid, key, value))


def _cell(initial):
    box = {"v": initial}
    return box, (lambda: box["v"]), (lambda v: box.__setitem__("v", v))


def _store(db, settings):
    return SettingsStore(db, settings)


def test_load_fills_default_when_absent():
    box, get, set_ = _cell("STALE")
    s = Setting("threshold", 80, INT[0], INT[1], get, set_)
    st = _store(_FakeDB(), [s])
    st.load(uid=1)
    assert box["v"] == 80          # default applied, not the stale in-memory value


def test_load_parses_present_value():
    box, get, set_ = _cell(0)
    s = Setting("threshold", 80, INT[0], INT[1], get, set_)
    st = _store(_FakeDB({(1, "threshold"): "120"}), [s])
    st.load(1)
    assert box["v"] == 120


def test_load_bad_value_falls_back_to_default():
    box, get, set_ = _cell(0)
    s = Setting("threshold", 80, INT[0], INT[1], get, set_)
    st = _store(_FakeDB({(1, "threshold"): "not-an-int"}), [s])
    st.load(1)
    assert box["v"] == 80


def test_load_isolates_users_no_leak():
    box, get, set_ = _cell(None)
    s = Setting("feedback_source", "noise", STR[0], STR[1], get, set_)
    db = _FakeDB({(1, "feedback_source"): "tone"})
    st = _store(db, [s])
    st.load(1)
    assert box["v"] == "tone"      # user 1 has it
    st.load(2)
    assert box["v"] == "noise"     # user 2 absent -> default, NOT user 1's "tone"


def test_save_serializes_all():
    _, get, set_ = _cell(True)
    s = Setting("sinking_alert", False, BOOL[0], BOOL[1], get, set_)
    db = _FakeDB()
    _store(db, [s]).save(7)
    assert db.get_user_setting(7, "sinking_alert") == "True"


def test_persist_writes_single_key():
    box, get, set_ = _cell(1.5)
    s = Setting("line_width", 1.2, FLOAT[0], FLOAT[1], get, set_)
    db = _FakeDB()
    _store(db, [s]).persist(3, "line_width")
    assert db.get_user_setting(3, "line_width") == "1.5"


def test_persist_suppressed_during_load():
    # A load applies values, which fire change callbacks that call persist(); those
    # re-writes must be suppressed so load doesn't thrash the DB with what it just read.
    box, get, set_ = _cell(0)
    db = _FakeDB({(1, "threshold"): "120"})

    def apply(v):
        box["v"] = v
        st.persist(1, "threshold")   # simulate change callback firing during load

    s = Setting("threshold", 80, INT[0], INT[1], get, apply)
    st = _store(db, [s])
    st.load(1)
    assert db.writes == []           # persist no-op'd while loading
    assert box["v"] == 120


def test_persist_noop_without_user():
    _, get, set_ = _cell(5)
    s = Setting("threshold", 80, INT[0], INT[1], get, set_)
    db = _FakeDB()
    _store(db, [s]).persist(None, "threshold")
    assert db.writes == []
