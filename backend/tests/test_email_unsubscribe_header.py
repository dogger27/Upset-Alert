"""The way out of a digest, and why it is a deliverability fix.

A mail-tester run on 2026-09-21 scored the welcome email 9/10 — SPF, DKIM and
DMARC all passing, not on a blocklist, nowhere near the spam threshold — and
objected to exactly one thing: "Your message does not contain a
List-Unsubscribe header."

That header is not cosmetic. Without it the only control a reader has from
the inbox list is Report Spam, and Gmail, Yahoo and AOL read each of those as
a verdict on upsetalert.ca rather than on one digest. At under a hundred sends
a day a handful is enough to route everyone's mail to spam — including the
verification email a new account needs to get in at all. It is the mechanism
behind "some users say upset alert emails go their spam" (owner, 2026-09-21).

So these are the four things that have to stay true:

  1. every message carries the footer, once;
  2. a subscription message carries both RFC 8058 headers;
  3. the -Post header is only ever a promise the API actually keeps;
  4. the label in the footer matches the one the landing page says back.
"""
import ast
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import email as E                       # noqa: E402

EMAIL_SRC = (BACKEND / "app" / "services" / "email.py").read_text(encoding="utf-8")
MAIN_SRC = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")

URL = "https://upsetalert-api.upsetalert.ca/unsubscribe?token=abc.def.ghi"
BODY = {"from": E.FROM, "to": ["a@b.ca"], "subject": "s", "html": "<p>hi</p>"}


# ── 1. the footer ─────────────────────────────────────────────────────────

def test_every_message_gets_the_footer():
    out = E._finalise(BODY)
    assert E._FOOTER_MARK in out["html"]
    assert "upsetalert.ca" in out["html"]
    # Identity, so a reader knows why it arrived and does not reach for Report
    # Spam to find out.
    assert "receiving this because you have an account" in out["html"]


def test_the_footer_is_not_appended_twice():
    once = E._finalise(BODY)
    twice = E._finalise(once)
    assert twice["html"].count(E._FOOTER_MARK) == 1
    assert once["html"] == twice["html"]


def test_the_way_out_is_named_in_the_body_too():
    """Some clients show no unsubscribe control at all; the link is the
    fallback, and it has to say WHICH emails it stops."""
    out = E._finalise(BODY, URL, "draw-change emails")
    assert URL in out["html"]
    assert "Unsubscribe from draw-change emails" in out["html"]


def test_a_message_nobody_subscribed_to_offers_no_unsubscribe():
    """A password reset has no preference to drop. Offering a link that
    unsubscribes from nothing is worse than offering none."""
    out = E._finalise(BODY)
    assert "Unsubscribe" not in out["html"]
    assert "List-Unsubscribe" not in (out.get("headers") or {})


# ── 2. the headers ────────────────────────────────────────────────────────

def test_a_subscription_message_carries_both_rfc_8058_headers():
    h = E._finalise(BODY, URL, "draw-release emails")["headers"]
    # Angle brackets are not decoration: RFC 2369 defines the value as a URL
    # in <>, and providers that parse strictly ignore a bare one.
    assert h["List-Unsubscribe"] == f"<{URL}>"
    assert h["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_headers_a_caller_already_set_survive():
    out = E._finalise({**BODY, "headers": {"X-Entity-Ref-ID": "7"}}, URL, "x")
    assert out["headers"]["X-Entity-Ref-ID"] == "7"
    assert "List-Unsubscribe" in out["headers"]


def test_nothing_else_in_the_payload_is_disturbed():
    out = E._finalise(BODY, URL, "x")
    assert {k: out[k] for k in ("from", "to", "subject")} == \
           {k: BODY[k] for k in ("from", "to", "subject")}
    assert BODY == {"from": E.FROM, "to": ["a@b.ca"], "subject": "s", "html": "<p>hi</p>"}


# ── 3. the promise the header makes ───────────────────────────────────────

def test_one_click_is_a_promise_the_api_keeps():
    """List-Unsubscribe-Post tells a provider the URL answers a POST and opts
    the reader out with no confirmation step. A provider that tries it and
    gets a 405 has been told the sender lies — which costs exactly the
    reputation the header was added to protect. So the route must exist."""
    assert 'List-Unsubscribe-Post' in EMAIL_SRC
    assert re.search(r'@app\.post\(\s*["\']/unsubscribe["\']', MAIN_SRC), \
        "email.py promises one-click unsubscribe but main.py has no POST /unsubscribe"


def test_both_methods_do_the_same_thing():
    """A link that opts out and a one-click that does not is the worst of the
    two failures, because only the reader can see it."""
    tree = ast.parse(MAIN_SRC)
    callers = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        routes = [d for d in node.decorator_list
                  if isinstance(d, ast.Call) and d.args
                  and isinstance(d.args[0], ast.Constant) and d.args[0].value == "/unsubscribe"]
        if routes:
            callers[node.name] = {n.func.id for n in ast.walk(node)
                                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert len(callers) == 2, f"expected a GET and a POST handler, found {sorted(callers)}"
    for name, called in callers.items():
        assert "_apply_unsubscribe" in called, f"{name} does not go through _apply_unsubscribe"


# ── 4. the digests, and the words they use ────────────────────────────────

def _senders_taking_an_unsubscribe_url():
    tree = ast.parse(EMAIL_SRC)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # send_async is the callee, not a caller: it takes the keywords and
        # applies them.
        if node.name.startswith("_") or node.name == "send_async":
            continue
        names = [a.arg for a in node.args.args + node.args.kwonlyargs]
        if "unsubscribe_url" in names:
            yield node


def test_every_digest_hands_its_url_to_send_async():
    """The footer moved into send_async so that nothing can be added without
    it. This is the other half: a digest that takes an unsubscribe_url and
    never passes it on renders no way out and sends no header, silently."""
    found = 0
    for fn in _senders_taking_an_unsubscribe_url():
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "send_async"]
        assert calls, f"{fn.name} takes an unsubscribe_url but sends nothing"
        for c in calls:
            kw = {k.arg for k in c.keywords}
            assert "unsubscribe_url" in kw, \
                f"{fn.name} drops its unsubscribe_url on the floor"
            assert "unsubscribe_label" in kw, \
                f"{fn.name} sends no label, so the footer reads 'these emails'"
        found += 1
    # Five since the standout-pick digest was removed (2026-09-26).
    assert found >= 5, f"only {found} digests found; the scan is not seeing them"


def test_the_footer_and_the_landing_page_say_the_same_words():
    """The footer's label is a literal in email.py; the page the link lands on
    reads its own from main.py's _UNSUB_PREF_LABELS. Two sources, one
    sentence — "Unsubscribe from qualifier emails" has to land on "You have
    been unsubscribed from qualifier emails", not from "the selected email
    type"."""
    from app.main import _UNSUB_PREF_LABELS
    page = set(_UNSUB_PREF_LABELS.values())
    used = set(re.findall(r'unsubscribe_label="([^"]+)"', EMAIL_SRC))
    assert used, "no literal labels found; has the keyword been renamed?"
    missing = used - page
    assert not missing, f"labels no unsubscribe page can name: {sorted(missing)}"
