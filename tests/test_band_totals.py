from app.storage.database import DatabaseManager
from app.ui.widgets.band_totals import BANDS, band_shares, format_power


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


def test_band_totals_view_builds_eight_rows_with_values():
    from app.ui.widgets.band_totals import BandTotalsView
    view = BandTotalsView()
    view.set_totals({"delta": 30.0, "theta": 10.0, "alpha1": 10.0, "alpha2": 0.0,
                     "beta1": 0.0, "beta2": 0.0, "gamma1": 0.0, "gamma2": 0.0})
    assert set(view._value_labels) == set(BANDS)
    assert set(view._bars) == set(BANDS)
    assert view._bars["delta"].size_hint_x == 0.6
    assert "30" in view._value_labels["delta"].text
    assert "60%" in view._value_labels["delta"].text


def test_band_totals_view_zero_total_renders_without_error():
    from app.ui.widgets.band_totals import BandTotalsView
    view = BandTotalsView()
    view.set_totals(dict.fromkeys(BANDS, 0.0))
    assert view._bars["delta"].size_hint_x == 0.0
    assert "0%" in view._value_labels["delta"].text
