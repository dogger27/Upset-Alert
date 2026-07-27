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


async def send_draw_notification(
    emails: list[str], tournament_name: str, tournament_id: int,
    category: str = "", gender: str = "M",
) -> None:
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    label = _tournament_label(tournament_name, category, gender)
    html = f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">The draw is live!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            The draw for <strong>{tournament_name}</strong> has been released.
            Head over to make your picks before play begins.
          </p>
          <a href="{tournament_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Make Your Picks
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}"""
    for email in emails:
        await send_async({
            "from": FROM,
            "to": [email],
            "subject": f"Draw released: {label}",
            "html": html,
        })


async def send_tournament_complete_notification(
    email: str,
    tournament_name: str,
    year: int,
    tournament_id: int,
    groups: list[tuple],  # [(group_name, rank, total_participants, points), ...]
    category: str = "",
    gender: str = "M",
    unsubscribe_url: str = "",
) -> None:
    """One email per user covering their standing in every group they participated in.

    Draw Completion is its own notification type with its own opt-out — the
    unsubscribe link here drops only the 'tournament_end' preference, leaving
    round-completion emails untouched.
    """
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    label = _tournament_label(tournament_name, category, gender)
    rows = "".join(
        f"<tr>"
        f"<td style='padding:8px 12px'>{name}</td>"
        f"<td style='padding:8px 12px;text-align:center'>#{rank}&nbsp;/&nbsp;{total}</td>"
        f"<td style='padding:8px 12px;text-align:right'>{int(pts)}&nbsp;pts</td>"
        f"</tr>"
        for name, rank, total, pts in groups
    )
    # Standalone footer, outside the card entirely — mirrors the round-complete email.
    unsubscribe = (
        f'<p style="max-width:560px;margin:16px auto 0;text-align:center;font-size:12px;color:#9ca3af">'
        f'<a href="{unsubscribe_url}" style="color:#9ca3af;text-decoration:underline">'
        f'Unsubscribe from draw-completion emails</a></p>'
        if unsubscribe_url else ""
    )
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": f"{label} {year} - Final Standings",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">{label} {year} is complete!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 12px">Here are your final standings across all groups:</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px;margin:0 0 20px">
            <thead>
              <tr style="background:#f3f4f6">
                <th style="padding:8px 12px;text-align:left">League</th>
                <th style="padding:8px 12px;text-align:center">Rank</th>
                <th style="padding:8px 12px;text-align:right">Points</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <a href="{tournament_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Draw &amp; Standings
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}
        {unsubscribe}""",
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
