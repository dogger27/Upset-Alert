"""THE ATP'S OWN DRAW SHEET — protennislive's mds.pdf, the men's draw source
that comes first (owner, 2026-09-25).

    https://www.protennislive.com/posting/{year}/{atp_id}/mds.pdf

The same host and path as the order-of-play PDF this project already reads
(order_of_play._ATP_PDF), keyed by the same `tournaments.atp_tournament_id`.
It is the tour's official sheet, and it states everything a draw needs in its
first column:

    1 1 VACHEROT, Valentin MON        position, seed, SURNAME, Given, IOC
    2 Bye
    3 Q HARRIS, Lloyd RSA             entry type (Q WC LL SE PR ALT NG)
    24 4 VAN DE ZANDSCHULP, … NED     a long name, cut by the sheet with "…"

Everything to the right of that column is later rounds and scores, which this
module never reads — only the draw's first round.

A CUT NAME IS RESOLVED, NEVER GUESSED (owner, 2026-09-25): three readings,
and they must agree —
  1. the name already in THAT slot of the draw we hold (Tennis Explorer's or
     Wikipedia's), when its surname and given name begin as the sheet's do;
  2. the Tennis Explorer player whose surname is the sheet's and whose given
     name begins with the letters shown, from the same country;
  3. the sheet's own "Seeded Players" table, which spells some names further.
A name none of them settles keeps the letters the sheet shows, without "…".

NEUTRAL ATHLETES carry no country on the sheet (Medvedev, Rublev), and none is
invented here.

POLITENESS, MEASURED THE HARD WAY (2026-09-25): eleven requests two seconds
apart earned a Cloudflare challenge page on this host — the host the order of
play also comes from. So each sheet is cached on disk for an hour, and a
challenge (an HTML answer where a PDF was asked for) stands the whole source
down for six hours rather than being retried into.
"""
import hashlib
import io
import logging
import os
import re
import time
import unicodedata
from collections import Counter
from typing import Optional

from app.services.sofa_draw_shape import DrawShape, ShapeEntrant

logger = logging.getLogger(__name__)

URL = "https://www.protennislive.com/posting/{year}/{atp_id}/mds.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/pdf,*/*"}
_CACHE_DIR = os.environ.get("ATP_PDF_CACHE_DIR", "/data/atp-pdf-cache")
_CACHE_TTL = 3600.0
_STAND_DOWN = 6 * 3600.0
_blocked_until = 0.0

_ENTRY = {"Q": "Q", "WC": "WC", "LL": "LL", "SE": "SE", "PR": "PR", "NG": "NG",
          "ALT": "Alt", "A": "Alt", "SR": "PR"}
_IOC = re.compile(r"^[A-Z]{3}$")
_ELLIPSIS = "…"


# ── parsing ───────────────────────────────────────────────────────────────

def _rows(pdf_bytes: bytes) -> list:
    """Every text line of the sheet as (page, top, [words]) — words with x."""
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pi, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            lines: dict = {}
            for w in words:
                key = round(w["top"])
                # Words a point apart vertically are one line.
                hit = next((k for k in lines if abs(k - key) <= 1), None)
                lines.setdefault(hit if hit is not None else key, []).append(w)
            for top in sorted(lines):
                out.append((pi, top, sorted(lines[top], key=lambda w: w["x0"])))
    return out


def parse_slots(pdf_bytes: bytes) -> Optional[list]:
    """The draw's first column as slots, in position order, or None when the
    sheet is not a draw this parser understands (never a half-bracket).

    Each slot: {pos, bye, placeholder, seed, entry, surname, given, country,
    cut} — `cut` when the sheet shortened the name with "…".
    """
    rows = _rows(pdf_bytes)
    # The position column: a line that STARTS with an integer at the left
    # margin. Its x is the leftmost such start seen.
    starts = [ws[0] for _, _, ws in rows if ws and ws[0]["text"].isdigit()]
    if not starts:
        return None
    pos_x = min(w["x0"] for w in starts)
    cand = [(p, t, ws) for p, t, ws in rows
            if ws and ws[0]["text"].isdigit() and abs(ws[0]["x0"] - pos_x) < 6]
    # Where names begin: the x of "Bye" and of every "SURNAME," token.
    name_xs = [w["x0"] for _, _, ws in cand for w in ws[1:4]
               if w["text"] == "Bye" or w["text"].endswith(",")]
    if not name_xs:
        return None
    name_x = Counter(round(x) for x in name_xs).most_common(1)[0][0]
    # The country column: the commonest x of a 3-capital token right of names.
    ioc_xs = [round(w["x0"]) for _, _, ws in cand for w in ws
              if _IOC.match(w["text"]) and w["x0"] > name_x + 25]
    country_x = Counter(ioc_xs).most_common(1)[0][0] if ioc_xs else None

    slots = []
    for _, _, ws in cand:
        pos = int(ws[0]["text"])
        lead = [w["text"] for w in ws[1:] if w["x0"] < name_x - 1]
        edge = (country_x - 2) if country_x else name_x + 90
        body = [w for w in ws[1:] if name_x - 1 <= w["x0"] < edge]
        country = None
        if country_x:
            c = next((w["text"] for w in ws if abs(w["x0"] - country_x) <= 4 and _IOC.match(w["text"])), None)
            country = c
        seed = next((int(t) for t in lead if t.isdigit()), None)
        entry = next((_ENTRY[t.upper()] for t in lead if t.upper() in _ENTRY), None)
        text = " ".join(w["text"] for w in body).strip()
        slot = {"pos": pos, "bye": False, "placeholder": False, "seed": seed, "entry": entry,
                "surname": None, "given": None, "country": country, "cut": False}
        if text == "Bye" or text.startswith("Bye "):
            slot["bye"] = True
        elif not text or text.lower().startswith(("qualifier", "lucky loser", "special exempt")):
            slot["placeholder"] = True
        else:
            slot["cut"] = _ELLIPSIS in text or text.endswith("...")
            text = text.replace(_ELLIPSIS, "").replace("...", "").strip()
            sur, _, given = text.partition(",")
            slot["surname"], slot["given"] = sur.strip(), given.strip()
        slots.append(slot)

    slots.sort(key=lambda s: s["pos"])
    n = len(slots)
    # A whole bracket or nothing: positions 1..n, n a power of two.
    if n < 8 or n & (n - 1) or [s["pos"] for s in slots] != list(range(1, n + 1)):
        return None
    # THE ODD-SLOT CONVENTION every reader in this project writes (wta_draw,
    # te_draw, Wikipedia, Sofascore): in a first-round pair holding a bye,
    # the PLAYER takes the odd slot. The sheet prints the bye above the seed
    # in the bottom half (Bye 23, van de Zandschulp 24) — same pair, same
    # match; flipped here so a draw never finds its seeds one slot away.
    for i in range(0, n, 2):
        a, b = slots[i], slots[i + 1]
        if a["bye"] and not b["bye"]:
            a["pos"], b["pos"] = b["pos"], a["pos"]
            slots[i], slots[i + 1] = b, a
    return slots


def seeded_table(pdf_bytes: bytes) -> dict:
    """{seed: "Surname, Given"} from the sheet's Seeded Players table, which
    sometimes spells a name the draw column cut ("Etcheverry, Tomas Martin")."""
    import pdfplumber
    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    out = {}
    for m in re.finditer(r"(?m)(?:^|\s)(\d{1,2}) ([A-Z][^\n,]+, [^\n\d]+?) (\d{1,4})\s*$", text):
        out.setdefault(int(m.group(1)), m.group(2).strip())
    return out


# ── names ─────────────────────────────────────────────────────────────────

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace("-", " ").strip()


def _title(word: str) -> str:
    """"VAN DE ZANDSCHULP" -> "Van De Zandschulp": the sheet's capitals, read
    as a name. Only for a name no other source could spell."""
    return " ".join(p[:1].upper() + p[1:].lower() if p else p for p in word.split(" "))


def _agrees(full: str, surname: str, given_prefix: str) -> bool:
    """Does `full` ("Given Surname") carry this surname and a given name that
    begins with the letters the sheet shows?"""
    f, s, g = _fold(full), _fold(surname), _fold(given_prefix)
    if not s or s not in f:
        return False
    rest = f.replace(s, " ").split()
    return not g or any(" ".join(rest[i:]).startswith(g) for i in range(len(rest)))


def resolve_names(slots: list, *, held: dict, te_players: list, seeded: dict,
                  country_to_ioc: dict) -> dict:
    """Fill each slot's full name. `held` = {position: name} from the draw we
    already hold (TE or Wikipedia); `te_players` rows with name_display /
    first_name / last_name / nationality. Returns counts for the report."""
    stats = {"cut": 0, "by_slot": 0, "by_te": 0, "by_seed_table": 0, "unresolved": 0}
    for s in slots:
        if s["bye"] or s["placeholder"]:
            continue
        sur, given = s["surname"] or "", s["given"] or ""
        if not s["cut"]:
            s["name"] = f"{given} {_title(sur) if sur.isupper() else sur}".strip()
            # OUR SPELLING when the slot's person is the same one: same
            # surname, same first initial — "Alexander Shevchenko" where the
            # sheet writes "Aleksandr" (2026-09-25). Every other source this
            # project matches against knows him by the name we hold.
            h = held.get(s["pos"])
            if h and _fold(sur) and _fold(sur) in _fold(h) and _fold(h)[:1] == _fold(given)[:1]:
                s["name"] = h
            continue
        stats["cut"] += 1
        # 1. The same slot in the draw we hold.
        h = held.get(s["pos"])
        if h and _agrees(h, sur, given):
            s["name"] = h
            stats["by_slot"] += 1
            continue
        # 2. Tennis Explorer: surname, given-name prefix, country.
        hits = []
        for tp in te_players:
            full = (tp.name_display or f"{tp.first_name or ''} {tp.last_name or ''}").strip()
            if not full or not _agrees(full, sur, given):
                continue
            ioc = country_to_ioc.get((tp.nationality or "").strip().lower())
            if s["country"] and ioc and ioc != s["country"]:
                continue
            hits.append(full)
        if len(set(hits)) == 1:
            s["name"] = hits[0]
            stats["by_te"] += 1
            continue
        # 3. The Seeded Players table.
        seeded_name = seeded.get(s["seed"]) if s["seed"] else None
        if seeded_name and _ELLIPSIS not in seeded_name:
            ssur, _, sgiven = seeded_name.partition(",")
            if _fold(ssur) == _fold(sur) and _fold(sgiven).startswith(_fold(given)):
                s["name"] = f"{sgiven.strip()} {ssur.strip()}"
                stats["by_seed_table"] += 1
                continue
        s["name"] = f"{given} {_title(sur)}".strip()
        stats["unresolved"] += 1
    return stats


def to_shape(slots: list) -> DrawShape:
    n = len(slots)
    shape = DrawShape(bracket_size=n, num_rounds=n.bit_length() - 1)
    for s in slots:
        if s["bye"]:
            shape.byes.append(s["pos"])
            continue
        shape.entrants.append(ShapeEntrant(
            bracket_position=s["pos"],
            name=s.get("name") or ("Qualifier" if s["placeholder"] else ""),
            seed=s["seed"], entry_type=s["entry"], nationality=s["country"],
            placeholder=s["placeholder"]))
    return shape


# ── fetching ──────────────────────────────────────────────────────────────

async def fetch_pdf(atp_id: int, year: int) -> Optional[bytes]:
    """The sheet, from the disk cache when fresh, else one request. None when
    it is not published, not a PDF, or the source is standing down."""
    global _blocked_until
    import httpx
    url = URL.format(year=year, atp_id=atp_id)
    path = os.path.join(_CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < _CACHE_TTL:
            with open(path, "rb") as fh:
                return fh.read()
    except OSError:
        pass
    if time.monotonic() < _blocked_until:
        return None
    try:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
    except Exception as exc:
        logger.info("ATP draw sheet unreachable for %s: %s", atp_id, exc)
        return None
    body = r.content or b""
    if r.status_code in (403, 429) or (r.status_code == 200 and not body.startswith(b"%PDF")
                                        and b"<html" in body[:200].lower()):
        _blocked_until = time.monotonic() + _STAND_DOWN
        from app.services.system_log import app_log
        await app_log("warning", "draws",
                      "protennislive answered the ATP draw sheet with a challenge — "
                      "standing the source down for six hours",
                      {"atp_id": atp_id, "status": r.status_code},
                      dedup_key="atp_pdf_challenge", dedup_hours=6)
        return None
    if r.status_code != 200 or not body.startswith(b"%PDF"):
        return None
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body)
    except OSError:
        pass
    return body


async def fetch_shape(draw, tournament, db) -> tuple[Optional[DrawShape], dict]:
    """The draw from the ATP's sheet, names resolved, or (None, report)."""
    from sqlalchemy import select
    from app.models.rankings import TePlayer
    from app.models.tournament import DrawEntry
    from app.services.rankings import COUNTRY_TO_IOC

    report: dict = {}
    atp_id = getattr(tournament, "atp_tournament_id", None)
    if not atp_id or (draw.gender or "").upper() != "M":
        return None, report
    pdf = await fetch_pdf(int(atp_id), int(draw.year))
    if not pdf:
        return None, report
    slots = parse_slots(pdf)
    if not slots:
        report["atp_pdf"] = "unparsed"
        return None, report
    held = {e.bracket_position: e.name for e in (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id))).scalars()
        if e.bracket_position and e.name}
    tps = (await db.execute(select(TePlayer).where(TePlayer.gender == "M"))).scalars().all()
    report["atp_pdf_names"] = resolve_names(slots, held=held, te_players=tps,
                                            seeded=seeded_table(pdf), country_to_ioc=COUNTRY_TO_IOC)
    return to_shape(slots), report
