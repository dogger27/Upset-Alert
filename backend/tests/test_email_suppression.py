"""An address that bounced or reported spam is not written to again.

Resend's log for Aug–Sep 2026: one address hard-bounced six times (verify,
welcome, four digests) and a reader who pressed Report spam was sent two more
digests. Each repeat is scored against upsetalert.ca, and the domain's score
is what decides whether everyone ELSE's mail lands in the inbox.
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base                                  # noqa: E402
from app.models.notification import EmailSuppression           # noqa: E402
from app.services import email_suppression as S                # noqa: E402


def _with_db(rows):
    async def go():
        eng = create_async_engine("sqlite+aiosqlite://")
        async with eng.begin() as c:
            await c.run_sync(lambda sc: EmailSuppression.__table__.create(sc))
        maker = async_sessionmaker(eng, expire_on_commit=False)
        async with maker() as db:
            for email, reason in rows:
                db.add(EmailSuppression(email=email, reason=reason))
            await db.commit()
        S.AsyncSessionLocal = maker
        return eng
    return asyncio.run(go())


ROWS = [("gone@x.ca", "bounced"), ("angry@aol.com", "complained"),
        ("listed@y.ca", "suppressed")]
TO = ["Gone@X.ca", "angry@aol.com", "listed@y.ca", "fine@z.ca"]


def test_digest_skips_every_suppressed_address():
    _with_db(ROWS)
    assert asyncio.run(S.allowed(TO, essential=False)) == ["fine@z.ca"]


def test_code_the_reader_asked_for_still_reaches_a_complainer():
    # A password reset is requested this minute by the person reading it; only
    # an address that cannot receive mail at all stops it.
    _with_db(ROWS)
    assert asyncio.run(S.allowed(TO, essential=True)) == \
        ["angry@aol.com", "listed@y.ca", "fine@z.ca"]


def test_resend_timestamp_parses():
    assert S._parse("2026-09-21 10:31:05.123+00").tzinfo is not None
    assert S._parse(None) is None


def test_verification_and_reset_are_the_essential_ones():
    src = (BACKEND / "app" / "services" / "email.py").read_text()
    for fn in ("send_verification", "send_password_reset"):
        i = src.index(f"async def {fn}(")
        body = src[i:src.index("\nasync def ", i + 10)]
        assert "essential=True" in body, fn
    assert src.count("essential=True") == 2


def test_invitation_opt_out_stops_only_invitations():
    _with_db([("stranger@x.ca", S.INVITES)])
    assert asyncio.run(S.allowed(["stranger@x.ca"], False, S.INVITES)) == []
    # The same person may sign up later; their digests must still arrive.
    assert asyncio.run(S.allowed(["stranger@x.ca"], False)) == ["stranger@x.ca"]


def test_opt_out_never_weakens_a_bounce():
    _with_db([("gone@x.ca", "bounced")])
    asyncio.run(S.opt_out_address("gone@x.ca", S.INVITES))
    assert asyncio.run(S.allowed(["gone@x.ca"], True)) == []


def test_address_token_round_trips_and_is_not_an_account_token():
    from app.core.security import (create_email_unsubscribe_token,
                                   verify_email_unsubscribe_token,
                                   verify_unsubscribe_token)
    t = create_email_unsubscribe_token("A@B.ca", S.INVITES)
    assert verify_email_unsubscribe_token(t) == ("a@b.ca", S.INVITES)
    assert verify_unsubscribe_token(t) is None


def test_every_mail_a_reader_did_not_ask_for_has_a_way_out():
    """Only the sends a reader triggered themselves (verify, reset, welcome)
    or that go to the owner may omit unsubscribe."""
    import ast
    src = (BACKEND / "app" / "services" / "email.py").read_text()
    exempt = {"send_verification", "send_password_reset", "send_welcome",
              "send_new_user_notification", "send_oop_status"}
    for fn in ast.parse(src).body:
        if not isinstance(fn, ast.AsyncFunctionDef) or fn.name in exempt:
            continue
        seg = ast.get_source_segment(src, fn)
        if "send_async(" in seg:
            assert "unsubscribe_url" in seg, f"{fn.name} has no unsubscribe"
