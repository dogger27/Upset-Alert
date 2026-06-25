import asyncio
import logging
from typing import Optional

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

FROM = "Upset Alert <info@upsetalert.ca>"
BASE_URL = "https://upsetalert.ca"

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

_WRAP_OPEN  = '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb">'
_WRAP_CLOSE = '</div>'
_BODY_OPEN  = '<div style="padding:28px 24px">'
_BODY_CLOSE = '</div>'


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
    exc = await asyncio.to_thread(_send, params)
    if exc is not None:
        from app.services.system_log import app_log
        to = params.get("to", [])
        subject = params.get("subject", "")
        await app_log("error", "notifications", f"Email send failed: {subject!r} — {exc}",
                      {"to": to, "subject": subject, "error": str(exc)})


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
        "subject": f"{new_username} joined {league_name}",
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
    emails: list[str], tournament_name: str, year: int, tournament_id: int
) -> None:
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    await send_async({
        "from": FROM,
        "to": emails,
        "subject": f"Play has started — {tournament_name} {year}",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
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
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_draw_notification(emails: list[str], tournament_name: str, tournament_id: int) -> None:
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    await send_async({
        "from": FROM,
        "to": emails,
        "subject": f"Draw released: {tournament_name}",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">The draw is live!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 24px">
            The draw for <strong>{tournament_name}</strong> has been released.
            Head over to make your picks before play begins.
          </p>
          <a href="{tournament_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Make Your Picks
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_tournament_complete_notification(
    email: str,
    tournament_name: str,
    year: int,
    tournament_id: int,
    groups: list[tuple],  # [(group_name, rank, total_participants, points), ...]
) -> None:
    """One email per user covering their standing in every group they participated in."""
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    rows = "".join(
        f"<tr>"
        f"<td style='padding:8px 12px'>{name}</td>"
        f"<td style='padding:8px 12px;text-align:center'>#{rank}&nbsp;/&nbsp;{total}</td>"
        f"<td style='padding:8px 12px;text-align:right'>{int(pts)}&nbsp;pts</td>"
        f"</tr>"
        for name, rank, total, pts in groups
    )
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": f"{tournament_name} {year} — your final standings",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">{tournament_name} {year} is complete!</h1>
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
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_round_complete_notification(
    email: str,
    tournament_name: str,
    year: int,
    tournament_id: int,
    round_name: str,
    groups: list[tuple],  # [(group_name, rank, total_participants, points), ...]
) -> None:
    """One email per user showing their standing in each group after a round."""
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    rows = "".join(
        f"<tr>"
        f"<td style='padding:8px 12px'>{name}</td>"
        f"<td style='padding:8px 12px;text-align:center'>#{rank}&nbsp;/&nbsp;{total}</td>"
        f"<td style='padding:8px 12px;text-align:right'>{int(pts)}&nbsp;pts</td>"
        f"</tr>"
        for name, rank, total, pts in groups
    )
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": f"{tournament_name} {year} — {round_name} complete",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">{round_name} is complete!</h1>
          <p style="color:#444;line-height:1.6;margin:0 0 12px">Here are your standings after {round_name}
            at <strong>{tournament_name} {year}</strong>:</p>
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
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })


async def send_round_standings(
    emails: list[str],
    tournament_name: str,
    tournament_id: int,
    round_name: str,
    standings: list[dict],
) -> None:
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    rows = "".join(
        f"<tr><td style='padding:8px 12px'>{i+1}</td>"
        f"<td style='padding:8px 12px'>{s['username']}</td>"
        f"<td style='padding:8px 12px;text-align:right'>{s['score']}</td></tr>"
        for i, s in enumerate(standings[:10])
    )
    await send_async({
        "from": FROM,
        "to": emails,
        "subject": f"{tournament_name} — {round_name} standings",
        "html": f"""{_WRAP_OPEN}{_LOGO_HEADER}{_BODY_OPEN}
          <h1 style="font-size:22px;margin:0 0 12px">{round_name} complete</h1>
          <p style="color:#444;margin:0 0 12px">Here are the current standings for
            <strong>{tournament_name}</strong>:</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px;margin:0 0 20px">
            <thead>
              <tr style="background:#f3f4f6">
                <th style="padding:8px 12px;text-align:left">#</th>
                <th style="padding:8px 12px;text-align:left">Player</th>
                <th style="padding:8px 12px;text-align:right">Score</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <a href="{tournament_url}" style="display:inline-block;padding:12px 24px;
             background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Full Standings
          </a>
        {_BODY_CLOSE}{_WRAP_CLOSE}""",
    })
