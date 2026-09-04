"""A dead token on a liveactivity push is a dead ACTIVITY, never a dead
device. Production 2026-09-04 01:49 UTC: one BadDeviceToken on one activity
disabled the phone, and every card on it froze mid-match."""
from app.services.apns import ApnsResult


def test_liveactivity_bad_token_ends_the_activity_only():
    for reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic",
                   "ExpiredToken", "ExpiredActivityToken"):
        r = ApnsResult(ok=False, status=400, reason=reason, push_type="liveactivity")
        assert r.activity_is_over is True, reason
        assert r.token_is_dead is False, reason


def test_alert_bad_token_kills_the_device():
    for reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
        r = ApnsResult(ok=False, status=400, reason=reason, push_type="alert")
        assert r.token_is_dead is True, reason
        assert r.activity_is_over is False, reason


def test_other_failures_touch_nothing():
    for reason in ("TooManyRequests", "connection_failed", "blocked", None):
        for pt in ("alert", "liveactivity"):
            r = ApnsResult(ok=False, reason=reason, push_type=pt)
            assert r.token_is_dead is False
            assert r.activity_is_over is False


def test_unstamped_result_is_treated_as_alert():
    # A result built without push_type (a future caller forgetting send())
    # keeps the old, conservative semantics rather than silently passing.
    r = ApnsResult(ok=False, reason="BadDeviceToken")
    assert r.token_is_dead is True and r.activity_is_over is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
