"""
Sofascore against ESPN, measured — the numbers, with nobody printing them.

Lifted out of scripts/sofa_diff.py so that the report a human reads and the gate
that decides the cutover are computed by the SAME code. Two implementations of
"do these sources agree" would eventually disagree with each other, and the one
that mattered would be the one nobody was looking at.

Nothing here writes. It reads both column sets off `matches` and counts.

The distinction that runs through all of it is BEFORE and AFTER the sweep began.
`sofa_completed_at` means "when this sweep first noticed", so for a match ESPN
finished days before the sweep existed it records when we deployed, not who
reported faster. Every figure therefore comes in two forms: the all-time count,
which is the fair summary of coverage, and the count restricted to matches that
finished while BOTH sources were watching, which is the only thing that says
what would happen if Sofascore were in charge tomorrow.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models.tournament import Draw, DrawEntry, Match


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_scores(scores) -> str:
    """A scores_json as one comparable line: "7(7)-6(4) 6-3"."""
    if not scores:
        return "—"
    a, b = (scores + [[], []])[:2]
    return " ".join(f"{x}-{y}" for x, y in zip(a, b))


def _marked(js) -> bool:
    """Does this scoreline carry a retirement or walkover marker?

    ESPN writes a trailing "r" on the set a player quit in. It is not cosmetic:
    the bracket renders a "ret." badge from it, and a retirement scored as a
    clean win is a different match.
    """
    return bool(js) and any(
        "r" in str(c).lower() or "w/o" in str(c).lower()
        for side in js for c in side)


async def compare(db, draw_ids=None) -> dict:
    """Every disagreement between the two sources, counted and listed.

    Returns totals, the per-match findings (so a report can print them), and
    `deltas` — completion lag in minutes, positive meaning Sofascore was later,
    for matches that finished while both sources were watching.
    """
    q = select(Draw).where(Draw.sofa_tournament_id.isnot(None))
    if draw_ids:
        q = q.where(Draw.id.in_(draw_ids))
    draws = (await db.execute(q)).scalars().all()
    if not draws:
        return {"draws": 0, "findings": [], "deltas": [], "totals": {}}

    names = {r[0]: r[1] for r in (await db.execute(
        select(DrawEntry.id, DrawEntry.name))).all()}

    # When the sweep first ran. Everything ESPN completed before this is
    # historical backfill as far as any "would this work now" question goes.
    first = (await db.execute(
        select(Match.sofa_completed_at)
        .where(Match.sofa_completed_at.isnot(None))
        .order_by(Match.sofa_completed_at).limit(1))).scalar_one_or_none()
    sweep_start = _aware(first) or datetime.max.replace(tzinfo=timezone.utc)

    totals = dict(agree=0, winner_mismatch=0, missing=0, extra=0,
                  score_agree=0, score_mismatch=0, retirement_lost=0,
                  missing_recent=0, score_mismatch_recent=0)
    findings = []
    deltas = []

    for d in draws:
        matches = (await db.execute(
            select(Match).where(Match.draw_id == d.id,
                                Match.is_bye == False))).scalars().all()  # noqa: E712
        for m in matches:
            espn, sofa = m.winner_id, m.sofa_winner_id
            if espn is None and sofa is None:
                continue
            # Did this finish under the current regime, or before it?
            recent = bool(m.completed_at and _aware(m.completed_at) >= sweep_start)

            if espn is not None and sofa is not None:
                if espn == sofa:
                    totals["agree"] += 1
                else:
                    totals["winner_mismatch"] += 1
                    findings.append({
                        "kind": "winner_mismatch", "draw": d.id, "match": m.id,
                        "recent": recent,
                        "espn": names.get(espn, espn), "sofa": names.get(sofa, sofa),
                    })

                if _marked(m.scores_json) and not _marked(m.sofa_scores_json):
                    totals["retirement_lost"] += 1
                    findings.append({
                        "kind": "retirement_lost", "draw": d.id, "match": m.id,
                        "recent": recent, "player": names.get(espn, espn),
                        "espn": fmt_scores(m.scores_json),
                        "sofa": fmt_scores(m.sofa_scores_json),
                    })

                if m.scores_json and m.sofa_scores_json:
                    if fmt_scores(m.scores_json) == fmt_scores(m.sofa_scores_json):
                        totals["score_agree"] += 1
                    else:
                        totals["score_mismatch"] += 1
                        if recent:
                            totals["score_mismatch_recent"] += 1
                        findings.append({
                            "kind": "score_mismatch", "draw": d.id, "match": m.id,
                            "recent": recent, "player": names.get(espn, espn),
                            "espn": fmt_scores(m.scores_json),
                            "sofa": fmt_scores(m.sofa_scores_json),
                        })

                if m.completed_at and m.sofa_completed_at and recent:
                    deltas.append((_aware(m.sofa_completed_at)
                                   - _aware(m.completed_at)).total_seconds() / 60.0)

            elif espn is not None:
                totals["missing"] += 1
                if recent:
                    totals["missing_recent"] += 1
                findings.append({
                    "kind": "missing", "draw": d.id, "match": m.id,
                    "recent": recent, "espn": names.get(espn, espn),
                })
            else:
                # Sofascore has a result ESPN does not. Not wrong in itself —
                # ESPN runs minutes behind, and covers neither doubles nor
                # qualifying at all.
                totals["extra"] += 1
                findings.append({
                    "kind": "extra", "draw": d.id, "match": m.id,
                    "recent": recent, "sofa": names.get(sofa, sofa),
                })

    totals["decided"] = totals["agree"] + totals["winner_mismatch"]
    return {
        "draws": len(draws),
        "sweep_start": sweep_start,
        "totals": totals,
        "findings": findings,
        "deltas": deltas,
    }


def timing(deltas) -> dict:
    """Completion lag, summarised. Positive means Sofascore reported later."""
    if not deltas:
        return {"n": 0}
    return {
        "n": len(deltas),
        "avg": sum(deltas) / len(deltas),
        "min": min(deltas),
        "max": max(deltas),
        "worst": max(abs(d) for d in deltas),
    }
