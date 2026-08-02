"""One-off: resend a round-complete standings email to a single user for testing.

Runs against the live DB inside the container, e.g.:

    docker exec app-backend-1 python -m app.scripts.send_test_round_email \
        --email pdwiens@gmail.com --tournament Wimbledon --gender M --round R32

It reuses the real notify_round_complete path (force=True bypasses the resend
guard and does NOT claim the (draw, round) slot, so the real batch is unaffected;
only_user_ids scopes delivery to the one recipient).
"""
import argparse
import asyncio

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Draw
from app.models.user import User
from app.services.notifications import notify_round_complete, _email_round_label


async def _main(email: str, name_like: str, gender: str, round_label: str) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if not user:
            print(f"ERROR: no user with email {email!r}")
            return
        print(f"User: id={user.id} username={user.username!r} email={user.email!r} "
              f"verified={user.email_verified}")

        # Pick the matching main-draw event: newest year, most rounds (singles main draw).
        draws = (await db.execute(
            select(Draw)
            .where(Draw.gender == gender, Draw.name.ilike(f"%{name_like}%"))
            .order_by(Draw.year.desc(), Draw.num_rounds.desc(), Draw.id.desc())
        )).scalars().all()
        if not draws:
            print(f"ERROR: no {gender} draw matching {name_like!r}")
            return
        for d in draws:
            print(f"  candidate draw: id={d.id} {d.year} {d.name!r} "
                  f"cat={d.category!r} rounds={d.num_rounds}")
        draw = draws[0]
        print(f"Using draw: id={draw.id} {draw.year} {draw.name!r} rounds={draw.num_rounds}")

        # Resolve the round_number whose label matches (e.g. 'R32').
        round_number = None
        for rn in range(1, (draw.num_rounds or 0) + 1):
            if _email_round_label(draw.round_name(rn)) == round_label:
                round_number = rn
                break
        if round_number is None:
            labels = [(_rn, _email_round_label(draw.round_name(_rn)))
                      for _rn in range(1, (draw.num_rounds or 0) + 1)]
            print(f"ERROR: round {round_label!r} not found. Available: {labels}")
            return
        print(f"Round: {round_label} -> round_number={round_number}")

        # Eligibility check (mirrors notify_round_complete: needs ≥1 pick).
        total_matches = await db.scalar(
            select(func.count()).where(Match.draw_id == draw.id, Match.is_bye == False)
        )
        my_preds = await db.scalar(
            select(func.count()).where(
                UserPrediction.draw_id == draw.id,
                UserPrediction.user_id == user.id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        print(f"Eligibility: predictions={my_preds} / non-bye matches={total_matches}")
        if not total_matches or not my_preds:
            print("ABORT: user is not eligible (no picks in this draw) — email would not send.")
            return

    print("Sending forced, single-recipient round-complete email ...")
    await notify_round_complete(draw.id, round_number, only_user_ids={user.id}, force=True)
    print("Done — check the inbox.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--tournament", default="Wimbledon")
    ap.add_argument("--gender", default="M")
    ap.add_argument("--round", dest="round_label", default="R32")
    a = ap.parse_args()
    asyncio.run(_main(a.email, a.tournament, a.gender, a.round_label))
