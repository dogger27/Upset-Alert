"""
Compare Sofascore's shadow verdicts against ESPN's real ones.

This is the evidence that decides whether Sofascore may take over
`winner_id` / `completed_at` / `scores_json`. Nothing here writes; it reads the
shadow columns sofascore_results fills and reports where the two sources
disagree.

    docker compose -f docker-compose.staging.yml exec backend \
        python -m scripts.sofa_diff

What to look for, in order of how much it matters:

  WINNER MISMATCH   Stop. Anything else is cosmetic next to this — the winner
                    drives scoring, standings, Hall of Fame and the
                    round-complete digest, and a bad notification cannot be
                    un-sent.
  MISSING           Sofascore has no verdict for a match ESPN finished. Either
                    the sweep has not reached it, the players were never
                    stamped, or the event is not in that season's feed.
  SCORE MISMATCH    Usually a tiebreak-annotation difference and usually
                    harmless, but read them: a genuinely different set score
                    means one source is describing a different match.
  TIMING            How much earlier or later Sofascore observes completion.
                    Not a fault — it shifts when notifications fire, which is a
                    decision, not a bug.
"""

import argparse
import asyncio
import sys

# Import every model module before touching the registry, or SQLAlchemy fails
# to resolve relationship targets it has not seen yet.
from app.models import league, schedule, setting, tournament, user  # noqa: F401
from app.database import AsyncSessionLocal
from app.models.tournament import Draw, DrawEntry, Match
from sqlalchemy import select


def _fmt(scores) -> str:
    if not scores:
        return "-"
    return " ".join(f"{a}-{b}" for a, b in zip(scores[0], scores[1]))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", type=int, help="restrict to one draw id")
    ap.add_argument("--verbose", action="store_true",
                    help="list agreeing matches too")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        q = select(Draw).where(Draw.sofa_tournament_id.isnot(None))
        if args.draw:
            q = q.where(Draw.id == args.draw)
        draws = (await db.execute(q)).scalars().all()
        if not draws:
            print("no draws carry Sofascore ids — run scripts.resolve_sofascore first")
            return 1

        names = {r[0]: r[1] for r in (await db.execute(
            select(DrawEntry.id, DrawEntry.name))).all()}

        totals = dict(agree=0, winner_mismatch=0, missing=0, extra=0,
                      score_mismatch=0, score_agree=0)
        deltas = []

        for d in draws:
            matches = (await db.execute(
                select(Match).where(Match.draw_id == d.id,
                                    Match.is_bye == False))).scalars().all()  # noqa: E712
            header = f"\n=== draw {d.id}  {d.gender}  ({len(matches)} matches) ==="
            printed_header = False

            def head():
                nonlocal printed_header
                if not printed_header:
                    print(header)
                    printed_header = True

            for m in matches:
                espn, sofa = m.winner_id, m.sofa_winner_id
                if espn is None and sofa is None:
                    continue

                if espn is not None and sofa is not None:
                    if espn == sofa:
                        totals["agree"] += 1
                        if args.verbose:
                            head()
                            print(f"  ok       {names.get(espn, espn)}")
                    else:
                        totals["winner_mismatch"] += 1
                        head()
                        print(f"  WINNER MISMATCH  match {m.id}")
                        print(f"     espn says : {names.get(espn, espn)}")
                        print(f"     sofa says : {names.get(sofa, sofa)}")
                    # Scores, only where both have a verdict.
                    if m.scores_json and m.sofa_scores_json:
                        if _fmt(m.scores_json) == _fmt(m.sofa_scores_json):
                            totals["score_agree"] += 1
                        else:
                            totals["score_mismatch"] += 1
                            head()
                            print(f"  score differs    match {m.id}"
                                  f"  ({names.get(espn, espn)})")
                            print(f"     espn : {_fmt(m.scores_json)}")
                            print(f"     sofa : {_fmt(m.sofa_scores_json)}")
                    if m.completed_at and m.sofa_completed_at:
                        a = m.completed_at if m.completed_at.tzinfo else m.completed_at.replace(
                            tzinfo=__import__("datetime").timezone.utc)
                        b = m.sofa_completed_at if m.sofa_completed_at.tzinfo else \
                            m.sofa_completed_at.replace(
                                tzinfo=__import__("datetime").timezone.utc)
                        deltas.append((b - a).total_seconds() / 60.0)
                elif espn is not None:
                    totals["missing"] += 1
                    head()
                    print(f"  missing in sofa  match {m.id}"
                          f"  espn winner: {names.get(espn, espn)}")
                else:
                    # Sofascore has a result ESPN does not. Not necessarily
                    # wrong — ESPN is often minutes behind, and it covers
                    # neither doubles nor qualifying at all.
                    totals["extra"] += 1
                    head()
                    print(f"  sofa ahead       match {m.id}"
                          f"  sofa winner: {names.get(sofa, sofa)}")

        print("\n" + "=" * 58)
        print(f"  winners agreed        : {totals['agree']}")
        print(f"  WINNER MISMATCHES     : {totals['winner_mismatch']}")
        print(f"  espn only (sofa gap)  : {totals['missing']}")
        print(f"  sofa only (espn lag)  : {totals['extra']}")
        print(f"  scores agreed         : {totals['score_agree']}")
        print(f"  score differences     : {totals['score_mismatch']}")
        if deltas:
            avg = sum(deltas) / len(deltas)
            print(f"  completion timing     : sofa {'later' if avg > 0 else 'earlier'} "
                  f"by {abs(avg):.1f} min on average "
                  f"(min {min(deltas):+.1f}, max {max(deltas):+.1f}, n={len(deltas)})")

        decided = totals["agree"] + totals["winner_mismatch"]
        print()
        if totals["winner_mismatch"]:
            print("  VERDICT: not safe to cut over. Every winner must agree.")
            return 2
        if decided < 20:
            print(f"  VERDICT: too little evidence yet ({decided} decided matches). "
                  "Let it run through a full tournament.")
            return 0
        print(f"  VERDICT: {decided} decided matches, zero winner mismatches. "
              "Cutting over looks safe on this evidence.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
