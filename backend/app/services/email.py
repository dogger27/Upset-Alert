import asyncio
import logging
from typing import Optional

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

FROM = "Upset Alert <info@upsetalert.ca>"
BASE_URL = "https://upsetalert.ca"


def _setup():
    resend.api_key = settings.resend_api_key


def _send(params: resend.Emails.SendParams) -> bool:
    _setup()
    try:
        resend.Emails.send(params)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", params.get("to"), e)
        return False


async def send_async(params: resend.Emails.SendParams) -> None:
    success = await asyncio.to_thread(_send, params)
    if not success:
        from app.services.system_log import app_log
        to = params.get("to", [])
        subject = params.get("subject", "")
        await app_log("error", "notifications", f"Email send failed: {subject!r}",
                      {"to": to, "subject": subject})


async def send_verification(email: str, username: str, token: str, code: str) -> None:
    verify_url = f"{BASE_URL}/verify-email?token={token}"
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": "Verify your Upset Alert email",
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">Hi {username}, verify your email</h1>
          <p style="color:#444;line-height:1.6">
            Enter this code on the site, or click the button below. Expires in 24 hours.
          </p>
          <div style="margin:24px 0;text-align:center">
            <span style="display:inline-block;font-size:36px;font-weight:700;letter-spacing:10px;
                         padding:16px 24px;background:#f3f4f6;border-radius:8px;color:#111">
              {code}
            </span>
          </div>
          <a href="{verify_url}" style="display:inline-block;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Verify Email
          </a>
        </div>
        """,
    })


async def send_welcome(email: str, username: str) -> None:
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": "Welcome to Upset Alert!",
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">Welcome to Upset Alert, {username}!</h1>
          <p style="color:#444;line-height:1.6">
            You're all set to start picking upsets and climbing the leaderboard.
            Head over to the site to join a league and make your first picks.
          </p>
          <a href="{BASE_URL}" style="display:inline-block;margin-top:24px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Go to Upset Alert
          </a>
        </div>
        """,
    })


async def send_password_reset(email: str, reset_token: str) -> None:
    reset_url = f"{BASE_URL}/reset-password?token={reset_token}"
    await send_async({
        "from": FROM,
        "to": [email],
        "subject": "Reset your Upset Alert password",
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">Reset your password</h1>
          <p style="color:#444;line-height:1.6">
            Click the button below to reset your password. This link expires in 1 hour.
          </p>
          <a href="{reset_url}" style="display:inline-block;margin-top:24px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Reset Password
          </a>
          <p style="margin-top:24px;font-size:13px;color:#888">
            If you didn't request this, you can safely ignore this email.
          </p>
        </div>
        """,
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
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">The first match is underway!</h1>
          <p style="color:#444;line-height:1.6">
            <strong>{tournament_name} {year}</strong> is officially live — a main-draw match
            has just started. Your picks are now locked.
          </p>
          <a href="{tournament_url}" style="display:inline-block;margin-top:24px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Draw &amp; Picks
          </a>
          <p style="margin-top:24px;font-size:13px;color:#888">
            Good luck — let's see those upsets!
          </p>
        </div>
        """,
    })


async def send_draw_notification(emails: list[str], tournament_name: str, tournament_id: int) -> None:
    tournament_url = f"{BASE_URL}/tournaments/{tournament_id}"
    await send_async({
        "from": FROM,
        "to": emails,
        "subject": f"Draw released: {tournament_name}",
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">The draw is live!</h1>
          <p style="color:#444;line-height:1.6">
            The draw for <strong>{tournament_name}</strong> has been released.
            Head over to make your picks before play begins.
          </p>
          <a href="{tournament_url}" style="display:inline-block;margin-top:24px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            Make Your Picks
          </a>
        </div>
        """,
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
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">{tournament_name} {year} is complete!</h1>
          <p style="color:#444;line-height:1.6">Here are your final standings across all groups:</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0">
            <thead>
              <tr style="background:#f3f4f6">
                <th style="padding:8px 12px;text-align:left">Group</th>
                <th style="padding:8px 12px;text-align:center">Rank</th>
                <th style="padding:8px 12px;text-align:right">Points</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <a href="{tournament_url}" style="display:inline-block;margin-top:8px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Draw &amp; Standings
          </a>
        </div>
        """,
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
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">{round_name} is complete!</h1>
          <p style="color:#444;line-height:1.6">Here are your standings after {round_name}
            at <strong>{tournament_name} {year}</strong>:</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0">
            <thead>
              <tr style="background:#f3f4f6">
                <th style="padding:8px 12px;text-align:left">Group</th>
                <th style="padding:8px 12px;text-align:center">Rank</th>
                <th style="padding:8px 12px;text-align:right">Points</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <a href="{tournament_url}" style="display:inline-block;margin-top:8px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Draw &amp; Standings
          </a>
        </div>
        """,
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
        "html": f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
          <h1 style="font-size:24px;margin-bottom:8px">{round_name} complete</h1>
          <p style="color:#444;margin-bottom:16px">Here are the current standings for
            <strong>{tournament_name}</strong>:</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px">
            <thead>
              <tr style="background:#f3f4f6">
                <th style="padding:8px 12px;text-align:left">#</th>
                <th style="padding:8px 12px;text-align:left">Player</th>
                <th style="padding:8px 12px;text-align:right">Score</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <a href="{tournament_url}" style="display:inline-block;margin-top:24px;padding:12px 24px;
             background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">
            View Full Standings
          </a>
        </div>
        """,
    })
