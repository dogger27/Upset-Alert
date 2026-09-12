"""Which notification types a new account is enrolled on.

Two things have to stay true at once, and they pull in opposite directions:
every key stays OFFERED (or the settings screen loses its toggle and nobody
can turn it back on), while the default-off ones are never ENROLLED (or the
boot pass hands them back to everyone on the next restart).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.notification_keys import (          # noqa: E402
    ALL_EMAIL_KEYS, ALL_KEYS, DEFAULT_OFF_EMAIL_KEYS, DEFAULT_ON_KEYS, push_key,
)


def test_the_default_off_keys_are_offered_but_not_enrolled():
    for key in DEFAULT_OFF_EMAIL_KEYS:
        # Offered: it is a real key, so the settings screen shows it unticked
        # and a tick re-enables it for good.
        assert key in ALL_EMAIL_KEYS
        assert key in ALL_KEYS
        # Not enrolled: neither a new account nor the boot pass hands it out.
        assert key not in DEFAULT_ON_KEYS


def test_push_is_untouched_by_an_email_default():
    """Push costs no quota, so switching an EMAIL type off by default must not
    take its push twin with it — the Final's push is the one people want."""
    for key in DEFAULT_OFF_EMAIL_KEYS:
        assert push_key(key) in DEFAULT_ON_KEYS


def test_everything_else_is_still_on_by_default():
    expected = [k for k in ALL_KEYS if k not in DEFAULT_OFF_EMAIL_KEYS]
    assert list(DEFAULT_ON_KEYS) == expected
    assert "draw_released" in DEFAULT_ON_KEYS


def test_the_boot_enrolment_hands_out_the_default_set_only():
    """The generated SQL is what actually decides this on every restart."""
    from app.database import _enrol_all_notifications_sql
    sql = _enrol_all_notifications_sql()
    for key in DEFAULT_OFF_EMAIL_KEYS:
        assert f"'{key}'" not in sql, f"{key} would be re-enrolled on boot"
        assert f"'{push_key(key)}'" in sql
    assert "notification_opt_outs" in sql, "the refusal guard must stay"


def test_a_new_account_starts_on_the_default_set():
    from app.routers.auth import _DEFAULT_NOTIF_PREFS
    assert set(_DEFAULT_NOTIF_PREFS) == set(DEFAULT_ON_KEYS)
