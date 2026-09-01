"""Replay real matches through the Live Activity throttle and count the pushes.

APNs budgets Live Activity updates and does not tell you when you have spent
them — it simply stops delivering, which freezes a wrong score on someone's
Lock Screen. There is no error to catch and no retry to make, so the policy has
to be sized BEFORE it is used, against matches that actually happened.

match_score_snapshots banks one row per content change, which is exactly the
stream the dispatcher will see. Replaying it answers the only question that
matters: how many pushes would a real five-setter have cost.

It imports classify() and the throttle from production rather than
reimplementing them. A simulation with its own copy of the policy measures the
copy, and the two drift the first time either is touched.

    docker compose exec -T backend python -m scripts.la_budget_sim
    docker compose exec -T backend python -m scripts.la_budget_sim --draw 77
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, "/app")

from app.services.live_activity import (            # noqa: E402
    MAX_TOTAL_PER_MATCH, PRIORITY_IMMEDIATE, classify, forget,
    note_sent, should_send,
)
from app.services.live_activity_content import build_content_state  # noqa: E402

DB = "/data/tennis_fantasy.db"

# Ship gates. Chosen to leave headroom under a budget Apple does not publish:
# if a real Slam final needs more than this, the policy is wrong, not the gate.
GATE_P10_PER_HOUR_P95 = 20
GATE_P10_PER_HOUR_MAX = 30
# Tied to STALE_AFTER_SECONDS rather than picked: a gap longer than the stale
# window greys the activity out mid-match. Kept just under it so the gate fails
# before a user would notice.
GATE_LONGEST_GAP_MIN = 3.5
GATE_TOTAL_P95 = 250

# Consecutive snapshots further apart than this mean the FEED stopped, not that
# the throttle held something back — a suspension, a poller outage, or a match
# that simply was not being played.
SOURCE_CONTINUOUS_SECONDS = 120


def render(snap: dict):
    """A stored snapshot in renderable_point()'s shape.

    The snapshots are written by the poller in its own format; the classifier
    reads what the API serves. Converting here keeps the classifier reading
    exactly one shape.
    """
    sets = snap.get("sets") or []
    games = [[str(s[0]) if s and s[0] is not None else "" for s in sets],
             [str(s[1]) if s and s[1] is not None else "" for s in sets]]
    return {
        "games": games if sets else None,
        "point": snap.get("point"),
        "tiebreak": bool(snap.get("tiebreak")),
        "match_tiebreak": bool(snap.get("match_tiebreak")),
        "serving": snap.get("serving"),
        "suspended": bool(snap.get("suspended")),
    }


def replay(rows):
    """One match's snapshot stream through the real policy."""
    aid = -1
    forget(aid)
    prev = None
    sent = []          # (epoch, priority, reason)
    gaps = []
    last_send = None
    last_seen = None
    # Did the FEED stop at any point since the last push? Tracked across the
    # whole window, not just between the last two snapshots — a 12-hour hole
    # in the middle of an otherwise dense stream still means we were not
    # withholding anything.
    source_broke = False
    first = last = None

    for at, raw in rows:
        try:
            snap = json.loads(raw)
        except (TypeError, ValueError):
            continue
        t = datetime.fromisoformat(at).timestamp()
        first = first or t
        last = t
        cur = render(snap)

        decision = classify(prev, cur)
        prev = cur
        if last_seen is not None and (t - last_seen) > SOURCE_CONTINUOUS_SECONDS:
            source_broke = True
        last_seen = t
        if not decision.send:
            continue

        state = build_content_state(cur, at=datetime.fromisoformat(at))
        final = should_send(aid, decision, state, now=t)
        if not final.send:
            continue
        note_sent(aid, final.priority, state, now=t)
        # ONLY COUNT A GAP WE CAUSED.
        # The question this metric answers is "did the Lock Screen look frozen
        # while play was happening" — so a gap only counts if the SNAPSHOT
        # stream was continuous across it. Overnight suspensions and poller
        # outages produce gaps of hours, and blaming the throttle for them
        # measures the feed rather than the policy. The first run of this
        # simulator reported a 19-hour gap and failed its own gate on three
        # rain-suspended US Open matches, which is exactly that mistake.
        if last_send is not None and not source_broke:
            gaps.append(t - last_send)
        source_broke = False
        last_send = t
        sent.append((t, final.priority, final.reason))

    forget(aid)
    dur_h = ((last - first) / 3600.0) if (first and last and last > first) else 0.0
    p10 = [s for s in sent if s[1] == PRIORITY_IMMEDIATE]
    return {
        "changes": len(rows),
        "sent": len(sent),
        "p10": len(p10),
        "hours": dur_h,
        "p10_per_hour": (len(p10) / dur_h) if dur_h > 0.25 else 0.0,
        "worst_p10_hour": worst_hour(p10),
        "longest_gap_min": (max(gaps) / 60.0) if gaps else 0.0,
        "reasons": Counter(s[2] for s in sent),
    }


def worst_hour(p10) -> int:
    """Most priority-10 pushes in any rolling 60 minutes — the real ceiling.

    An average hides the only case that matters: a tight fifth set where every
    game is a break and every other point is a break point.
    """
    times = [t for t, _, _ in p10]
    best = 0
    for i, t0 in enumerate(times):
        n = sum(1 for t in times[i:] if t - t0 < 3600)
        best = max(best, n)
    return best


def pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p / 100.0))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", type=int, help="limit to one draw")
    ap.add_argument("--min-changes", type=int, default=30,
                    help="skip matches too short to be informative")
    args = ap.parse_args()

    c = sqlite3.connect(DB)
    q = """SELECT s.match_id, s.at, s.snap
           FROM match_score_snapshots s"""
    params = ()
    if args.draw:
        q += " JOIN matches m ON m.id = s.match_id WHERE m.draw_id = ?"
        params = (args.draw,)
    q += " ORDER BY s.match_id, s.id"

    by_match = {}
    for mid, at, snap in c.execute(q, params):
        by_match.setdefault(mid, []).append((at, snap))

    results = []
    for mid, rows in by_match.items():
        if len(rows) < args.min_changes:
            continue
        r = replay(rows)
        r["match_id"] = mid
        results.append(r)

    if not results:
        print("no matches with enough history — try a different draw")
        return

    print(f"replayed {len(results)} matches\n")
    print(f"  {'match':>7} {'chg':>5} {'sent':>5} {'p10':>4} {'hrs':>5} "
          f"{'p10/h':>6} {'worst/h':>7} {'gap min':>8}")
    for r in sorted(results, key=lambda x: -x["sent"])[:12]:
        print(f"  {r['match_id']:>7} {r['changes']:>5} {r['sent']:>5} {r['p10']:>4} "
              f"{r['hours']:>5.1f} {r['p10_per_hour']:>6.1f} "
              f"{r['worst_p10_hour']:>7} {r['longest_gap_min']:>8.1f}")

    totals = [r["sent"] for r in results]
    worst = [r["worst_p10_hour"] for r in results]
    gaps = [r["longest_gap_min"] for r in results]

    print("\n  gates:")
    checks = [
        ("p95 priority-10 per hour", pct(worst, 95), GATE_P10_PER_HOUR_P95, "<="),
        ("max priority-10 per hour", max(worst), GATE_P10_PER_HOUR_MAX, "<="),
        ("longest in-play gap (min)", max(gaps), GATE_LONGEST_GAP_MIN, "<="),
        ("p95 total pushes / match", pct(totals, 95), GATE_TOTAL_P95, "<="),
        ("runaway breaker hit", max(totals), MAX_TOTAL_PER_MATCH, "<"),
    ]
    ok = True
    for label, got, limit, op in checks:
        good = got <= limit if op == "<=" else got < limit
        ok = ok and good
        print(f"    {'PASS' if good else 'FAIL'}  {label:28} {got:>7.1f}  {op} {limit}")

    agg = Counter()
    for r in results:
        agg.update(r["reasons"])
    print("\n  why pushes happened:",
          ", ".join(f"{k}={v}" for k, v in agg.most_common(8)))
    print("\n  " + ("ALL GATES PASS" if ok else "GATES FAILED — tune before shipping"))


if __name__ == "__main__":
    main()
