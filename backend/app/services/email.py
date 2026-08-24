import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
import re as _re
from typing import Optional

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

FROM = "Upset Alert <info@upsetalert.ca>"
BASE_URL = "https://upsetalert.ca"
API_BASE = "https://upsetalert-api.upsetalert.ca"

_LOGO_HEADER = """<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#1b4332" style="background:#1b4332">
  <tr>
    <td align="center" bgcolor="#1b4332" style="background:#1b4332;padding:28px 24px 16px">
      <table cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto">
        <tr>
          <td width="72" height="72" bgcolor="#3d5538" style="background:#3d5538;border-radius:36px;width:72px;height:72px" align="center" valign="middle">
            <table cellpadding="0" cellspacing="0" border="0" align="center">
              <tr>
                <td width="43" height="43" bgcolor="#c9783a" style="background:#c9783a;border-radius:22px;width:43px;height:43px;font-size:0;line-height:0">&nbsp;</td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""

# background + color are set EXPLICITLY on the card and body: without them the
# card inherited whatever the client painted behind it, so every dark-mode
# inbox (and any dark-background preview) rendered our #111 text on near-black.
_WRAP_OPEN  = ('<div style="font-family:sans-serif;max-width:560px;margin:0 auto;border-radius:8px;'
               'overflow:hidden;border:1px solid #e5e7eb;background:#ffffff;color:#111111">')
_WRAP_CLOSE = '</div>'
_BODY_OPEN  = '<div style="padding:28px 24px;background:#ffffff;color:#111111">'
_BODY_CLOSE = '</div>'


def _tournament_label(tournament_name: str, category: str, gender: str) -> str:
    """Return 'Wimbledon ATP' for GS or 'Canadian Open ATP1000' for tour events.

    The tour, never the gender. Slams used to read 'Wimbledon Men' — the only
    label in the app that named the draw any other way, and the reason the two
    halves of a combined event did not line up beside each other.
    """
    cat = (category or "").upper()
    tour = "ATP" if gender == "M" else "WTA"
    if "SLAM" in cat or "GRAND" in cat:
        return f"{tournament_name} {tour}"
    tier = "1000" if "1000" in cat else "500" if "500" in cat else "250"
    return f"{tournament_name} {tour}{tier}"


# Tour ink for the trailing "ATP1000" / "WTA 250" / "ATP" in a draw label.
# Two per tour because the same label is drawn in two places: dark ink on the
# white summary table, and a light tint on the green section banner, where the
# dark blue would be 1.65:1 and effectively black.
_TOUR_INK = {
    "ATP": {"light_bg": "#1d4ed8", "dark_bg": "#93b8ff"},
    "WTA": {"light_bg": "#be185d", "dark_bg": "#ffb3c6"},
}
_TOUR_SUFFIX_RE = _re.compile(r"(ATP|WTA)\s?(\d{3,4})?$")


def _tour_coloured(label: str, on_dark: bool = False) -> str:
    """'Cincinnati Open ATP1000' -> the tour AND its tier number in tour colour.

    Applied at render time, never baked into the label itself: the same label
    goes into the subject line, and a subject cannot carry a <span>.

    The tier is inside the match on purpose — "ATP 1000" reads as one badge, so
    coluring the letters and leaving the number black splits it in half.
    """
    m = _TOUR_SUFFIX_RE.search(label)
    if not m:
        return label
    ink = _TOUR_INK[m.group(1)]["dark_bg" if on_dark else "light_bg"]
    return f'{label[:m.start()]}<span style="color:{ink}">{m.group(0)}</span>'


def _setup():
    resend.api_key = settings.resend_api_key


def _send(params: resend.Emails.SendParams) -> Optional[Exception]:
    # The last line before the network. Every email in the app funnels through
    # here, so this is the one place the staging kill switch cannot be routed
    # around by a caller that forgot about it — see Settings.outbound_notifications.
    if not settings.outbound_notifications:
        logger.warning(
            "BLOCKED outbound email to %s (%r) — outbound_notifications=false",
            params.get("to"), params.get("subject"))
        return None
    _setup()
    try:
        resend.Emails.send(params)
        return None
    except Exception as e:
        logger.error("Failed to send email to %s: %s", params.get("to"), e)
        return e


async def send_async(params: resend.Emails.SendParams) -> None:
    if not settings.resend_api_key:
        return  # Email disabled in this environment (no RESEND_API_KEY set)
    if settings.environment != "production":
        # Local/dev processes can inherit a real RESEND_API_KEY from the shell
        # environment; without this guard they'd send real emails to real users
        # any time the dev server's scheduler polls a live tournament.
        logger.info("Skipping email send (ENVIRONMENT=%r, not 'production'): %r", settings.environment, params.get("subject"))
        return
    from app.services.system_log import app_log
    exc = await asyncio.to_thread(_send, params)
    to = params.get("to", [])
    subject = params.get("subject", "")
    recipient = to[0] if len(to) == 1 else to
    if exc is not None:
        # Not routed through is_transient_http_error on purpose: a transient
        # failure elsewhere self-heals on the next poll, but there is no retry
        # here — a blip means this particular email was never delivered, which
        # is exactly the thing worth knowing about.
        from app.services.http_errors import describe_exception
        await app_log("error", "notifications", f"Email send failed: {subject!r} → {recipient}",
                      {"to": to, "subject": subject, "error": describe_exception(exc)})
    else:
        await app_log("info", "notifications", f"Email sent: {subject!r} → {recipient}",
                      {"to": to, "subject": subject})


async def send_verification(email: str, username: str, token: str, code: str) -> None:
    verify_url = f"{BASE_URL}/verify-email?token={token}"
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": "Verify your Upset Alert email",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">Hi {username}, verify your email</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 20px">
            Enter this code on the site, or click the button below. Expires in 24 hours.
          </p>
          <div style="margin:0 0 24px;text-align:center">
            <span style="display:inline-block;font-size:36px;font-weight:700;letter-spacing:10px;
                         padding:16px 24px;background:#f3f4f6;border-radius:8px;color:#111">
              {code}
            </span>
          </div>
          <a href="{verify_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Verify Email
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_welcome(email: str, username: str) -> None:
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": "Welcome to Upset Alert!",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">Welcome to Upset Alert, {username}!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            You're all set to start picking upsets and climbing the leaderboard.
            Head over to the site to join a league and make your first picks.
          </p>
          <a href="{BASE_URL}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Go to Upset Alert
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_password_reset(email: str, reset_token: str) -> None:
    reset_url = f"{BASE_URL}/reset-password?token={reset_token}"
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": "Reset your Upset Alert password",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">Reset your password</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            Click the button below to reset your password. This link expires in 1 hour.
          </p>
          <a href="{reset_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Reset Password
          </a>
          <p style="margin-top:24px;font-size:13px;color:#888">
            If you didn't request this, you can safely ignore this email.
          </p>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_member_joined(
    owner_email: str,
    owner_username: str,
    league_name: str,
    league_id: int,
    new_username: str,
) -> None:
    league_url = f"{BASE_URL}/leagues/{league_id}"
    await send_async({
        "from": FROM,
        "to": [owner_email],
        "subject": f'{new_username} joined "{league_name}"',
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">New member in {league_name}!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            <strong>{new_username}</strong> just joined your league <strong>{league_name}</strong>.
          </p>
          <a href="{league_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View League
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_new_user_notification(
    new_email: str, new_username: str, full_name: Optional[str] = None
) -> None:
    """Admin ping when someone finishes verifying.

    Named "Full Name (username)". The username alone is often no help in
    working out who has actually signed up.

    The body is escaped, unlike the rest of this module: all three values are
    typed by the person registering, and a name containing < or & would
    otherwise land as markup. The SUBJECT takes the raw form — a subject line is
    plain text, so an escaped apostrophe would arrive as a literal &#x27;.
    """
    from html import escape

    uname = (new_username or "").strip()
    real = (full_name or "").strip()
    # Fall back to the username alone rather than printing "None (bob)" or the
    # same string twice — some accounts have no name, and some set it to their
    # username.
    who = f"{real} ({uname})" if real and real.casefold() != uname.casefold() else uname

    await send_async({
        "from": FROM,
        "to": ["pdwiens@gmail.com"],
        "subject": f"New user: {who}",
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <p><strong>{escape(who)}</strong> ({escape(new_email or "")}) just verified their
             account on Upset Alert.</p>
        </div>
        """,
    })


_NUMBER_WORDS = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
    6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
}

# Row accent per tour, matching the blue/pink banding of the draws table on site.
_TOUR_COLOURS = {"M": ("#1e3a8a", "#e0e7ff"), "F": ("#9d174d", "#fce7f3")}


def _tier_badge(category: str, gender: str) -> str:
    """Short tier label for the badge on each digest row: 'ATP 250', 'Grand Slam'."""
    cat = (category or "").upper()
    if "SLAM" in cat or "GRAND" in cat:
        return "Grand Slam"
    tour = "ATP" if gender == "M" else "WTA"
    tier = "1000" if "1000" in cat else "500" if "500" in cat else "250"
    return f"{tour} {tier}"


def fmt_close(dt, tz_name: Optional[str] = None) -> str:
    """'Sun 18 Oct, 11:00 PM PDT' in the reader's zone, or '… 6:00 AM UTC'.

    closing_time is stored as naive UTC. Rendering it in the reader's own zone
    is the whole point of storing User.timezone — but the zone is null until
    they next open the site, so UTC is the fallback and it is always labelled.
    An unlabelled time would be worse than either: being wrong about a pick
    deadline is the one error this email cannot afford.
    """
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo

    aware = dt.replace(tzinfo=_tz.utc)
    if tz_name:
        try:
            aware = aware.astimezone(ZoneInfo(tz_name))
        except Exception:
            # Stored zone no longer resolves (tzdata drop, hand-edited row).
            # Fall through to UTC rather than lose the notification.
            logger.warning("Unresolvable user timezone %r — falling back to UTC", tz_name)
            aware = dt.replace(tzinfo=_tz.utc)

    clock = f"{(aware.hour % 12) or 12}:{aware.strftime('%M')} {aware.strftime('%p')}"
    label = aware.strftime("%Z") or "UTC"
    return f"{aware.strftime('%a')} {aware.day} {aware.strftime('%b')}, {clock} {label}"


def _digest_row(draw: dict, last: bool) -> str:
    fg, bg = _TOUR_COLOURS.get(draw["gender"], _TOUR_COLOURS["M"])
    url = f"{BASE_URL}/tournaments/{draw['id']}"
    meta = " &nbsp;·&nbsp; ".join(
        p for p in (draw.get("location"), draw.get("surface"),
                    f"{draw['draw_size']} draw" if draw.get("draw_size") else None) if p
    )
    close = draw.get("closes")
    close_html = (
        f'<td style="font-size:13px;color:{"#b45309" if draw.get("closes_soon") else "#6b7280"}">'
        f'Picks close {close}</td>'
        if close else '<td style="font-size:13px;color:#6b7280">Picks close at first ball</td>'
    )
    return f"""
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;
         margin:0 0 {'22px' if last else '10px'};border:1px solid #e5e7eb;border-radius:6px">
    <tr><td style="padding:12px 14px">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="font-size:16px;font-weight:700;color:#111">{draw['name']}</td>
        <td align="right"><span style="font-size:11px;font-weight:700;color:{fg};background:{bg};
            border-radius:10px;padding:3px 8px">{draw['tier']}</span></td>
      </tr></table>
      <div style="font-size:13px;color:#6b7280;margin:5px 0 9px">{meta}</div>
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        {close_html}
        <td align="right"><a href="{url}" style="font-size:13px;font-weight:600;color:#1b4332;
           text-decoration:none">Make picks &rarr;</a></td>
      </tr></table>
    </td></tr>
  </table>"""


async def send_draw_release_digest(
    email: str,
    draws: list[dict],
    week_label: str,
    is_followup: bool = False,
    unsubscribe_url: str = "",
    tz_known: bool = False,
) -> None:
    """One email covering every draw released this week.

    draws is sorted soonest-deadline-first and its 'closes' strings are already
    rendered in this recipient's zone — the caller does that per recipient,
    which is why this takes a single address rather than a list.
    """
    n = len(draws)
    if not n:
        return
    count_word = _NUMBER_WORDS.get(n, str(n))

    # A Slam or a 1000 opens its men's and women's draws together, so the whole
    # batch is one tournament. "2 draws are live" then says the least useful
    # true thing about it — the event's name is what a reader recognises in an
    # inbox, and counting draws is only informative when they are different
    # tournaments.
    names = {d["name"] for d in draws}
    event = draws[0]["name"] if len(names) == 1 else None

    if is_followup:
        # The week's digest already went out; these arrived late.
        subject = (f"One more draw is live — {draws[0]['name']}" if n == 1
                   else f"{event}: {n} more draws are live" if event
                   else f"{n} more draws are live — week of {week_label}")
        heading = (f"One more draw for the week of {week_label}" if n == 1
                   else f"{count_word} more draws for the week of {week_label}")
        intro = ("It wasn't out when we sent the rest of this week's draws. It's live now."
                 if n == 1 else
                 "They weren't out when we sent the rest of this week's draws. They're live now.")
    else:
        subject = (f"{event} is live — week of {week_label}" if event
                   else f"{n} draws are live — week of {week_label}")
        heading = "The draw is live!" if n == 1 else "This week's draws are live"
        intro = (f"The draw for <strong>{draws[0]['name']}</strong> has been released."
                 if n == 1 else
                 f"{count_word} draws opened for the week of <strong>{week_label}</strong>. "
                 f"Soonest deadline first.")

    rows = "".join(_digest_row(d, last=(i == n - 1)) for i, d in enumerate(draws))
    # Same admin-gated destination the round digest had: /tournaments is wrapped
    # in RequireAdmin, so "View All Draws" bounced every non-admin recipient.
    # The dashboard is the right landing page for this one rather than /leagues —
    # this email is about draws that just opened for picking, and the dashboard
    # is what lists them (it is also where the matching push notification goes).
    cta_url = f"{BASE_URL}/tournaments/{draws[0]['id']}" if n == 1 else BASE_URL
    cta_text = "Make Your Picks" if n == 1 else "View All Draws"
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af;'
        f'font-family:sans-serif">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from draw-release emails</a></p>'
        if unsubscribe_url else ""
    )

    await send_async({
        "from": FROM,
        "to": [email],
        "subject": subject,
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">{heading}</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 20px">{intro}</p>
          {rows}
          <a href="{cta_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            {cta_text}
          </a>
          <p style="color:#9ca3af;line-height:1.6;margin:18px 0 0;font-size:12px">
            Picks lock when each draw's first match starts.{
              "" if tz_known else " Times shown in UTC — open the site to see your local time."
            }
          </p>
        {_BODY_CLOSE}{_WRAP_CLOSE}{unsubscribe}""",
    })


def _round_complete_league_block(name: str, rows: list[tuple], is_last: bool) -> str:
    """One vertically-stacked league: full-width table with the league name as a
    header spanning above the Name / Score column headers, then the numbered list.

    rows: [(rank, competitor_name, score, is_you), ...] in rank order.
    A row with rank is None is an ellipsis (gap) row.
    """
    def _row(i, rank, cname, score, you):
        if rank is None:  # ellipsis / gap row
            return (
                '<tr style="background:#ffffff">'
                '<td colspan="2" style="padding:2px 12px;color:#9ca3af;text-align:center">…</td>'
                '</tr>'
            )
        bg = "#cfe8ff" if you else ("#ffffff" if i % 2 == 0 else "#f9fafb")
        weight = "700" if you else "400"
        return (
            f'<tr style="background:{bg}">'
            f'<td style="padding:7px 12px 7px 14px;font-weight:{weight};color:#111">'
            f'<span style="color:#9ca3af">{rank}.</span>&nbsp;{cname}</td>'
            f'<td align="center" width="90" style="padding:7px 12px;text-align:center;width:90px;'
            f'font-weight:{"700" if you else "400"};color:#111">{score:g}</td>'
            f'</tr>'
        )
    body_rows = "".join(_row(i, *r) for i, r in enumerate(rows))
    margin = "0" if is_last else "0 0 22px"
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;border-collapse:collapse;font-size:14px;margin:{margin};'
        f'border:1px solid #e5e7eb">'
        # League name — header spanning both columns, above the Name/Score headers.
        f'<tr><td colspan="2" style="padding:11px 12px;text-align:center;font-weight:700;'
        f'font-size:16px;color:#111;background:#ffffff;'
        f'border-bottom:1px solid #e5e7eb">{name}</td></tr>'
        # Column headers.
        '<tr style="background:#f3f4f6">'
        '<th align="left" style="padding:7px 12px 7px 14px;font-size:12px;'
        'text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;'
        'border-bottom:2px solid #e5e7eb">Name</th>'
        '<th align="center" width="90" style="padding:7px 12px;font-size:12px;text-align:center;'
        'width:90px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;'
        'border-bottom:2px solid #e5e7eb">Score</th>'
        f'</tr>{body_rows}</table>'
    )


def _status_badge(status: str) -> str:
    """Seed number or entry type (WC/Q/LL/PR/SE) beside a player's name.

    Inline styles only, and no flex/border-radius load-bearing: Outlook drops
    most of this and is left with a plain grey-on-white token, which still
    reads. Empty status renders nothing at all rather than an empty box —
    most players are neither seeded nor special entries.
    """
    if not status:
        return ""
    return (
        f'<span style="display:inline-block;margin-left:5px;padding:0 4px;'
        f'font-size:11px;font-weight:700;line-height:16px;color:#6b7280;'
        f'background:#f3f4f6;border:1px solid #e5e7eb;border-radius:3px">'
        f'{_esc(status)}</span>'
    )


def _match_result_row(i: int, winner_last: str, winner_status: str,
                      loser_last: str, loser_status: str,
                      score: str, is_correct: bool) -> str:
    # Alternating row background (matches _round_complete_league_block) instead
    # of bolding the winner name — easier to scan a long list of results.
    bg = "#ffffff" if i % 2 == 0 else "#f9fafb"
    # Mirrors the app's pick-result convention (BracketView.jsx): ✓ #15803d / ✗ #dc2626.
    mark_color = "#15803d" if is_correct else "#dc2626"
    mark_char = "&#10003;" if is_correct else "&#10007;"
    return (
        f'<tr style="background:{bg}">'
        f'<td width="24" style="padding:8px 4px 8px 12px;font-size:14px;'
        f'font-weight:700;color:{mark_color};width:24px">{mark_char}</td>'
        f'<td style="padding:8px 12px 8px 4px;font-size:14px;color:#111">'
        f'{_esc(winner_last)}{_status_badge(winner_status)} def. '
        f'{_esc(loser_last)}{_status_badge(loser_status)}</td>'
        f'<td align="right" style="padding:8px 12px;font-size:14px;color:#444;'
        f'white-space:nowrap;text-align:right">{score}</td>'
        f'</tr>'
    )


def _round_results_widget(round_name: str, results: list[tuple]) -> str:
    """Always-visible match-results panel. Gmail (web and mobile app) strips
    <style> tags and doesn't support the CSS-only ":checked" accordion trick,
    so this is plain static markup rather than a collapsible widget.
    results: [(winner_last, winner_status, loser_last, loser_status, score,
    is_correct), ...] already ordered by the caller — correct picks first, then
    by the best-ranked player in the match — where is_correct reflects this
    recipient's own pick, so the order differs per recipient."""
    if not results:
        return ""
    rows = "".join(
        _match_result_row(i, w, ws, l, ls, s, c)
        for i, (w, ws, l, ls, s, c) in enumerate(results)
    )
    return f"""<div style="margin:24px 0 0">
          <div style="padding:11px 14px;background:#f3f4f6;border:1px solid #e5e7eb;
                border-top-left-radius:6px;border-top-right-radius:6px;
                font-weight:600;font-size:14px;color:#111">
            {round_name} Results
          </div>
          <table width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-top:none;
                        border-bottom-left-radius:6px;border-bottom-right-radius:6px">
            <tbody>{rows}</tbody>
          </table>
        </div>"""


async def send_round_complete_notification(
    email: str,
    tournament_name: str,
    year: int,
    tournament_id: int,
    round_name: str,
    leagues: list[tuple],  # [(league_name, [(rank, name, score, is_you), ...]), ...]
    category: str = "",
    gender: str = "M",
    unsubscribe_url: str = "",
    match_results: Optional[list[tuple]] = None,  # [(w_last, w_status, l_last, l_status, score, is_correct), ...]
) -> None:
    """One email per user: every group's competitor list, stacked vertically."""
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    blocks = "".join(
        _round_complete_league_block(lg_name, rows, i == len(leagues) - 1)
        for i, (lg_name, rows) in enumerate(leagues)
    )
    results_widget = _round_results_widget(round_name, match_results or [])
    # Standalone footer, outside the card entirely — not part of any widget/box.
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from round-completion emails</a></p>'
        if unsubscribe_url else ""
    )
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": f"{round_name} Complete: {_tournament_label(tournament_name, category, gender)}",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 16px">{_tournament_label(tournament_name, category, gender)} {round_name} is complete!</h1>
          <a href="{tournament_url}" style="display:inline-block;padding:12px 24px;margin:0 0 20px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Draw &amp; Standings
          </a>
          <p style="color:#444;line-height:1.6;margin:0 0 20px">Here are the current standings for the leagues you are competing in:</p>
          <div style="margin:0 0 24px">{blocks}</div>
          {results_widget}
        {_BODY_CLOSE}{_WRAP_CLOSE}
        {unsubscribe}""",
    })


def _round_abbrev(round_name: str) -> str:
    """'Semi-Finals' -> 'SF'. Column headers have ~86px to work with, so the
    round name has to shrink to fit beside the word it qualifies."""
    n = (round_name or "").strip()
    low = n.lower()
    if low.startswith("semi"):
        return "SF"
    if low.startswith("quarter"):
        return "QF"
    if low.startswith("final"):
        return "F"
    return n  # R128 / R64 / R32 / R16 are already short


def _section_banner(title: str, subtitle: str = "", link_url: str = "", link_text: str = "") -> str:
    """Full-bleed section header — a green bar spanning the whole email card,
    edge to edge like the logo header, not inset the way the body content is.

    Built as a table (not a padded div) so it can sit outside the body's own
    horizontal padding: that padding is what would otherwise stop it short of
    the card edges in every client.
    """
    link_cell = (
        f'<td align="right" valign="middle" bgcolor="#1b4332" '
        f'style="padding:13px 24px 13px 8px;background:#1b4332;text-align:right;white-space:nowrap">'
        f'<a href="{link_url}" style="color:#ffffff;font-size:13px;font-weight:600;'
        f'text-decoration:underline">{link_text}</a></td>'
        if link_url and link_text else ""
    )
    sub = (
        f'<div style="font-size:12px;font-weight:400;color:#b7cdbf;padding-top:3px">{subtitle}</div>'
        if subtitle else ""
    )
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#1b4332" '
        f'style="width:100%;background:#1b4332;border-collapse:collapse">'
        f'<tr><td valign="middle" bgcolor="#1b4332" '
        f'style="padding:13px 24px;background:#1b4332;color:#ffffff;font-size:16px;'
        f'font-weight:700;line-height:1.25">{title}{sub}</td>{link_cell}</tr></table>'
    )


def _week_summary(rows: list[tuple], round_name: str) -> str:
    """'Summary' section: one line per draw — correct picks and global place.

    rows: [(draw_label, '12/16', '2nd of 13'), ...]
    """
    body = "".join(
        f'<tr style="background:{"#ffffff" if i % 2 == 0 else "#f9fafb"}">'
        f'<td style="padding:8px 12px 8px 14px;font-size:14px;color:#111">{_tour_coloured(label)}</td>'
        f'<td align="center" width="86" style="padding:8px 6px;font-size:14px;text-align:center;'
        f'width:86px;color:#111;font-weight:700">{hits}</td>'
        f'<td align="right" width="90" style="padding:8px 14px 8px 6px;font-size:14px;'
        f'text-align:right;width:90px;color:#444;white-space:nowrap">{place}</td>'
        f'</tr>'
        for i, (label, hits, place) in enumerate(rows)
    )
    return f"""{_section_banner("Summary")}
    <div style="padding:20px 24px 22px;background:#ffffff">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:6px">
        <tr style="background:#f3f4f6">
          <th align="left" style="padding:7px 12px 7px 14px;font-size:12px;text-transform:uppercase;
              letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb">Draw</th>
          <th align="center" width="86" style="padding:7px 6px;font-size:12px;text-align:center;width:86px;
              text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;line-height:1.25;
              border-bottom:2px solid #e5e7eb">{_round_abbrev(round_name)} Correct</th>
          <th align="right" width="90" style="padding:7px 14px 7px 6px;font-size:12px;text-align:right;width:90px;
              text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;
              border-bottom:2px solid #e5e7eb">Global</th>
        </tr>
        {body}
      </table>
    </div>"""


def _draw_section(draw: dict, is_last: bool) -> str:
    """One draw inside the weekly email: full-bleed banner, then its standings
    and results boxed beneath it."""
    blocks = "".join(
        _round_complete_league_block(n, rows, i == len(draw["leagues"]) - 1)
        for i, (n, rows) in enumerate(draw["leagues"])
    )
    city = f"{draw['city']} &middot; " if draw.get("city") else ""
    banner = _section_banner(
        _tour_coloured(draw["label"], on_dark=True),
        f"{city}{draw['round_name']} complete",
        f"{BASE_URL}/tournaments/{draw['id']}",
        "View draw",
    )
    pad_bottom = "24px" if is_last else "22px"
    return f"""{banner}
    <div style="padding:20px 24px {pad_bottom};background:#ffffff">
      {blocks}
      {_round_results_widget(draw['round_name'], draw['match_results'])}
    </div>"""


async def send_round_complete_digest(
    email: str,
    draws: list[dict],
    round_name: str,
    week_label: str,
    reached: int,
    total_in_week: int,
    summary_rows: list[tuple],
    unsubscribe_url: str = "",
    unsubscribe_label: str = "round-completion emails",
    is_final: bool = False,
    is_followup: bool = False,
    event_label: Optional[str] = None,
) -> None:
    """One email per user per round per bucket, covering every draw that reached it.

    draws: [{id, label, city, round_name, leagues, match_results}, ...] — already
    sliced to this recipient (their leagues, their pick correctness).

    is_final: this batch is the Final round, so it is also the draw-completion
    digest — the standings in it are final, not a mid-tournament snapshot, and
    the wording says so. Same content either way; only the voice changes.

    event_label: the batch is one 1000/Slam event rather than a tennis week, so
    it is titled after the event and covers that event's draws — both genders
    where it hosts both. total_in_week is then the event's draw count, not the
    week's.
    """
    if not draws:
        return

    if is_followup:
        lead = "Final Standings" if is_final else f"{round_name} Complete"
        subject = f"{lead} — {draws[0]['label']}" if len(draws) == 1 \
            else f"{lead} — {len(draws)} more draws"
        heading = "The draw is complete" if is_final else f"{round_name} is complete"
        peers = "this event's other draw" if event_label else "the rest of this week's draws"
        scope = (f"It finished after {peers}." if len(draws) == 1
                 else f"These finished after {peers}.")
    elif event_label:
        # A major is its own bucket, so the event name is the scope — "Week of
        # August 2" would be both redundant and wrong for a draw that runs into
        # the following week.
        lead = "Final Standings" if is_final else f"{round_name} Complete"
        subject = f"{lead} — {event_label}"
        if is_final:
            heading = ("The draw is complete" if reached == 1
                       else "Both draws are complete" if reached == 2
                       else "The draws are complete")
        else:
            heading = f"{round_name} is complete"
        scope = ("the men's and women's draws" if reached == 2 and reached == total_in_week
                 else "the singles draw" if total_in_week == 1
                 else f"{reached} of {total_in_week} draws")
    elif is_final:
        subject = (f"Final Standings: {draws[0]['label']}" if total_in_week == 1
                   else f"Final Standings — Week of {week_label}")
        heading = ("The draw is complete" if reached == 1
                   else "This week's draws are complete")
        scope = (f"all {total_in_week} draws" if reached == total_in_week and total_in_week > 1
                 else f"{reached} of {total_in_week} draws has finished" if reached == 1
                 else f"{reached} of {total_in_week} draws have finished")
    else:
        subject = (f"{round_name} Complete: {draws[0]['label']}" if total_in_week == 1
                   else f"{round_name} Complete — Week of {week_label}")
        heading = f"{round_name} is complete"
        # Naming every tournament would overflow the subject line, so the scope
        # goes here instead — and it has to be honest about draws still playing.
        scope = (f"all {total_in_week} draws" if reached == total_in_week and total_in_week > 1
                 else f"{reached} of {total_in_week} draws has reached this round" if reached == 1
                 else f"{reached} of {total_in_week} draws have reached this round")

    if is_followup:
        intro = scope
    else:
        intro = f"{event_label or f'Week of {week_label}'} &middot; {scope}"
    sections = "".join(_draw_section(d, i == len(draws) - 1) for i, d in enumerate(draws))
    summary = _week_summary(summary_rows, round_name) if len(summary_rows) > 1 else ""
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from {unsubscribe_label}</a></p>'
        if unsubscribe_url else ""
    )
    # Always the leagues page: this email is about where everyone placed, and
    # that is the page that answers it for every draw at once.
    #
    # The multi-draw branch this replaces pointed at /tournaments, which is
    # admin-gated (App.jsx wraps it in RequireAdmin) — so every non-admin
    # recipient of a multi-draw digest, which is most of them most weeks, was
    # sent to a page they are bounced off.
    cta_url = f"{BASE_URL}/leagues"
    cta_text = "View Standings"

    await send_async({
        "from": FROM,
        "to": [email],
        "subject": subject,
        # The intro block keeps the body padding; everything after it is a
        # banner-headed section that must reach both card edges, so those sit
        # outside the padded div rather than inside it.
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}
          <div style="padding:28px 24px 24px;background:#ffffff;color:#111111">
            <h1 style="font-size:22px;margin:0 0 6px">{heading}</h1>
            <p style="color:#6b7280;font-size:13px;margin:0 0 18px">{intro}</p>
            <a href="{cta_url}" style="display:inline-block;padding:12px 24px;margin:0;
               background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
              {cta_text}
            </a>
          </div>
          {summary}
          {sections}
        {_WRAP_CLOSE}
        {unsubscribe}""",
    })



def _change_row(change: dict, is_last: bool) -> str:
    """One swap: who left, who took the slot, and whether it was the reader's pick.

    The arrow is a table cell rather than inline text so the two names stay on
    their own lines when a client narrows the card — a wrapped 'X → Y' that
    breaks after the arrow reads as two unrelated players.
    """
    from app.services.draw_changes import entry_suffix, slot_label

    # No "this was your pick" flag, and no highlight for the rows that were.
    # Any replacement in a draw you are competing in can reach your bracket —
    # whoever comes in plays on, and everything downstream moves with them.
    # Marking two of the rows implied the rest were somebody else's problem.
    mine = False
    src = (change["old_name"] if change["kind"] == "replaced"
           else slot_label(change.get("old_entry_type"), change["bracket_position"]))
    src_style = ("color:#6b7280;text-decoration:line-through" if change["kind"] == "replaced"
                 else "color:#6b7280;font-style:italic")
    flag = ""
    return f"""
      <tr>
        <td style="padding:{'10px 14px' if is_last else '10px 14px 0'};">
          <table width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="border-collapse:separate;border:1px solid {'#fcd34d' if mine else '#e5e7eb'};
                        border-radius:6px;background:{'#fffbeb' if mine else '#ffffff'}">
            <tr><td style="padding:11px 13px">
              <div style="font-size:14px;{src_style}">{_esc(src)}</div>
              <div style="font-size:15px;font-weight:700;color:#111;padding-top:3px">
                &#8595;&nbsp; {_esc(change['new_name'])}{_esc(entry_suffix(change.get('new_entry_type')))}
              </div>
              {flag}
            </td></tr>
          </table>
        </td>
      </tr>"""


def _draw_change_section(draw: dict, is_last: bool) -> str:
    n = len(draw["changes"])
    banner = _section_banner(
        _tour_coloured(draw["label"], on_dark=True),
        f"{n} change{'' if n == 1 else 's'} &middot; "
        + ("picks are locked" if draw.get("locked") else "picks still open"),
        f"{BASE_URL}/tournaments/{draw['id']}",
        "View draw",
    )
    rows = "".join(_change_row(c, i == n - 1) for i, c in enumerate(draw["changes"]))
    return f"""{banner}
    <div style="padding:10px 10px {'20px' if is_last else '14px'};background:#ffffff">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>
    </div>"""


async def send_draw_change_digest(
    email: str,
    draws: list[dict],
    unsubscribe_url: str = "",
) -> None:
    """
    A draw this reader has entered changed after they picked from it.

    draws is already sliced to this recipient: only draws they compete in, and
    each change carries affects_you. That flag drives the subject line as well
    as the card styling — "your pick was replaced" is a different message from
    "the draw moved around you", and putting both behind one neutral subject
    would bury the one that needs acting on.
    """
    if not draws:
        return

    one_draw = draws[0] if len(draws) == 1 else None

    # WHAT MATTERS IS THE DRAW, NOT WHOSE PICK IT WAS.
    #
    # This used to lead with "some of your picks have changed" and flag the rows
    # that were yours. That is the wrong emphasis: a replacement anywhere in a
    # draw you are competing in can reach your bracket, because whoever comes in
    # plays on and everything downstream moves with them. Singling out the two
    # rows that were literally your pick implies the others are none of your
    # business, when they are exactly as capable of changing your result.
    #
    # So it is one neutral subject naming the event, and the swaps themselves —
    # which is all the message ever needed to carry.
    subject = (
        f"Player Replacements in {one_draw['name']}" if one_draw
        else f"Player Replacements in {len(draws)} draws"
    )

    open_draws = [d for d in draws if not d.get("locked")]
    footer = (
        "Predictions are still open" if open_draws else
        "Picks are locked for these draws, so nothing needs doing — this is just so "
        "you know who your bracket is backing."
    )

    sections = "".join(_draw_change_section(d, i == len(draws) - 1) for i, d in enumerate(draws))
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af;'
        f'font-family:sans-serif">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from draw-change emails</a></p>'
        if unsubscribe_url else ""
    )

    await send_async({
        "from": FROM,
        "to": [email],
        "subject": subject,
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}
          {sections}
          <div style="padding:0 24px 24px;background:#ffffff">
            <p style="color:#9ca3af;line-height:1.6;margin:0;font-size:12px">{_esc(footer)}</p>
          </div>
        {_WRAP_CLOSE}{unsubscribe}""",
    })


def _matchup_row(change: dict, is_last: bool) -> str:
    """One placed qualifier and the first-round match it creates."""
    mine = change.get("affects_you")
    opp = change.get("opponent")
    status = change.get("opponent_status")
    if change.get("opponent_bye"):
        right = '<span style="color:#6b7280">bye</span>'
    elif opp:
        badge = (f'<span style="font-size:11px;font-weight:700;color:#1b4332;background:#e8f0ea;'
                 f'border-radius:9px;padding:2px 6px;margin-left:6px">{_esc(status)}</span>'
                 if status else "")
        right = f'{_esc(opp)}{badge}'
    else:
        right = '<span style="color:#6b7280">opponent to be confirmed</span>'
    flag = (
        '<div style="font-size:12px;font-weight:700;color:#b45309;padding-top:5px">'
        'You picked this slot</div>' if mine else ""
    )
    # Marks which of the two names on the card is the qualifier. Read from the
    # entry, so a slot that resolved to something else is labelled accurately.
    entry_type = (change.get("new_entry_type") or "").strip()
    qual_badge = (
        f'<span style="font-size:11px;font-weight:700;color:#5b21b6;background:#ede9fe;'
        f'border-radius:9px;padding:2px 6px;margin-left:6px">{_esc(entry_type)}</span>'
        if entry_type else ""
    )
    return f"""
      <tr>
        <td style="padding:{'10px 14px' if is_last else '10px 14px 0'};">
          <table width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="border-collapse:separate;border:1px solid {'#fcd34d' if mine else '#e5e7eb'};
                        border-radius:6px;background:{'#fffbeb' if mine else '#ffffff'}">
            <tr><td style="padding:11px 13px">
              <div style="font-size:15px;font-weight:700;color:#111">
                {_esc(change['new_name'])}{qual_badge}
              </div>
              <div style="font-size:14px;color:#444;padding-top:3px">
                <span style="color:#6b7280">vs</span> {right}
              </div>
              {flag}
            </td></tr>
          </table>
        </td>
      </tr>"""


def _qualifiers_section(draw: dict, is_last: bool) -> str:
    from app.services.draw_changes import dedupe_matchups

    n = len(draw["changes"])
    # One card per MATCH, headline counts QUALIFIERS — two qualifiers drawn
    # against each other are one match, and printing it from both sides read as
    # a duplicate.
    rows_data = dedupe_matchups(draw["changes"])
    banner = _section_banner(
        _tour_coloured(draw["label"], on_dark=True),
        f"{n} qualifier{'' if n == 1 else 's'} placed &middot; "
        + ("picks are locked" if draw.get("locked") else "picks still open"),
        f"{BASE_URL}/tournaments/{draw['id']}",
        "View draw",
    )
    rows = "".join(_matchup_row(c, i == len(rows_data) - 1)
                   for i, c in enumerate(rows_data))
    return f"""{banner}
    <div style="padding:10px 10px {'20px' if is_last else '14px'};background:#ffffff">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>
    </div>"""


async def send_qualifiers_added_digest(
    email: str,
    draws: list[dict],
    unsubscribe_url: str = "",
) -> None:
    """
    The qualifying slots in a draw this reader entered now have players.

    A separate message from send_draw_change_digest, not a variant of it: a
    replacement is something to go and check, this is the draw becoming complete.
    Every placement is listed with the first-round match it creates, because the
    opponent is what makes it mean anything — a list of qualifier names on its
    own is a list of strangers.
    """
    if not draws:
        return

    changes = [c for d in draws for c in d["changes"]]
    n = len(changes)
    yours = [c for c in changes if c.get("affects_you")]
    one_draw = draws[0] if len(draws) == 1 else None

    subject = (
        f"Qualifier added: {one_draw['name']}" if one_draw and n == 1
        else f"{n} qualifiers added — {one_draw['name']}" if one_draw
        else f"{n} qualifiers added across {len(draws)} draws"
    )
    heading = "The qualifiers are in" if n > 1 else "A qualifier is in"
    intro = (
        "The qualifying slots in your draw now have players. Here's who came "
        "through and who they face first."
    )
    if yours:
        intro += (
            f" {'One' if len(yours) == 1 else str(len(yours))} of them "
            f"{'is' if len(yours) == 1 else 'are'} in a slot you picked, so your "
            f"bracket now backs a real player rather than a placeholder."
        )

    open_draws = [d for d in draws if not d.get("locked")]
    footer = (
        "Picks are still open for " + ", ".join(d["name"] for d in open_draws)
        + " — you can change yours."
        if open_draws else
        "Picks are locked for these draws, so this is just so you know who your "
        "bracket is backing."
    )

    sections = "".join(_qualifiers_section(d, i == len(draws) - 1) for i, d in enumerate(draws))
    cta_url = f"{BASE_URL}/tournaments/{draws[0]['id']}" if len(draws) == 1 else BASE_URL
    cta_text = "Check Your Picks" if open_draws else "View Draw" if len(draws) == 1 else "View Draws"
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af;'
        f'font-family:sans-serif">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from qualifier emails</a></p>'
        if unsubscribe_url else ""
    )

    await send_async({
        "from": FROM,
        "to": [email],
        "subject": subject,
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}
          <div style="padding:28px 24px 22px;background:#ffffff;color:#111111">
            <h1 style="font-size:22px;margin:0 0 8px">{heading}</h1>
            <p style="color:#444;line-height:1.6;margin:0 0 18px;font-size:14px">{intro}</p>
            <a href="{cta_url}" style="display:inline-block;padding:12px 24px;
               background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
              {cta_text}
            </a>
          </div>
          {sections}
          <div style="padding:0 24px 24px;background:#ffffff">
            <p style="color:#9ca3af;line-height:1.6;margin:0;font-size:12px">{_esc(footer)}</p>
          </div>
        {_WRAP_CLOSE}{unsubscribe}""",
    })


def _standout_row(pick: dict, is_last: bool) -> str:
    """One minority-correct call: the result, the score, and how alone they were."""
    pct = round(100 * pick["correct_count"] / pick["participant_count"])
    score = f'<div style="font-size:13px;color:#6b7280;padding-top:3px">{_esc(pick["score"])}</div>' \
        if pick.get("score") else ""
    return f"""
      <tr>
        <td style="padding:{'10px 14px' if is_last else '10px 14px 0'};">
          <table width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="border-collapse:separate;border:1px solid #e5e7eb;border-radius:6px">
            <tr><td style="padding:12px 13px">
              <div style="font-size:12px;color:#6b7280;padding-bottom:5px">
                {_esc(pick['label'])} &middot; {_esc(pick['round_name'])}
              </div>
              <div style="font-size:15px;font-weight:700;color:#111">
                {_esc(pick['winner'])} <span style="font-weight:400;color:#6b7280">def.</span> {_esc(pick['loser'])}
              </div>
              {score}
              <div style="font-size:13px;font-weight:700;color:#1b4332;padding-top:7px">
                {pick['correct_count']} of {pick['participant_count']} competitors called it &middot; {pct}%
              </div>
            </td></tr>
          </table>
        </td>
      </tr>"""


async def send_standout_pick_digest(
    email: str,
    picks: list[dict],
    unsubscribe_url: str = "",
) -> None:
    """
    The calls this reader got right that most of the field did not.

    picks is this recipient's own, rarest first — the caller sorts, so the
    subject line and the first card are always the best call of the batch.
    """
    if not picks:
        return

    n = len(picks)
    top = picks[0]
    if n == 1:
        subject = f"You called it: {top['winner']} def. {top['loser']}"
        heading = "You saw that coming"
        intro = (
            f"Only {top['correct_count']} of {top['participant_count']} competitors "
            f"picked {_esc(top['winner'])} — you were one of them."
        )
    else:
        subject = f"{n} picks the field missed"
        heading = f"{n} calls most competitors missed"
        intro = ("Fewer than half the field picked these right. You did.")

    rows = "".join(_standout_row(p, i == n - 1) for i, p in enumerate(picks))
    cta_url = f"{BASE_URL}/tournaments/{top['draw_id']}"
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af;'
        f'font-family:sans-serif">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from standout-pick emails</a></p>'
        if unsubscribe_url else ""
    )

    await send_async({
        "from": FROM,
        "to": [email],
        "subject": subject,
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}
          <div style="padding:28px 24px 22px;background:#ffffff;color:#111111">
            <h1 style="font-size:22px;margin:0 0 8px">{heading}</h1>
            <p style="color:#444;line-height:1.6;margin:0 0 18px;font-size:14px">{intro}</p>
            <a href="{cta_url}" style="display:inline-block;padding:12px 24px;
               background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
              View Draw
            </a>
          </div>
          {_section_banner("Your calls", f"{n} pick{'' if n == 1 else 's'} the field missed")}
          <div style="padding:10px 10px 20px;background:#ffffff">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>
          </div>
        {_WRAP_CLOSE}{unsubscribe}""",
    })


_ALERT_STYLES = {
    "error":   {"label": "Error",   "fg": "#b91c1c", "bg": "#fee2e2", "bar": "#dc2626"},
    "warning": {"label": "Warning", "fg": "#92400e", "bg": "#fef3c7", "bar": "#f59e0b"},
}


def _alert_time(dt, tz) -> str:
    """'Tue 5 Aug, 6:40 PM PDT' — every timestamp in an alert is zone-labelled."""
    local = dt.astimezone(tz)
    clock = f"{(local.hour % 12) or 12}:{local.strftime('%M')} {local.strftime('%p')}"
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')}, {clock} {local.strftime('%Z')}"


def _alert_ago(delta) -> str:
    """'25 hours' / '3 days' — coarse on purpose, these are never precise claims."""
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{max(1, int(delta.total_seconds() // 60))} minutes"
    if hours < 48:
        return f"{round(hours)} hours"
    return f"{round(hours / 24)} days"


# Multi-line and always long — a truncated first frame identifies nothing, so
# it would cost the card's whole width to say "there was a traceback". The full
# thing is in the admin panel, one click away via the button below.
_ALERT_DETAIL_SKIP = {"traceback", "stack", "stacktrace", "handoff"}


def _alert_handoff(detail: dict) -> str:
    """A paste-ready prompt, rendered whole.

    When an automated repair gives up, its verdict carries `handoff`: the text
    a human pastes into an interactive Claude Code session to continue the
    fix. The compact strip above truncates values at 90 chars — useless for
    this one field, whose entire job is to survive copy-paste intact — so it
    is skipped there and rendered here as a <pre>, newlines and all.
    """
    text = (detail or {}).get("handoff")
    if not text or not str(text).strip():
        return ""
    return (
        '<div style="font-size:11px;font-weight:700;color:#6b7280;'
        'text-transform:uppercase;letter-spacing:0.04em;margin:12px 0 4px">'
        'Paste this into Claude Code</div>'
        f'<pre style="font-size:12px;font-family:monospace;line-height:1.5;'
        f'background:#f3f4f6;border:1px solid #e5e7eb;border-radius:6px;'
        f'padding:10px 12px;margin:0;white-space:pre-wrap;word-break:break-word">'
        f'{_esc(str(text).strip())}</pre>'
    )


# The OOP verifier's own channel, so it is exempt from the alert digest's
# caps and dedup (alerts.py excludes the category) — one PDF processed, one
# email, per the owner's explicit request. Same recipient as ALERT_TO in
# alerts.py; duplicated rather than imported because alerts.py imports this
# module and the constant is two words.
OOP_STATUS_TO = "pdwiens@gmail.com"


async def send_oop_status(*, doc_id: int, tournament: str, play_date: str,
                          ok: bool, fixed: list, problems: list,
                          summary: str = "", handoff: str = "") -> None:
    """One concise status email per processed PDF — every outcome, every time.

    Three shapes: clean ("no problems found"), self-healed (each fix stated in
    the owner's requested wording — found, fixed, and made unrepeatable), and
    failed (what remains, plus the paste-ready handoff block)."""
    if not ok or problems:
        state, color = "needs attention", "#dc2626"
    elif fixed:
        state, color = f"{len(fixed)} fixed", "#d97706"
    else:
        state, color = "clean", "#16a34a"

    lines = []
    for f in fixed:
        # The owner's phrasing, verbatim by request. The claim is earned: the
        # verifier's orders require fixing the bug class, not the symptom.
        lines.append(
            f'<li style="margin:0 0 6px">{_esc(f)} — was found, and fixed. '
            f'Future instances of this error will not occur again.</li>')
    for pr in problems:
        lines.append(
            f'<li style="margin:0 0 6px;color:#dc2626">{_esc(pr)} — '
            f'could NOT be fixed automatically.</li>')
    body_list = (f'<ul style="margin:10px 0 0;padding-left:20px;font-size:14px;'
                 f'line-height:1.5;color:#111">{"".join(lines)}</ul>'
                 if lines else
                 '<div style="font-size:14px;color:#111;margin:10px 0 0">'
                 'All slots match the sheet. No problems found.</div>')

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px">
      <div style="font-size:13px;color:#6b7280">Order of play verified</div>
      <div style="font-size:16px;font-weight:700;color:#111;margin:4px 0 0">
        {_esc(tournament)} — {_esc(play_date)}
        <span style="color:{color}">({state})</span></div>
      {body_list}
      {f'<div style="font-size:12px;color:#6b7280;margin:10px 0 0">{_esc(summary)}</div>' if summary else ''}
      {_alert_handoff({"handoff": handoff}) if handoff else ''}
      <div style="font-size:11px;color:#9ca3af;margin:14px 0 0">doc {doc_id} · automated verify-and-fix</div>
    </div>"""

    await send_async({
        "from": FROM,
        "to": [OOP_STATUS_TO],
        "subject": f"OOP verified: {tournament} {play_date} — {state}",
        "html": html,
    })


def _alert_detail(detail: dict, message: str = "") -> str:
    """Compact key/value strip from detail_json, so the facts you'd triage with
    (which tournament, which title, which status code) are in the email rather
    than one admin-panel visit away.

    Values the message already contains are dropped: app_log callers routinely
    pass the same string as both, and printing it twice pushes the parts that
    are only in detail_json off the visible end of the row.
    """
    if not isinstance(detail, dict) or not detail:
        return ""
    parts = []
    for key, value in detail.items():
        if key in _ALERT_DETAIL_SKIP:
            continue
        text = str(value).strip()
        # Length floor so a coincidental short token ("M", "503") isn't mistaken
        # for a genuine repeat of a phrase in the message.
        if not text or (len(text) >= 8 and text in message):
            continue
        if len(text) > 90:
            text = text[:87] + "…"
        parts.append(
            f'<span style="white-space:nowrap"><span style="color:#9ca3af">{_esc(key)}</span> '
            f'<span style="color:#4b5563">{_esc(text)}</span></span>'
        )
        if len(parts) == 6:
            break
    if not parts:
        return ""
    return (f'<div style="font-size:12px;font-family:monospace;line-height:1.9;'
            f'margin:8px 0 0">{" &nbsp;·&nbsp; ".join(parts)}</div>')


def _esc(text) -> str:
    """These strings are exception text and scraped page titles — they contain
    angle brackets and ampersands often enough to break the markup."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _now_utc() -> datetime:
    """Now, tz-aware. The alert payload's timestamps are aware, and comparing
    an aware value with a naive one raises — the trap that has already cost
    this app an order-of-play ingest and a repeated database write."""
    return datetime.now(timezone.utc)


def _alert_card(issue: dict, tz, is_last: bool) -> str:
    style = _ALERT_STYLES.get(issue["level"], _ALERT_STYLES["error"])
    count = issue["count"]

    if issue["is_recurrence"]:
        # "Still happening" was asserted from is_recurrence alone — meaning only
        # "we have alerted about this before" — with nothing checking whether it
        # was still occurring. A fault that happened twice and then stopped, or
        # was fixed between the last occurrence and this send, was described as
        # ongoing. That is the fastest way to teach someone to ignore an alert.
        #
        # Say what the evidence supports instead: how long ago it was last seen.
        # A reader can tell "3 minutes ago" from "14 hours ago" without being
        # told what it means, and the second one is not a claim that has to be
        # retracted once it is fixed.
        nth = issue["previous_alerts"] + 1
        quiet_for = _now_utc() - issue["last_seen"]
        if quiet_for > timedelta(hours=2):
            head = f'Last seen {_alert_ago(quiet_for)} ago — nothing since'
        else:
            head = 'Still happening'
        since = (f' · last alerted {_alert_ago(issue["last_seen"] - issue["last_alerted"])} '
                 f'before that' if issue["last_alerted"] else '')
        recurrence = (
            f'<div style="font-size:12px;color:{style["fg"]};font-weight:600;margin:8px 0 0">'
            f'{head} (alert #{nth}){since}</div>'
        )
    else:
        recurrence = ""

    occurrences = "Once" if count == 1 else f"{count} times"
    window = (
        f'{occurrences}, {_alert_time(issue["last_seen"], tz)}' if count == 1 else
        f'{occurrences} &nbsp;·&nbsp; first {_alert_time(issue["first_seen"], tz)} '
        f'&nbsp;·&nbsp; latest {_alert_time(issue["last_seen"], tz)}'
    )

    return f"""
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;
         margin:0 0 {'22px' if is_last else '12px'};border:1px solid #e5e7eb;border-radius:6px">
    <tr>
      <td width="4" bgcolor="{style['bar']}" style="background:{style['bar']};width:4px;
          border-radius:6px 0 0 6px;font-size:0;line-height:0">&nbsp;</td>
      <td style="padding:13px 15px">
        <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td>
            <span style="font-size:11px;font-weight:700;color:{style['fg']};background:{style['bg']};
                  border-radius:10px;padding:3px 8px;text-transform:uppercase;
                  letter-spacing:0.04em">{style['label']}</span>
            <span style="font-size:12px;font-weight:600;color:#6b7280;margin-left:8px">
              {_esc(issue['category'])}</span>
          </td>
        </tr></table>
        <div style="font-size:14px;color:#111;line-height:1.5;margin:9px 0 0;
             word-break:break-word">{_esc(issue['message'])}</div>
        {_alert_detail(issue['detail'], issue['message'])}
        {_alert_handoff(issue['detail'])}
        <div style="font-size:12px;color:#6b7280;margin:9px 0 0">{window}</div>
        {recurrence}
      </td>
    </tr>
  </table>"""


# SQLAlchemy writes long, and all of it after the first clause is boilerplate:
# an autoflush advisory, the driver's own exception class, the full statement
# with its parameters, and a link to the docs. Truncating the raw message at a
# fixed character count therefore cut off INSIDE that boilerplate — the subject
# line read "OperationalError on GET /tournaments/121/draw: (raised as a result
# of …", which spends its whole width saying nothing.
_NOISE = re.compile(
    r"\(raised as a result of[^)]*\)"      # the autoflush advisory
    r"|\[SQL:.*"                           # the statement, and everything after it
    r"|\(Background on this error.*"       # the documentation link
    r"|\(sqlite3\.\w+\)"                  # the driver's exception class
    r"|\(psycopg2\.\w+\)",
    re.S,
)


def _headline(message: str, limit: int = 90) -> str:
    """A subject line that says what went wrong, in as few words as it takes.

    The noise comes out first, so the width is spent on the fault rather than on
    SQLAlchemy's preamble, and what is left is cut at a WORD boundary — a
    subject ending mid-word reads as a broken email rather than a long one.
    """
    text = " ".join(_NOISE.sub(" ", message or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


async def send_system_alert_digest(
    to_email: str,
    issues: list[dict],
    remaining_today: int = 0,
    held_back: int = 0,
    tz=None,
) -> bool:
    """
    Admin-only health digest — one email covering every problem that qualified
    in this scan. Returns True only if Resend accepted it.

    Deliberately does NOT go through send_async. send_async records its own
    failures via app_log at level "error", which is precisely the input this
    alerter reads: a bounced alert would log an error, which would become a new
    problem, which would send an alert. This path reports success/failure to
    its caller instead, and alerts.py logs the outcome under a category the
    scan excludes.
    """
    from zoneinfo import ZoneInfo
    tz = tz or ZoneInfo("America/Los_Angeles")
    if not issues:
        return False
    if not settings.resend_api_key or settings.environment != "production":
        logger.info("Skipping alert digest (ENVIRONMENT=%r): %d issue(s)",
                    settings.environment, len(issues))
        return False

    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = len(issues) - errors

    if len(issues) == 1:
        one = issues[0]
        headline = _headline(one["message"])
        subject = f"Upset Alert {one['level']} in {one['category']} — {headline}"
        heading = "Something needs your attention"
    else:
        counts = " and ".join(
            p for p in (f"{errors} error{'s' if errors != 1 else ''}" if errors else "",
                        f"{warnings} warning{'s' if warnings != 1 else ''}" if warnings else "")
            if p
        )
        subject = f"Upset Alert: {len(issues)} issues ({counts})"
        heading = f"{len(issues)} issues need your attention"

    # Only count something as "still going" if it actually happened recently.
    # The summary line made the same unchecked claim as the card beneath it.
    recurrences = sum(1 for i in issues if i["is_recurrence"]
                      and (_now_utc() - i["last_seen"]) <= timedelta(hours=2))
    if len(issues) == 1:
        recurring = " It has been alerted before and is still going." if recurrences else ""
    elif recurrences == len(issues):
        recurring = " All of them have been alerted before and are still going."
    elif recurrences:
        recurring = f" {recurrences} of them have been alerted before and are still going."
    else:
        recurring = ""
    intro = (
        f"{'This problem has' if len(issues) == 1 else 'These problems have'} been logged since "
        f"the last alert.{recurring}"
    )

    cards = "".join(_alert_card(i, tz, is_last=(n == len(issues) - 1))
                    for n, i in enumerate(issues))

    if held_back:
        cards += (
            f'<p style="font-size:13px;color:#6b7280;margin:0 0 22px;padding:10px 14px;'
            f'background:#f3f4f6;border-radius:6px">'
            f'&hellip; and {held_back} more distinct issue{"s" if held_back != 1 else ""} '
            f'not shown here. {"They are" if held_back != 1 else "It is"} still queued and '
            f'will appear in the next alert.</p>'
        )

    budget = (
        "This is the last alert of the day — anything new from here is held until "
        "tomorrow's first digest."
        if remaining_today <= 0 else
        f"{remaining_today} more alert{'s' if remaining_today != 1 else ''} available today."
    )

    html = f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">{heading}</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 20px">{intro}</p>
          {cards}
          <a href="{BASE_URL}/admin" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Open Admin Logs
          </a>
          <p style="color:#9ca3af;line-height:1.6;margin:18px 0 0;font-size:12px">
            Each problem is alerted at most once every 24 hours; repeats in between are
            counted, not sent. Maximum 3 alerts a day. {budget}
          </p>
        {_BODY_CLOSE}{_WRAP_CLOSE}"""

    exc = await asyncio.to_thread(_send, {
        "from": FROM,
        "to": [to_email],
        "subject": subject,
        "html": html,
    })
    return exc is None


async def send_league_added_existing(
    to_email: str,
    username: str,
    added_by_username: str,
    league_name: str,
    league_id: int,
) -> None:
    """Existing user was added to a league by another member."""
    league_url = f"{BASE_URL}/leagues/{league_id}"
    await send_async({
        "from": FROM,
        "to": [to_email],
        "subject": f'You\'ve been added to "{league_name}" on Upset Alert!',
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">You've been added to a league!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            <strong>{added_by_username}</strong> has added you to the league
            <strong>{league_name}</strong> on Upset Alert.
          </p>
          <a href="{league_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View League
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_league_invite_new_user(
    to_email: str,
    invited_by_username: str,
    league_name: str,
    invite_code: str,
) -> None:
    """No account yet — invite them to create one and join with the code."""
    register_url = f"{BASE_URL}/register"
    await send_async({
        "from": FROM,
        "to": [to_email],
        "subject": f'{invited_by_username} invited you to join "{league_name}" on Upset Alert!',
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">You've been invited!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 8px">
            <strong>{invited_by_username}</strong> has invited you to join
            <strong>{league_name}</strong> on Upset Alert — a free fantasy tennis bracket game.
          </p>
          <p style="color:#444;line-height:1.6;margin:0 0 20px">
            Create a free account, then join the league using this invite code:
          </p>
          <div style="background:#f4f6f9;border-radius:8px;padding:16px 20px;margin:0 0 24px;text-align:center">
            <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:#666;margin-bottom:6px">Invite Code</div>
            <div style="font-size:28px;font-weight:700;letter-spacing:0.12em;font-family:monospace">{invite_code}</div>
          </div>
          <a href="{register_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Create Account
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })
