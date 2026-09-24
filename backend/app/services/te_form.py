"""A player's form from Tennis Explorer — the whole ladder, in one page.

WHY THIS EXISTS (owner, 2026-09-23). The Form panel was computed from our own
`matches` table, which holds the tour draws this app has scraped and nothing
else — so a qualifier, a Challenger regular or anyone whose last month was
Futures arrived with an empty form line, which is the reader's first question
about a name they do not know. Our database holds 4,911 completed matches in
total; one lower-ranked player's TE page holds 42 played matches for 2026
alone.

WHY TENNIS EXPLORER AND NOT SOFASCORE. Sofascore's `/team/{id}/events/last/0`
does the same job in one request and was measured doing it (see the memory
`reference_sofascore_data_model`, "the whole ladder"). It loses on the two
things that decide it here:

  identity   `te_slug` is on 4,474 of our 4,482 draw entries; `sofa_player_id`
             is on 684. Sofascore would need an identity lookup for 85% of
             players before it could ask about form — extra requests to the one
             source that answers 403 and bans the egress IP.
  standing   "NEVER bulk-collect from Sofascore" and "not getting blocked is
             the top priority" are the owner's rules. A form line is opened per
             match, and a draw page's worth of them is a sweep. Tennis Explorer
             serves this server unchallenged, caches an hour on disk, and is
             already the source of the head-to-head beside this very panel.

And TE's row carries MORE than the endpoint we would have had to risk: the real
played date (our own `completed_at` is the scrape time for backfilled draws),
the surface, the winner, the score with tiebreak detail, the round including
qualifying, the opponent's own slug — no name matching — and the match-detail id
if per-match statistics are ever wanted.

WHAT THE PAGE LOOKS LIKE. `/player/{slug}/` is the current season;
`?annual=YYYY` is any other. Its match tables are one block per tournament: a
`tr.head.flags` naming the event (and linking to `/{slug}/{year}/{tour}/`),
then `tr.one` / `tr.two` rows. THREE row shapes share those classes and only
one is a match:

  a match     `td.first.time` with the day, `td.s-color` with the surface in a
              title, `td.t-name` with the players as anchors, `td.round`,
              `td.tl` with the score, two `td.course` with the odds
  a fixture   the same, with an empty `td.tl` — not played, so not form
  a summary   the season win/loss table at the foot of the page, which has a
              `td.year` and no players at all

An earlier reading of this page saw only the third and concluded TE had no
per-match history (the memory `reference_h2h_form_feature` said so until
today). It has.

THE WINNER IS LISTED FIRST, which is the one convention this parser rests on,
so it was proved rather than assumed: Muller's 22.09 row lists him first and
our own `schedule_entries.winner_side` says he won that day; his 26.08 row
lists him second and our data says he lost. Both checked before this file was
written.
"""
import html as _html
import logging
import re
from datetime import date
from typing import Optional

from app.services.te_rounds import normalize_qual_round

logger = logging.getLogger(__name__)

# Thirty is the owner's number, and it is also what one season's page holds for
# a busy lower-ranked player — so the common case is one request.
FORM_LIMIT = 30
# Two seasons at most. A tour player's current-season page already covers nine
# months; anyone whose page is thin is thin because they did not play, and a
# third page would buy a fourth-year result nobody reads as "form".
MAX_SEASONS = 2

_TR = re.compile(r'<tr class="(head flags|one|two)[^"]*">(.*?)</tr>', re.S)
# THE HEADER'S CELL, AND ITS LINK ONLY IF IT HAS ONE. Reading the anchor
# directly lost the whole block: a header TE prints without a link — a team
# competition, an exhibition — left the event blank for every row under it,
# and the app drew a form line with no tournament on it (owner, 2026-09-23:
# "why is some tournament name or info not showing up?!?"). The cell always
# holds the name; the link is where the rung and the tour live when there is
# one.
_HEAD_CELL = re.compile(r'<td class="t-name"[^>]*>(.*?)</td>', re.S)
_HEAD_LINK = re.compile(r'<a href="([^"]*)"')
_DAY = re.compile(r'class="first time">\s*(\d{1,2})\.(\d{1,2})\.')
_SURFACE = re.compile(r'class="s-color"><span title="([^"]*)"')
_NAMES = re.compile(r'<td class="t-name">(.*?)</td>', re.S)
# TWO ANCHORS ARE TWO SIDES, whoever is on them. A singles row links
# `/player/{slug}/`; a DOUBLES row links the pair as one team,
# `/doubles-team/{slugA}/{slugB}/`, with the full names in a `title` and the
# visible text abbreviated to five letters a name ("Harri / Kraji"). Reading
# anchors as players found nothing on a doubles specialist's page — all 49 of
# Austin Krajicek's played matches parsed as zero — which is what sent this
# regex looking for the side rather than the person.
_SIDE = re.compile(r'<a href="/(player|doubles-team)/([^"]+?)/?"([^>]*)>(.*?)</a>', re.S)
_TITLE = re.compile(r'title="([^"]*)"')
_SCORE = re.compile(r'class="tl"><a[^>]*>(.*?)</a>', re.S)
_ROUND = re.compile(r'<td class="round"(?:\s+title="([^"]*)")?[^>]*>(.*?)</td>', re.S)
_YEAR_ROW = re.compile(r'<td class="year">')
_SEASON = re.compile(r'<td class="year"><a[^>]*annual=(\d{4})[^"]*"\s+class="bold"')
_TAGS = re.compile(r"<[^>]+>")
# A TIEBREAK IS A SUPERSCRIPT ON THIS PAGE: `6<sup>6</sup>-7` is 6-7 in the
# breaker, 7-6 to the other side. Stripping the markup first turned it into
# "6 6 -7", which reads as a set score that cannot exist — so the digits come
# down into the bracket the sport writes them in before any tag is dropped.
_SUP = re.compile(r"<sup>(\d+)</sup>")


def _text(fragment: str) -> str:
    """The words in a cell, with the markup and the padding gone."""
    return " ".join(_html.unescape(_TAGS.sub(" ", fragment or "")).split())


def _score_text(fragment: str) -> str:
    """A score cell, with its tiebreaks kept: "6-4, 6-7(6), 6-3"."""
    out = []
    for part in _text(_SUP.sub(r"(\1)", fragment or "")).split(","):
        p = part.strip()
        # The bracket belongs after the pair, not inside it: TE prints the
        # loser's breaker points against the games they lost.
        m = re.match(r"^(\d+)\((\d+)\)-(\d+)$", p.replace(" ", ""))
        if m:
            p = f"{m.group(1)}-{m.group(3)}({m.group(2)})"
        else:
            m = re.match(r"^(\d+)-(\d+)\((\d+)\)$", p.replace(" ", ""))
            if m:
                p = f"{m.group(1)}-{m.group(2)}({m.group(3)})"
        out.append(p)
    return ", ".join(x for x in out if x)


def level_of(path: str, name: str) -> Optional[str]:
    """'tour' | 'challenger' | 'itf' — which rung of the ladder an event is on.

    Read from the tournament's own path and printed name, because that is what
    the page states: TE names the rung in both ("mallorca-challenger", "ITF
    M15 Cancun"). Unknown stays None rather than guessing 'tour': a form line
    saying nothing about the level is honest, one promoting a Futures result to
    the tour is not.
    """
    hay = f"{path} {name}".lower()
    if "challenger" in hay:
        return "challenger"
    if re.search(r"\bitf\b|\bfutures\b|[mw]-?(?:15|25|40|50|60|75|100)\b", hay):
        return "itf"
    if re.search(r"atp-men|wta-women", path or ""):
        return "tour"
    return None


def season_of(page: str) -> Optional[int]:
    """Which season's matches a page is showing, from the page itself.

    The summary table at the foot marks the displayed season `class="bold"`, so
    the default page says which year it is rather than the caller assuming
    today's — which matters in the first days of January, when the default page
    is still last season for a player who has not started.
    """
    m = _SEASON.search(page)
    return int(m.group(1)) if m else None


def _dated(season: int, month: int, day: int, today: date) -> Optional[str]:
    """A TE day ('22.09.') as an ISO date, given the season it sits in.

    A row carries no year, and a season's page can hold a December event from
    the year before it (the tour's season opens in the last days of December).
    A match cannot have been played in the future, so a date that lands ahead
    of today belongs to the season before.
    """
    for year in (season, season - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue                      # 29 Feb in a non-leap season
        if d <= today:
            return d.isoformat()
    return None


def parse_player_matches(page: str, slug: str, season: Optional[int] = None,
                         today: Optional[date] = None) -> list[dict]:
    """One season page -> that player's played matches, newest first.

    Pure: the same page always parses to the same list, so the shape of a TE
    row is provable from a fixture without a network.
    """
    today = today or date.today()
    season = season or season_of(page) or today.year
    event, path = "", ""
    out: list[dict] = []
    for kind, body in ((m.group(1), m.group(2)) for m in _TR.finditer(page)):
        if kind == "head flags":
            cell = _HEAD_CELL.search(body)
            inner = cell.group(1) if cell else ""
            link = _HEAD_LINK.search(inner)
            path = link.group(1) if link else ""
            event = _text(inner)
            continue
        if _YEAR_ROW.search(body):
            continue                      # the win/loss summary, not a match
        score_m = _SCORE.search(body)
        if not score_m:
            continue                      # scheduled, not played: not form yet
        day_m = _DAY.search(body)
        names_m = _NAMES.search(body)
        if not day_m or not names_m:
            continue
        sides = []
        # `who`, never `path`: the outer `path` is the TOURNAMENT's, and a
        # loop variable of the same name silently replaced it with the last
        # player's slug — every tour event then read as an unknown level while
        # the Challengers, which are named in the event's own words, still
        # resolved. Caught by the level test.
        for kind, who, attrs, text in _SIDE.findall(names_m.group(1)):
            t = _TITLE.search(attrs)
            sides.append({
                "slugs": [x for x in who.split("/") if x],
                # The title is the full name where there is one; a doubles
                # row's visible text is cut to five letters a player and is
                # not a name anyone would recognise.
                "name": _text(t.group(1)) if t else _text(text),
                "doubles": kind == "doubles-team",
            })
        if len(sides) != 2:
            continue                      # not a pairing this parser can read
        mine = next((i for i, sd in enumerate(sides) if slug in sd["slugs"]), None)
        if mine is None:
            continue                      # cannot say which side is the player
        won = mine == 0                    # the winner is listed first
        theirs = sides[1 - mine]
        when = _dated(season, int(day_m.group(2)), int(day_m.group(1)), today)
        if when is None:
            continue
        surf = _SURFACE.search(body)
        rnd = _ROUND.search(body)
        out.append({
            "result": "W" if won else "L",
            "opponent": theirs["name"],
            # One slug identifies a singles opponent; a pair is two people and
            # neither of them is "the opponent".
            "opponent_slug": theirs["slugs"][0] if len(theirs["slugs"]) == 1 else None,
            "score": _score_text(score_m.group(1)),
            "event": event,
            "level": level_of(path, event),
            # Read the way the head-to-head reads it (te_rounds): "Q-QF" is a
            # qualifying round, and says so as "Q2".
            "round": normalize_qual_round(_text(rnd.group(2)), event) if rnd else "",
            "round_long": (rnd.group(1) or "") if rnd else "",
            # SAID ONCE, HERE. "Q-R16" is qualifying and "QF" is a
            # quarter-final, and a caller testing the short label's first
            # letter gets that wrong every time — the mistake this project
            # has a memory about (round tokens are not prefixes). TE spells
            # it out in the cell's title, so the answer comes from there.
            "qualifying": ((rnd.group(1) or "") if rnd else "").lower().startswith("qualific"),
            # Title case, because that is how `draws.surface` spells it and
            # the fallback path below returns those — one vocabulary, whichever
            # source answered.
            "surface": (surf.group(1).strip().title() if surf and surf.group(1).strip()
                        else None),
            "date": when,
            "doubles": sides[mine]["doubles"] or theirs["doubles"],
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


async def fetch_form(slug: str, limit: int = FORM_LIMIT,
                     before: Optional[date] = None) -> list[dict]:
    """A player's last `limit` played matches from Tennis Explorer, or [].

    Walks back a season at a time only while short of `limit`, so the ordinary
    case is one request — served from te_draw's own hour-long disk cache, whose
    politeness this shares deliberately rather than keeping a second one.

    `before` is for a historical draw: the panel there must show the form the
    player took INTO that match, not the results that came after it.
    """
    from app.services import te_draw

    today = date.today()
    got: list[dict] = []
    season: Optional[int] = None
    for step in range(MAX_SEASONS):
        path = f"/player/{slug}/" if step == 0 else f"/player/{slug}/?annual={season - 1}"
        try:
            page = await te_draw._get(path)
        except Exception as exc:
            logger.debug("TE form unavailable for %s (%s): %s", slug, path, exc)
            break
        season = (season_of(page) if step == 0 else season - 1) or today.year
        rows = parse_player_matches(page, slug, season=season, today=today)
        if before is not None:
            rows = [r for r in rows if r["date"] < before.isoformat()]
        got.extend(rows)
        if len(got) >= limit:
            break
    got.sort(key=lambda r: r["date"], reverse=True)
    return got[:limit]
