"""Which draw-release email a draw belongs to.

The never-split rule (one email per bucket, and it waits for every draw in
that bucket however long that takes) is only as good as the agreement between
two things: how the ready draws are GROUPED, and which siblings a group WAITS
on. `release_bucket` is the single answer to both, so these tests are about
bucket membership rather than about the dispatcher's plumbing.
"""
from types import SimpleNamespace as NS

from app.services.scheduler import TOUR_SPLIT_WEEKS, release_bucket


def draw(id, year=2026, week=30, gender="F"):
    return NS(id=id, year=year, week=week, gender=gender)


def test_a_normal_week_is_one_bucket_for_both_tours():
    wta = draw(1, week=30, gender="F")
    atp = draw(2, week=30, gender="M")
    assert release_bucket(wta) == release_bucket(atp)
    # …and a different week is a different bucket.
    assert release_bucket(draw(3, week=31)) != release_bucket(wta)
    # …as is the same week of a different year.
    assert release_bucket(draw(4, year=2025, week=30)) != release_bucket(wta)


def test_the_exempt_week_splits_by_tour_and_nothing_else():
    """Week 38 of 2026: the WTA draws start Monday and the ATP 250s start
    Wednesday, around the Laver Cup, so they are two emails (owner,
    2026-09-19)."""
    korea = draw(146, week=38, gender="F")
    singapore = draw(144, week=38, gender="F")
    chengdu = draw(145, week=38, gender="M")
    hangzhou = draw(122, week=38, gender="M")

    # Each tour buckets together…
    assert release_bucket(korea) == release_bucket(singapore)
    assert release_bucket(chengdu) == release_bucket(hangzhou)
    # …and the two tours do not.
    assert release_bucket(korea) != release_bucket(chengdu)


def test_the_exemption_is_scoped_to_the_week_it_was_granted_for():
    """A one-off stays one-off. This pins the set deliberately: widening it is
    a per-case decision that needs the owner's word, because every extra week
    here is another week that gets two emails instead of one."""
    assert TOUR_SPLIT_WEEKS == {(2026, 38)}, (
        "TOUR_SPLIT_WEEKS grew. Each entry splits that week's draw-release "
        "digest by tour; confirm it was asked for before updating this test."
    )
    # The week either side of it is untouched.
    assert release_bucket(draw(1, week=37, gender="F")) == release_bucket(draw(2, week=37, gender="M"))
    assert release_bucket(draw(3, week=39, gender="F")) == release_bucket(draw(4, week=39, gender="M"))


def test_a_draw_with_no_week_goes_out_alone():
    # It can be batched with nothing, so it must not be held for a group it is
    # not part of — and two of them are still separate buckets.
    a, b = draw(7, week=None), draw(8, week=None)
    assert release_bucket(a) == ("solo", 7)
    assert release_bucket(a) != release_bucket(b)


# ── The copy each half of a split week carries ───────────────────────────────
# Without a tour in the subject and heading, both emails for one week announce
# themselves as "this week's draws" and the second reads as a correction of
# the first. Captured through the real send function with the transport stubbed.

import app.services.email as email_mod   # noqa: E402  (after the module docstring)


def _capture(monkeypatch):
    sent = {}

    async def fake_send(params, *, unsubscribe_url="", unsubscribe_label=""):
        # Captured through _finalise, not around it: the footer and the
        # List-Unsubscribe headers are added there, so anything asserting on
        # "what was sent" should see the message as a provider would.
        sent.update(email_mod._finalise(params, unsubscribe_url, unsubscribe_label))
        return None

    # send_draw_release_digest builds the params and hands them to send_async.
    monkeypatch.setattr(email_mod, "send_async", fake_send)
    return sent


def _rows(n, name="Korea Open"):
    return [{"id": i, "name": f"{name} {i}" if n > 1 else name, "gender": "F",
             "tier": "WTA 250", "location": "Seoul", "surface": "Hard",
             "draw_size": 32, "closing_time": None, "closes": None,
             "closes_soon": False}
            for i in range(n)]


def test_a_split_weeks_email_names_its_tour(monkeypatch):
    import asyncio
    sent = _capture(monkeypatch)
    asyncio.run(email_mod.send_draw_release_digest(
        "a@b.c", _rows(2), "September 21", tour="F"))
    assert "WTA draws are live" in sent["subject"] or "WTA" in sent["subject"]
    assert "WTA" in sent["html"]

    sent.clear()
    asyncio.run(email_mod.send_draw_release_digest(
        "a@b.c", _rows(2), "September 23", tour="M"))
    assert "ATP" in sent["subject"]


def test_an_ordinary_week_carries_no_qualifier(monkeypatch):
    """The digest IS the week on a normal week, so naming a tour there would
    be noise — and would change copy nobody asked to change."""
    import asyncio
    sent = _capture(monkeypatch)
    asyncio.run(email_mod.send_draw_release_digest(
        "a@b.c", _rows(2), "September 21"))
    assert "WTA" not in sent["subject"] and "ATP" not in sent["subject"]
    assert "2 draws are live" in sent["subject"]
