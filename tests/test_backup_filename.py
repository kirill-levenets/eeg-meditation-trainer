"""The suggested backup name must identify the profile and time, and be a valid filename on phone storage."""

from datetime import datetime

import pytest

from app.storage.backup import backup_filename

NOW = datetime(2026, 9, 29, 17, 49, 5)


@pytest.mark.parametrize(("user", "expected"), [
    ("carl", "eeg_backup_carl_2026-09-29_17-49.db"),
    ("Кирило", "eeg_backup_Кирило_2026-09-29_17-49.db"),
    ("Anna Maria", "eeg_backup_Anna_Maria_2026-09-29_17-49.db"),
    ('a/b\\c:d*e?f"g<h>i|j', "eeg_backup_a_b_c_d_e_f_g_h_i_j_2026-09-29_17-49.db"),
    ("..hidden.", "eeg_backup_hidden_2026-09-29_17-49.db"),
    ("a\x00b\x1fc", "eeg_backup_a_b_c_2026-09-29_17-49.db"),
])
def test_name_carries_profile_and_time(user, expected):
    assert backup_filename(user, NOW) == expected


def test_long_name_stays_far_below_the_filename_byte_limit():
    name = backup_filename("Ж" * 300, NOW)
    assert name.startswith("eeg_backup_" + "Ж" * 40 + "_")
    assert len(name.encode("utf-8")) < 255


@pytest.mark.parametrize("user", [None, "", "  ", "///", "..."])
def test_no_usable_profile_name_leaves_just_the_time(user):
    assert backup_filename(user, NOW) == "eeg_backup_2026-09-29_17-49.db"
