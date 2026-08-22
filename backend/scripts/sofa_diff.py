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

The numbers come from services/sofa_compare.py and the verdict from the same
gate the automatic cutover uses (services/sofa_cutover.evaluate), so what this
prints and what the running site will decide can never drift apart. This is a
window onto that decision, not a second opinion about it.
"""

import argparse
import asyncio
import sys

# SQLAlchemy resolves relationship strings against a registry that only
# app.main fully populates. Import every model module first, or select(Draw)
# fails on a name it has never seen — 'League', 'UserPrediction', and so on.
# Same list, and the same reason, as scripts/resolve_sofascore.py.
for _m in ("league", "user", "prediction", "notification", "push", "alert",
           "draw_history", "h2h", "rankings", "setting", "system_log",
           "tournament", "schedule"):
    try:
        __import__(f"app.models.{_m}")
    except ModuleNotFoundError:
        pass

from app.database import AsyncSessionLocal              # noqa: E402
from app.services.sofa_compare import compare, timing   # noqa: E402
from app.services.sofa_cutover import evaluate          # noqa: E402
async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", type=int, help="restrict to one draw id")
    ap.add_argument("--all", action="store_true",
                    help="list findings from before the sweep started too")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        result = await compare(db, [args.draw] if args.draw else None)

    if not result.get("draws"):
        print("no draws carry Sofascore ids — run scripts.resolve_sofascore first")
        return 1

    t = result["totals"]
    lag = timing(result["deltas"])

    shown = [f for f in result["findings"] if args.all or f["recent"]
             or f["kind"] in ("winner_mismatch", "retirement_lost")]
    if shown:
        for f in shown:
            age = "" if f["recent"] else "  (before the sweep started)"
            if f["kind"] == "winner_mismatch":
                print(f"  WINNER MISMATCH  match {f['match']}{age}")
                print(f"     espn says : {f['espn']}")
                print(f"     sofa says : {f['sofa']}")
            elif f["kind"] == "retirement_lost":
                print(f"  retirement lost  match {f['match']}  ({f['player']}){age}")
                print(f"     espn : {f['espn']}")
                print(f"     sofa : {f['sofa']}")
            elif f["kind"] == "score_mismatch":
                print(f"  score differs    match {f['match']}  ({f['player']}){age}")
                print(f"     espn : {f['espn']}")
                print(f"     sofa : {f['sofa']}")
            elif f["kind"] == "missing":
                print(f"  missing in sofa  match {f['match']}  espn winner: {f['espn']}{age}")
            else:
                print(f"  sofa ahead       match {f['match']}  sofa winner: {f['sofa']}{age}")
        print()
    elif not args.all and result["findings"]:
        print(f"({len(result['findings'])} findings, all from before the sweep "
              f"started — pass --all to list them)\n")

    print("=" * 58)
    print(f"  winners agreed        : {t['agree']}")
    print(f"  WINNER MISMATCHES     : {t['winner_mismatch']}")
    print(f"  espn only (sofa gap)  : {t['missing']}  (since sweep: {t['missing_recent']})")
    print(f"  sofa only (espn lag)  : {t['extra']}")
    print(f"  scores agreed         : {t['score_agree']}")
    print(f"  score differences     : {t['score_mismatch']}  (since sweep: {t['score_mismatch_recent']})")
    print(f"  retirement/wo markers LOST : {t['retirement_lost']}")
    if lag["n"]:
        print(f"  completion timing     : sofa {'later' if lag['avg'] > 0 else 'earlier'} "
              f"by {abs(lag['avg']):.1f} min on average "
              f"(min {lag['min']:+.1f}, max {lag['max']:+.1f}, n={lag['n']})")
    else:
        print("  completion timing     : no match finished while both sources "
              "were watching — rerun after a live match ends")

    ok, why = evaluate(result)
    print()
    if ok:
        print("  VERDICT: gate OPEN. The site will hand Sofascore the result")
        print("           columns within the hour, by itself.")
        return 0
    print("  VERDICT: gate closed. Still wanted:")
    for w in why:
        print(f"           - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
