from app.storage.database import DatabaseManager
from app.ui.widgets.band_totals import (
    BANDS,
    GROUPS,
    band_rows,
    band_shares,
    format_power,
    grouped_totals,
)

_T = {"delta": 16.0, "theta": 12.0, "alpha1": 28.0, "alpha2": 17.0,
      "beta1": 8.0, "beta2": 4.0, "gamma1": 1.0, "gamma2": 2.0}


def test_groups_are_five_collapsed_bands():
    assert GROUPS == ["delta", "theta", "alpha", "beta", "gamma"]


def test_grouped_totals_sum_paired_subbands():
    g = grouped_totals(_T)
    assert set(g) == set(GROUPS)
    assert g["alpha"] == 45.0       # 28 + 17
    assert g["beta"] == 12.0        # 8 + 4
    assert g["gamma"] == 3.0        # 1 + 2
    assert g["delta"] == 16.0       # unchanged
    assert g["theta"] == 12.0


def test_band_rows_detailed_natural_order_is_frequency():
    rows = band_rows(_T, mode="detailed", sort_by="band", descending=False)
    assert [r["key"] for r in rows] == BANDS


def test_band_rows_grouped_natural_order():
    rows = band_rows(_T, mode="grouped", sort_by="band", descending=False)
    assert [r["key"] for r in rows] == GROUPS
    alpha = next(r for r in rows if r["key"] == "alpha")
    assert alpha["total"] == 45.0


def test_band_rows_sort_by_power_descending():
    rows = band_rows(_T, mode="detailed", sort_by="power", descending=True)
    totals = [r["total"] for r in rows]
    assert totals == sorted(totals, reverse=True)
    assert rows[0]["key"] == "alpha1"   # 28 is the largest


def test_band_rows_sort_by_percent_matches_power_order():
    by_power = [r["key"] for r in band_rows(_T, mode="detailed", sort_by="power", descending=True)]
    by_pct = [r["key"] for r in band_rows(_T, mode="detailed", sort_by="percent", descending=True)]
    assert by_power == by_pct


def test_band_rows_ascending_reverses():
    desc = band_rows(_T, mode="detailed", sort_by="power", descending=True)
    asc = band_rows(_T, mode="detailed", sort_by="power", descending=False)
    assert [r["key"] for r in asc] == [r["key"] for r in reversed(desc)]


def test_band_rows_shares_within_mode():
    rows = band_rows(_T, mode="grouped", sort_by="band", descending=False)
    assert abs(sum(r["share"] for r in rows) - 1.0) < 1e-9


def test_bands_are_the_eight_raw_subbands_low_to_high():
    assert BANDS == [
        "delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2",
    ]


def test_band_shares_normalize_to_fractions_of_total():
    totals = {"delta": 30.0, "theta": 10.0, "alpha1": 10.0, "alpha2": 0.0,
              "beta1": 0.0, "beta2": 0.0, "gamma1": 0.0, "gamma2": 0.0}
    shares = band_shares(totals)
    assert shares["delta"] == 0.6
    assert shares["theta"] == 0.2
    assert shares["alpha1"] == 0.2
    assert abs(sum(shares.values()) - 1.0) < 1e-9


def test_band_shares_zero_total_is_all_zero_no_div_by_zero():
    shares = band_shares(dict.fromkeys(BANDS, 0.0))
    assert all(v == 0.0 for v in shares.values())


def test_band_shares_missing_band_treated_as_zero():
    shares = band_shares({"delta": 100.0})
    assert shares["delta"] == 1.0
    assert shares["gamma2"] == 0.0
    assert set(shares) == set(BANDS)


def test_format_power_scales_to_k_and_m():
    assert format_power(0.0) == "0"
    assert format_power(830.0) == "830"
    assert format_power(12345.0) == "12.3K"
    assert format_power(4_210_000.0) == "4.21M"


def test_get_session_band_totals_sums_raw_bands(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    uid = db.create_user("a")
    sid = db.save_session({"duration": 10}, user_id=uid)
    db.save_metrics_batch(sid, [
        {"delta": 10, "theta": 1, "alpha1": 2, "alpha2": 3,
         "beta1": 4, "beta2": 5, "gamma1": 6, "gamma2": 7},
        {"delta": 20, "theta": 1, "alpha1": 2, "alpha2": 3,
         "beta1": 4, "beta2": 5, "gamma1": 6, "gamma2": 7},
    ])
    totals = db.get_session_band_totals(sid)
    assert set(totals) == set(BANDS)
    assert totals["delta"] == 30
    assert totals["theta"] == 2
    assert totals["gamma2"] == 14


def test_get_session_band_totals_empty_session_is_zeros(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    uid = db.create_user("a")
    sid = db.save_session({"duration": 0}, user_id=uid)
    totals = db.get_session_band_totals(sid)
    assert set(totals) == set(BANDS)
    assert all(v == 0.0 for v in totals.values())


def test_band_totals_view_detailed_default_shows_eight_bands():
    from app.ui.widgets.band_totals import BandTotalsView
    view = BandTotalsView()
    view.set_totals({"delta": 30.0, "theta": 10.0, "alpha1": 10.0, "alpha2": 0.0,
                     "beta1": 0.0, "beta2": 0.0, "gamma1": 0.0, "gamma2": 0.0})
    assert view.current_keys() == BANDS          # detailed, frequency order
    assert set(view._bars) == set(BANDS)
    assert view._bars["delta"].size_hint_x == 0.6
    assert "60%" in view._value_labels["delta"].text


def test_band_totals_view_zero_total_renders_without_error():
    from app.ui.widgets.band_totals import BandTotalsView
    view = BandTotalsView()
    view.set_totals(dict.fromkeys(BANDS, 0.0))
    assert view._bars["delta"].size_hint_x == 0.0
    assert "0%" in view._value_labels["delta"].text


def test_band_totals_view_grouped_mode_collapses_to_five():
    from app.ui.widgets.band_totals import BandTotalsView
    view = BandTotalsView()
    view.set_totals(_T)
    view.set_view_state("grouped", "band", False)
    assert view.current_keys() == GROUPS
    assert set(view._bars) == set(GROUPS)
    # alpha bar = (alpha1+alpha2)/grand = 45/88
    assert abs(view._bars["alpha"].size_hint_x - 45.0 / sum(_T.values())) < 1e-9


def test_band_totals_view_sort_by_power_reorders_and_emits():
    from app.ui.widgets.band_totals import BandTotalsView
    seen = []
    view = BandTotalsView(on_change=lambda m, s, d: seen.append((m, s, d)))
    view.set_totals(_T)
    view._toggle_sort("power")
    assert view.current_keys()[0] == "alpha1"      # largest first
    assert seen[-1] == ("detailed", "power", True)
    # tapping again reverses
    view._toggle_sort("power")
    assert view.current_keys()[0] == "gamma1"      # smallest (1.0) first
    assert seen[-1] == ("detailed", "power", False)
