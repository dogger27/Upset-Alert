import asyncio
import logging
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
    """Return 'Wimbledon Men' for GS or 'Canadian Open ATP1000' for tour events."""
    cat = (category or "").upper()
    is_gs = "SLAM" in cat or "GRAND" in cat
    if is_gs:
        return f"{tournament_name} {'Men' if gender == 'M' else 'Women'}"
    tour = "ATP" if gender == "M" else "WTA"
    tier = "1000" if "1000" in cat else "500" if "500" in cat else "250"
    return f"{tournament_name} {tour}{tier}"


def _setup():
    resend.api_key = settings.resend_api_key


def _send(params: resend.Emails.SendParams) -> Optional[Exception]:
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
        await app_log("error", "notifications", f"Email send failed: {subject!r} → {recipient}",
                      {"to": to, "subject": subject, "error": str(exc)})
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


async def send_new_user_notification(new_email: str, new_username: str) -> None:
    await send_async({
        "from": FROM,
        "to": ["pdwiens@gmail.com"],
        "subject": f"New user: {new_username}",
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <p><strong>{new_username}</strong> ({new_email}) just verified their account on Upset Alert.</p>
        </div>
        """,
    })


async def send_match_start_notification(
    emails: list[str], tournament_name: str, year: int, tournament_id: int,
    category: str = "", gender: str = "M",
) -> None:
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    label = _tournament_label(tournament_name, category, gender)
    html = f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">The first match is underway!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            <strong>{tournament_name} {year}</strong> is officially live — a main-draw match
            has just started. Your picks are now locked.
          </p>
          <a href="{tournament_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Draw &amp; Picks
          </a>
          <p style="margin-top:24px;font-size:13px;color:#888">
            Good luck — let's see those upsets!
          </p>
        {_BODY_CLOSE}{_WRAP_CLOSE}"""
    for email in emails:
        await send_async({
            "from": FROM,
            "to": [email],
            "subject": f"Play has started — {label}",
            "html": html,
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

    if is_followup:
        # The week's digest already went out; these arrived late.
        subject = (f"One more draw is live — {draws[0]['name']}" if n == 1
                   else f"{n} more draws are live — week of {week_label}")
        heading = (f"One more draw for the week of {week_label}" if n == 1
                   else f"{count_word} more draws for the week of {week_label}")
        intro = ("It wasn't out when we sent the rest of this week's draws. It's live now."
                 if n == 1 else
                 "They weren't out when we sent the rest of this week's draws. They're live now.")
    else:
        subject = (f"Draw released: {draws[0]['name']}" if n == 1
                   else f"{n} draws are live — week of {week_label}")
        heading = "The draw is live!" if n == 1 else "This week's draws are live"
        intro = (f"The draw for <strong>{draws[0]['name']}</strong> has been released."
                 if n == 1 else
                 f"{count_word} draws opened for the week of <strong>{week_label}</strong>. "
                 f"Soonest deadline first.")

    rows = "".join(_digest_row(d, last=(i == n - 1)) for i, d in enumerate(draws))
    cta_url = f"{BASE_URL}/tournaments/{draws[0]['id']}" if n == 1 else f"{BASE_URL}/tournaments"
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


def _match_result_row(i: int, winner_last: str, loser_last: str, score: str, is_correct: bool) -> str:
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
        f'{winner_last} def. {loser_last}</td>'
        f'<td align="right" style="padding:8px 12px;font-size:14px;color:#444;'
        f'white-space:nowrap;text-align:right">{score}</td>'
        f'</tr>'
    )


def _round_results_widget(round_name: str, results: list[tuple]) -> str:
    """Always-visible match-results panel. Gmail (web and mobile app) strips
    <style> tags and doesn't support the CSS-only ":checked" accordion trick,
    so this is plain static markup rather than a collapsible widget.
    results: [(winner_last, loser_last, score, is_correct), ...] in bracket order,
    where is_correct reflects this recipient's own pick for that match."""
    if not results:
        return ""
    rows = "".join(
        _match_result_row(i, w, l, s, c)
        for i, (w, l, s, c) in enumerate(results)
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
    match_results: Optional[list[tuple]] = None,  # [(winner_last, loser_last, score, is_correct), ...]
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
        f'<td style="padding:8px 12px 8px 14px;font-size:14px;color:#111">{label}</td>'
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
        draw["label"],
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
    cta_url = f"{BASE_URL}/tournaments/{draws[0]['id']}" if len(draws) == 1 else f"{BASE_URL}/tournaments"
    cta_text = "View Draw &amp; Standings" if len(draws) == 1 else "View This Week&#39;s Draws"

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
