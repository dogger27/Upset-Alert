"""Order-of-play PDF parser, built against a 184-file corpus.

Design follows what the corpus actually contains, not what one sample looked
like:

* Columns are found by cutting rows into cells and anchoring on TIME markers —
  not by keying off ATP/WTA labels (141 of 184 files are single-tour and carry
  no per-match label), and not by empty vertical corridors (Cincinnati's six
  courts sit ~20pt apart and the centred title crosses the gutters, so any
  threshold that separates the columns also splits a name from its
  nationality). One column or six, portrait or landscape, same code path.
* Both tours are supported. They differ in wording — ATP writes "Starts At",
  WTA "Starting at" — and in nationality style: "(CZE)" vs "CZE".
* Every page is read. Five corpus files are multi-page, one of them nine pages.
* The document type is checked first. The same URL serves WTA "Match Schedule
  Plan" admin forms, a "-Tournament Information Not Yet Available-" placeholder,
  and at least one zero-word file, all at HTTP 200.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

# Time markers that open a new slot on a court.
# The slot keyword is NOT anchored: a fifth of the corpus writes
# "Singles Final - Starting at 1:00 PM" or "Starting at 11:00 AM Doubles Final",
# and an anchored match found neither, which is what left 19 files empty.
SLOT_RE = re.compile(
    r'(?:start(?:s|ing)?\s+at|not\s+before|not\s+bef\.?|followed\s+by|'
    r'after\s+(?:rest|suitable)|to\s+be\s+arranged|'
    # "30 mins after ceremony" opens the next slot on the same court. Without
    # it the doubles final was swallowed into the singles final above it.
    r'\d+\s*min(?:ute)?s?\s+after|'
    r'after\s+(?:the\s+)?(?:ceremony|presentation|previous|preceding|conclusion))', re.I)
CLOCK_RE = re.compile(r'\d{1,2}[:.]\d{2}\s*(?:am|pm)?', re.I)
# The sheet often states the discipline outright, which beats guessing it from
# how many names ended up on a side.
DISC_RE = re.compile(r'\b(singles|doubles)\b', re.I)
# A bare clock time on its own line is also a slot ("7:00 PM").
BARE_TIME_RE = re.compile(r'^\d{1,2}[:.]\d{2}\s*(?:am|pm)?$', re.I)
VS_RE = re.compile(r'^(?:vs\.?|v\.?|contre)$', re.I)
TOUR_RE = re.compile(r'^(ATP|WTA)$', re.I)
ROUND_RE = re.compile(r'^(F|SF|QF|R\d{1,3}|Q\d?|FQ|1R|2R|3R|4R)$', re.I)
CONT_RE = re.compile(r'^(?:\[[^\]]*\]|[A-Z]{3})$')
NOISE_RE = re.compile(
    r'sign-?in|deadline|supervisor|referee|tournament director|order of play|'
    r'ceremony|presentation|trophy|approximately|interview|practice|mins?\)|'
    r'^(?:singles|doubles|mixed)\s+(?:final|semi|quarter|qf|sf|f)\b|'
    r'^(?:MS|MD|WS|WD|XD|BS|BD|GS|GD|QS|QD)\s+(?:final|sf|qf|f|r\d+|tbf)\b|'
    r'locker-?room|director|^any match|'
    r'revised|released|any match|matches will|prize money|^\d+$|^page\b|'
    r'last match on any court|may be moved|order of play is subject', re.I)

# Everything below the last match: officials rosters, physio lists, the
# generation timestamp. The final slot on a court has no terminator after it, so
# without this it swallows the entire footer as extra players.
FOOTER_RE = re.compile(
    r'officials|player relations|physio|supervisor\(s\)|referee|tournament director|'
    r'released|matches may be moved|\d{1,2}\s+\w{3}\s+\d{4}\s+\d{1,2}:\d{2}', re.I)
OOP_HDR_RE = re.compile(r'ORDER\s+OF\s+PLAY', re.I)
REJECT_RE = re.compile(r'MATCH\s+SCHEDULE\s+PLAN|ELC\s+SYSTEM|Not\s+Yet\s+Available', re.I)
# The Finals publish a whole-event summary titled "COMPLETE TOURNAMENT RESULTS
# / ORDER OF PLAY TO DATE" — every match played so far, with scores, rather than
# one day's schedule. It contains the words "ORDER OF PLAY", so it passes the
# header test and then parses as nonsense: result lines like "C. Alcaraz d
# A. de Minaur 76(5) 62" become player names. One file produced 26 of the 29
# defects in the entire 75-file ATP set.
RESULTS_RE = re.compile(r'COMPLETE\s+TOURNAMENT\s+RESULTS|ORDER\s+OF\s+PLAY\s+TO\s+DATE', re.I)
SLAM_RE = re.compile(
    r"Gentlemen's\s+Singles|Ladies'\s+Singles|"      # Wimbledon
    r'PROGRAMME\s+OFFICIEL|Pas\s+avant|'             # Roland Garros (French)
    r'\b[WM]S\d{3}\b', re.I)                        # Australian Open codes


@dataclass
class Match:
    court: str = ''
    time: Optional[str] = None
    tour: Optional[str] = None
    round: Optional[str] = None
    discipline: Optional[str] = None
    # True when the sheet lists alternatives ("BOUZKOVA or JOVIC") because a
    # qualifier or a preceding match has not resolved yet. The extra name is
    # real information, not a parse error — but the slot cannot be mapped to one
    # fixture until it settles.
    tbd: bool = False
    # Which side(s) are unresolved — 'a', 'b' or 'ab'. Only those sides list
    # alternatives; the other holds real partners and must not be shown as a
    # choice between them.
    tbd_side: Optional[str] = None
    # The slot line exactly as printed ("Not before 3:00 PM"), so the caller can
    # tell a hard time from a lower bound from a pure ordering constraint.
    start_raw: Optional[str] = None
    # INTERNAL. Never shown to a user — a sheet's score is a snapshot from
    # whenever that revision was published and can be hours stale. Kept only to
    # anchor expected-start estimates on courts ESPN does not cover.
    printed_score: Optional[str] = None
    printed_status: Optional[str] = None
    side_a: list = field(default_factory=list)
    side_b: list = field(default_factory=list)
    page: int = 0

    @property
    def is_doubles(self):
        if self.discipline:
            return self.discipline == 'doubles'
        return self._side_size('a') > 1 or self._side_size('b') > 1

    def _side_size(self, side):
        """How many PLAYERS a side holds.

        Not the same as how many entries: once "X OR Y" is regrouped, a side
        holds one entry per candidate, so a singles match with both opponents
        still undecided ("L. Tien OR F. Tiafoe" against "J. M. Cerundolo OR
        F. Auger-Aliassime") looked like two partners a side and was labelled
        doubles. A doubles candidate names its pair with a slash, which is what
        distinguishes the two cases.
        """
        names = self.side_a if side == 'a' else self.side_b
        if side not in (self.tbd_side or ''):
            return len(names)
        return 2 if any('/' in n for n in names) else 1

    @property
    def complete(self):
        return bool(self.side_a and self.side_b)


def _cells(words, run_gap=14):
    """Split each visual row into CELLS — runs of words separated by a real gap.

    Corridor detection on the whole page does not work here: Cincinnati's six
    court columns are separated by only ~20pt, and the centred title crosses
    them, so any threshold that keeps the columns apart also splits names from
    their nationality. Cutting rows into cells first and clustering the cells
    afterwards sidesteps the geometry entirely, and treats a one-column portrait
    page and a six-column landscape page with the same code.
    """
    rows = {}
    for w in words:
        rows.setdefault(round(w['top'] / 3) * 3, []).append(w)

    cells = []
    for y, ws in sorted(rows.items()):
        ws.sort(key=lambda a: a['x0'])
        run = [ws[0]]
        for w in ws[1:]:
            if w['x0'] - run[-1]['x1'] > run_gap:
                cells.append(_cell(y, run))
                run = [w]
            else:
                run.append(w)
        cells.append(_cell(y, run))
    return cells


def _cell(y, run):
    """A cell is located by its CENTRE, not its left edge.

    Portrait sheets centre each court's column, so a cell's x0 depends on how
    long its text is — a full name starts further left than a short one. Bucketing
    on x0 therefore pushed wide names into the previous court's column and merged
    unrelated matches together (2026-08-19 Cincinnati: Zverev, Cirstea, Tirante
    and Kostyuk arrived in one slot). The centre is stable regardless of width.
    """
    return (y, (run[0]['x0'] + run[-1]['x1']) / 2,
            ' '.join(a['text'] for a in run))


def _column_origins(cells, tol=60):
    """Columns are anchored on TIME markers, not on all cell positions.

    Clustering every cell x-origin chains: indentation varies within a column,
    so the values form a near-continuum and single-linkage swallows the whole
    page (Cincinnati's six courts collapsed to two). Every match slot in every
    layout opens with a time marker at its column's left edge, and those sit at
    a clean pitch — 56/189/321/454/586/718 across six courts — so they identify
    the columns unambiguously.
    """
    anchors = sorted(x for _, x, t in cells if _slot_of(_clean(t)))
    if not anchors:
        return [min((x for _, x, _ in cells), default=0)]
    groups, cur = [], [anchors[0]]
    for x in anchors[1:]:
        if x - cur[-1] > tol:
            groups.append(cur); cur = [x]
        else:
            cur.append(x)
    groups.append(cur)
    return [sum(g) / len(g) for g in groups]


def _slot_of(text):
    """-> (time, discipline) when this line opens a match slot, else None."""
    if not text:
        return None
    if SLOT_RE.search(text) or BARE_TIME_RE.match(text):
        times = CLOCK_RE.findall(text)
        d = DISC_RE.search(text)
        return (times[-1].strip() if times else None,
                d.group(1).lower() if d else None)
    return None


LEADER_RE = re.compile(r'^\d{1,6}\.{1,}\s*')
# "CERUNDOLO ARGor" — the alternative marker for an unresolved qualifier gets
# glued onto the nationality by the text extractor.
GLUED_OR_RE = re.compile(r'([A-Z]{3})or\b')


def _clean(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = LEADER_RE.sub('', text)
    # Parentheses come off FIRST. The raw text is "BOUZKOVA (CZE)or", so the
    # closing paren sits between the code and the "or" and blocks the unglue.
    text = re.sub(r'\((\w{3})\)', r'\1', text)          # (POR) -> POR
    text = GLUED_OR_RE.sub(r'\1', text)
    text = re.sub(r'\s+or$', '', text)
    return text


# In-progress and finished slots print the score where "vs" would be, sometimes
# with a status code: "6-3 0-0 RET", "62 *42 TBF", "6-4 6-2 F".
SCORE_RE = re.compile(
    r'^[\d\s\-()*/,.]*'
    r'(?:\s*(?:RET|TBF|W/?O|DEF|ABD|CONC|F|SF|QF|ATP|WTA))*\s*$', re.I)


# Two partners sometimes share one cell with nothing between them:
# "David VEGA HERNANDEZ ESP Benjamin WINTER LOPEZ ESP". Every name in this
# format ends with a nationality code, so the boundary is the point just after
# one, followed by a real given name. Requiring that following name matters:
# keying on a bracket alone tore the trailing seed off "Eva LYS GER [6]" and
# turned every seeded singles player into a phantom pair.
_PAIR_SPLIT_RE = re.compile(r'(?<=[A-Z]{3})\s+(?=(?:\[[^\]]*\]\s*)?[A-Z][a-z])')


def _split_players(text):
    parts = [p.strip() for p in text.split('/')] if '/' in text else [text]
    out = []
    for p in parts:
        out.extend(x.strip() for x in _PAIR_SPLIT_RE.split(p) if x.strip())
    return out


def _is_name(text):
    if not text or NOISE_RE.search(text):
        return False
    if TOUR_RE.match(text) or ROUND_RE.match(text) or VS_RE.match(text):
        return False
    if _slot_of(text) or SCORE_RE.match(text):
        return False
    # Every player line in the corpus carries mixed case — "Marie BOUZKOVA",
    # "FEARNLEY, Jacob". Score and status fragments never do, which separates
    # them far more reliably than trying to enumerate score punctuation.
    if not re.search(r'[a-z]', text):
        return False
    return bool(re.search(r'[A-Za-z]{2,}', text))


def parse_pdf(pdf_bytes):
    """-> (matches, meta). meta.reason explains an empty result."""
    import pdfplumber
    import io

    meta = {'pages': 0, 'kind': 'oop', 'reason': None, 'date_line': None}
    matches = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        meta['pages'] = len(pdf.pages)
        head = ' '.join((p.extract_text() or '') for p in pdf.pages[:2])
        if not head.strip():
            meta.update(kind='empty', reason='no extractable text')
            return [], meta
        if REJECT_RE.search(head):
            meta.update(kind='not-an-oop', reason='admin/placeholder document')
            return [], meta
        if RESULTS_RE.search(head):
            meta.update(kind='results-summary',
                        reason='whole-event results, not a day\'s order of play')
            return [], meta
        if SLAM_RE.search(head):
            meta.update(kind='slam', reason='Grand Slam format — not yet supported')
            return [], meta
        m = re.search(r'ORDER\s+OF\s+PLAY\s*[-–]?\s*([^\n]{0,40})', head, re.I)
        if m:
            meta['date_line'] = m.group(1).strip()

        for pno, page in enumerate(pdf.pages, 1):
            words = page.extract_words()
            if not words:
                continue
            cells = _cells(words)
            foot = [y for y, _, t in cells if FOOTER_RE.search(_clean(t))]
            if foot:
                cutoff = min(foot)
                cells = [c for c in cells if c[0] < cutoff]
                words = [w for w in words if w['top'] < cutoff]
            origins = _column_origins(cells)
            if not origins:
                continue

            # Assign WORDS to columns, then group each column into lines —
            # never the other way round. Grouping first merged words across
            # column boundaries whenever centred names nearly touched, which
            # put four players from four courts into one slot (2026-08-19
            # Cincinnati: Zverev, Cirstea, Tirante, Kostyuk). Columns are found
            # from the slot markers, which are short and always well separated.
            bounds = [(origins[k] + origins[k + 1]) / 2 for k in range(len(origins) - 1)]
            wbuckets = {i: [] for i in range(len(origins))}
            for w in words:
                mid = (w['x0'] + w['x1']) / 2
                i = 0
                while i < len(bounds) and mid >= bounds[i]:
                    i += 1
                wbuckets[i].append(w)

            buckets = {}
            for i, ws in wbuckets.items():
                buckets[i] = [(y, text) for y, _mid, text in _cells(ws)]

            for i in sorted(buckets):
                rows = [(y, t) for y, t in sorted(buckets[i])]
                matches += _parse_column(rows, pno)

    if not matches and meta['reason'] is None:
        meta['reason'] = 'no matches found'
    return matches, meta


def _regroup_alternatives(match):
    """Rebuild "A / B OR C / D" into the two teams it names.

    An unresolved opponent is printed as one logical line and wraps mid-name:

        O. Luz / R. Matos OR C.
        Harrison / N. Skupski

    Split line by line that yields "O. Luz", "R. Matos OR C.", "Harrison",
    "N. Skupski" — four jumbled names, with "C. Harrison" torn in half. Joining
    the side back up before splitting on OR recovers the pairing. Only done when
    an OR is actually present: joining unconditionally would run two ordinary
    doubles partners printed on separate lines into one string.

    Each alternative is kept as a single entry, so a side reads "team or team".
    A TBD side cannot be resolved to draw entries anyway — that is what makes it
    TBD — so nothing is lost by not splitting it into individual players.
    """
    for attr in ('side_a', 'side_b'):
        names = getattr(match, attr)
        if not any(re.search(r'\bOR\b', n) for n in names):
            continue
        joined = ' '.join(names)
        parts = [p.strip(' /') for p in re.split(r'\s+OR\s+', joined) if p.strip(' /')]
        # The "/" between partners was consumed when the side was first split,
        # so put it back. In this abbreviated form every player begins with an
        # initial, and any initial after the first starts the next partner.
        # Split only where a SURNAME is followed by an initial. Keying on the
        # following initial alone tore "J. M. Cerundolo" — one player with two
        # initials — into two people.
        parts = [re.sub(r'(?<=[a-z])\s+(?=[A-Z]\.)', ' / ', p) for p in parts]
        parts = [re.sub(r'-\s+', '-', p) for p in parts]   # "Auger- Aliassime"
        if len(parts) >= 2:
            setattr(match, attr, parts)
            match.tbd = True
            # Accumulate: BOTH sides can be unresolved at once, as when two
            # preceding matches are still in progress. Overwriting here left
            # the first side rendering as if it were settled.
            side = 'a' if attr == 'side_a' else 'b'
            match.tbd_side = ''.join(sorted(set((match.tbd_side or '') + side)))


def _parse_column(lines, pno):
    """One column, top to bottom: court header, then time-delimited match slots."""
    out, court, cur, after_vs = [], '', None, False

    def flush():
        nonlocal cur
        if cur and cur.complete:
            _regroup_alternatives(cur)
            out.append(cur)
        cur = None

    for _, raw in lines:
        alt = bool(re.search(r'\)or\b|\bor\s*$|\bOR\s*$', raw))
        text = _clean(raw)
        if not text:
            continue

        # Only after play has started: the header carries "CITY, GER", which an
        # over-broad footer pattern matched, breaking the column before it had
        # parsed anything at all.
        if (out or cur) and FOOTER_RE.search(text):
            break          # nothing below this is play

        slot = _slot_of(text)
        if slot:
            flush()
            cur = Match(court=court, time=slot[0], discipline=slot[1],
                        start_raw=text, page=pno)
            after_vs = False
            continue

        if cur is None:
            # Before the first time marker, an all-caps line is the court name.
            if (text.isupper() and not NOISE_RE.search(text)
                    and not TOUR_RE.match(text) and not ROUND_RE.match(text)
                    and len(text) > 2 and not DISC_RE.fullmatch(text)):
                court = text
            continue

        if VS_RE.match(text):
            after_vs = True
            continue
        if TOUR_RE.match(text):
            cur.tour = text.upper()
            continue
        if ROUND_RE.match(text):
            cur.round = text.upper()
            continue
        # Strip leading round/tour tokens the layout parks on the name line.
        text = re.sub(r'^(?:F|SF|QF|R\d{1,3}|ATP|WTA)\s+(?=[A-Za-z\[])', '', text).strip()
        # A trailing round marker on a name line ("... USA F")
        parts = text.rsplit(' ', 1)
        if len(parts) == 2 and ROUND_RE.match(parts[1]) and _is_name(parts[0]):
            cur.round = parts[1].upper()
            text = parts[0]

        side = cur.side_b if after_vs else cur.side_a
        # A bare country code or seed is the tail of the name on the line above,
        # wrapped by the layout — not a second player. Treating it as one made
        # 274 of 278 matches look like doubles.
        if CONT_RE.match(text):
            if side:
                side[-1] = f'{side[-1]} {text}'
            continue
        if alt and cur is not None:
            cur.tbd = True
        if cur is not None and SCORE_RE.match(text) and re.search(r'\d', text):
            cur.printed_score = text
            st = re.search(r'\b(RET|W/?O|DEF|ABD|CONC|TBF)\b', text, re.I)
            if st:
                cur.printed_status = st.group(1).upper()
            continue

        if _is_name(text):
            side.extend(_split_players(text))

    flush()
    return out
