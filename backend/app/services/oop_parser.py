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
# A slot whose start time is not settled yet prints only "TBC" in the header
# band where "Followed by" would go — Monterrey 2026-08-25 held its last
# doubles quarter-final that way. It has to open a slot like any other wording,
# or everything printed under it is read as more players for the match above.
#
# ANCHORED, unlike SLOT_RE: these tokens are also ordinary words on a sheet.
# "COURT TBA" is a court NAME (2025_741) and "AFTER REST, TIME TBA" is already
# a slot by its first three words; matching either as a marker would lose the
# court and split a slot in two. Only a line that is nothing but the token.
TBX_RE = re.compile(
    r'^(?:TB[ACD]|to\s+be\s+(?:confirmed|announced|advised|determined))$', re.I)
VS_RE = re.compile(r'^(?:vs\.?|v\.?|contre)$', re.I)
TOUR_RE = re.compile(r'^(ATP|WTA)$', re.I)
ROUND_RE = re.compile(r'^(F|SF|QF|R\d{1,3}|Q\d?|FQ|1R|2R|3R|4R)$', re.I)
CONT_RE = re.compile(r'^(?:\[[^\]]*\]|[A-Z]{3})$')

# IOC codes as the tours print them, plus the ISO variants that turn up in
# their place (DEU for Germany, and RUS/BLR which persist on some sheets
# despite the neutral-athlete rules). Lives HERE, and schedule.py imports it,
# because two copies of a country table drift and the failure is silent.
COUNTRY_CODES = frozenset("""
AFG AHO ALB ALG AND ANG ANT ARG ARM ARU ASA AUS AUT AZE BAH BAN BAR BDI BEL BEN
BER BHU BIH BIZ BLR BOL BOT BRA BRN BRU BUL BUR CAF CAM CAN CAY CGO CHA CHI CHN
CIV CMR COD COK COL COM CPV CRC CRO CUB CYP CZE DEN DEU DJI DMA DOM ECU EGY ERI
ESA ESP EST ETH FIJ FIN FRA FSM GAB GAM GBR GBS GEO GEQ GER GHA GRE GRN GUA GUI
GUM GUY HAI HKG HON HUN INA IND IRI IRL IRQ ISL ISR ISV ITA IVB JAM JOR JPN KAZ
KEN KGZ KIR KOR KOS KSA KUW LAO LAT LBA LBN LBR LCA LES LIE LTU LUX MAD MAR MAS
MAW MDA MDV MEX MGL MHL MKD MLI MLT MNE MON MOZ MRI MTN MYA NAM NCA NED NEP NGR
NIG NOR NRU NZL OMA PAK PAN PAR PER PHI PLE PLW PNG POL POR PRK PUR QAT ROU RSA
RUS RWA SAM SEN SEY SIN SKN SLE SLO SMR SOL SOM SRB SRI SSD STP SUD SUI SUR SVK
SWE SWZ SYR TAN TCH TGA THA TJK TKM TLS TOG TPE TTO TUN TUR TUV UAE UGA UKR URU
USA UZB VAN VEN VIE VIN YEM ZAM ZIM
""".split())


def _is_continuation(text):
    """Is this line the wrapped tail of the name above — or the sheet's own furniture?

    THREE CAPITALS IS NOT A COUNTRY BY SHAPE. The layout wraps a name's seed or
    nationality onto its own line, so a lone "[Q]" or "CZE" belongs to the
    player above; but the sheet prints its own words in caps too. Monterrey's
    2026-08-25 sheet ended Cancha 4 with a "TBC" slot header, which is exactly
    this shape, and it was glued onto the last name printed above it: the
    doubles quarter-final went out as "Magali KEMPEN / Alexandra PANOVA TBC",
    a country nobody has and a name no search matches. TBC also opens a slot
    now (TBX_RE), so this is the second lock on the same door — the next such
    word will not have a slot rule waiting for it.
    """
    if not CONT_RE.match(text):
        return False
    if text.startswith('['):
        return True
    return text.upper() in COUNTRY_CODES
NOISE_RE = re.compile(
    r'sign-?in|deadline|supervisor|referee|tournament director|order of play|'
    r'ceremony|presentation|trophy|approximately|interview|practice|mins?\)|'
    # Side events printed in the running order but not part of any draw. They
    # carry their own "vs", so left alone they are absorbed into the real match
    # above — Keys v Parry acquired "EXHIBITION DOUBLES - BAHRAMI/CLEMENT vs
    # PIOLINE/SANTORO" as two extra opponents, which then read as a doubles
    # match. Six files across the corpus do this.
    r'exhibition|wheelchair|legends?\b|invitational|pro-?am|'
    r'^(?:singles|doubles|mixed)\s+(?:final|semi|quarter|qf|sf|f)\b|'
    r'^(?:MS|MD|WS|WD|XD|BS|BD|GS|GD|QS|QD)\s+(?:final|sf|qf|f|r\d+|tbf)\b|'
    r'locker-?room|director|^any match|'
    r'revised|released|any match|matches will|prize money|^\d+$|^page\b|'
    # Scheduling-policy footnotes. They sit below the play but share a line with
    # notes from neighbouring columns, so the y-cutoff does not always reach
    # them and one arrived as a third opponent.
    r'no matches later|matches not started|unless agreed|order of play is|'
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
    r'\b[WM][SQD]\d{2,4}\b|'                        # AO/US Open match codes
    r'Official\s+Order\s+of\s+Play', re.I)           # US Open


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
    # IOC codes aligned index-for-index with side_a/side_b, where the source
    # states them per player (the US Open feed does; PDF text leaves these
    # empty and nationality rides inside the printed name instead).
    nations_a: list = field(default_factory=list)
    nations_b: list = field(default_factory=list)
    page: int = 0
    # INTERNAL. Lines this slot swallowed that no rule could read as a name,
    # a score, a round or the sheet's furniture. Kept only so that a slot which
    # ends up with no players can say WHY it is empty — see meta['dropped_slots'].
    rejected: list = field(default_factory=list)

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
    if SLOT_RE.search(text) or BARE_TIME_RE.match(text) or TBX_RE.match(text):
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


ALLCAPS_NAME_RE = re.compile(r"(?:[A-Z][A-Za-z.'-]*\s+){2,}\(?[A-Z]{3}\)?\s*$")
# A DOUBLES entrant as the ATP prints one: surname only, then a nationality —
# "ARRIBAGE (FRA)", "[WC] LAMMONS (USA)". One name token, not two, so
# ALLCAPS_NAME_RE cannot express it. What replaces the missing second token as
# proof this is a person is the code itself: it must be a REAL country, which
# is the same lock _is_continuation uses. "COURT TBA" has the shape and is a
# court name; TBA is not a country, so it stays out.
ALLCAPS_ONE_NAME_RE = re.compile(
    r"^(?:\[[^\]]*\]\s*)*(?:[A-Z][A-Za-z.'-]*\s+)+\(?([A-Z]{3})\)?$")


def _allcaps_name(seg):
    """Is this all-caps fragment a player, in either shape the sheets print?"""
    seg = seg.strip()
    if ALLCAPS_NAME_RE.search(seg):
        return True
    m = ALLCAPS_ONE_NAME_RE.match(seg)
    return bool(m and m.group(1) in COUNTRY_CODES)


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
    #
    # EXCEPT when the given name is itself initials. "JJ TRACY (USA)" has no
    # lowercase letter anywhere, so this rejected him outright — and because he
    # is a doubles player, the match kept his partner and lost him: Monday's
    # Winston-Salem sheet showed "KRAJICEK / MEKTIC vs CABRAL", a team of one.
    #
    # THE TELL IS THE TRAILING NATIONALITY, AND IT MUST BE TESTED IN THE FORM
    # THIS FUNCTION ACTUALLY RECEIVES. The first version of this exemption
    # looked for "(USA)" with its parentheses — but _clean strips those to a
    # bare code before any of this runs, so the exemption could never fire and
    # Tracy went on being dropped. Both forms are accepted now.
    #
    # Two name-shaped tokens must precede the code, which is the "Given SURNAME
    # NAT" shape every player line on these sheets has. That keeps the
    # exemption from re-admitting the all-caps furniture the mixed-case rule
    # exists to reject: "ANY MATCH ON ANY COURT MAY BE MOVED" ends in a
    # five-letter word, not a country, and a bare "USA" continuation line has
    # no name in front of it.
    #
    # AND THE TEST RUNS PER "/"-SEPARATED SEGMENT, because a doubles line names
    # a TEAM: "[1] ARRIBAGE (FRA) / GUINARD (FRA)". Whole-line, the two-token
    # rule can never be satisfied — the slash sits where the second token would
    # be — so every all-caps doubles line was rejected as furniture. On
    # Winston-Salem's 2026-08-26 sheet all four lines of Court 3's third slot
    # were doubles pairs printed that way, so the slot lost every player, went
    # out incomplete, and the day published 11 matches for a 12-match sheet:
    # the Arribage/Guinard quarter-final simply was not on the site. Same class
    # as JJ TRACY above — an all-caps name read as the sheet's own furniture —
    # through the one shape that rule could not describe.
    if not re.search(r'[a-z]', text):
        segs = [s for s in (p.strip() for p in text.split('/')) if s]
        if not segs or not all(_allcaps_name(s) for s in segs):
            return False
    return bool(re.search(r'[A-Za-z]{2,}', text))


def parse_pdf(pdf_bytes):
    """-> (matches, meta). meta.reason explains an empty result."""
    import pdfplumber
    import io

    meta = {'pages': 0, 'kind': 'oop', 'reason': None, 'date_line': None,
            # Slots the sheet opened that this parse could not fill. The caller
            # alerts on these — schedule_invariants.check_parse.
            'dropped_slots': []}
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
            # y_tolerance=1, NOT pdfplumber's default 3. The default groups
            # chars into lines by CHAINING tops within the tolerance, across
            # the whole page — so two lines inside one court's cell can be
            # joined into a single "line" by way of a neighbouring column's
            # line whose top happens to fall between them. The chars of that
            # merged line are then sorted by x, and the two names come out
            # interleaved letter by letter, which the word splitter breaks into
            # one word per letter. Winston-Salem 2026-08-26 published
            # "Raphael COLLIGNON (BEL) or Rinky HIJIKATA (AUS)" as
            # "Ra R p i h n a k e y l H C I O JI L K L A IG TA N O ...".
            #
            # A sheet shrinks a cell's text to fit (this one to a 0.5 text
            # matrix — 8pt glyphs on a ~9pt pitch), so the tighter the box the
            # likelier the chain: the shape appears on exactly the crowded
            # slots, and only there, which is why no corpus file shows it.
            #
            # Tightening costs nothing here: line grouping for the parse is
            # done by _cells below (rows bucketed on top, then sorted by x), so
            # a visual line split into two clusters at this step is reassembled
            # there. Measured over the 285-file corpus: identical output.
            words = page.extract_words(y_tolerance=1)
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
                matches += _parse_column(rows, pno, meta['dropped_slots'])

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


def _parse_column(lines, pno, dropped=None):
    """One column, top to bottom: court header, then time-delimited match slots.

    `dropped` collects slots that the sheet opened and this parse could not
    fill — see the flush() comment. The caller surfaces them in meta so the
    ingest can alert on a slot the site would otherwise be silently missing.
    """
    out, court, cur, after_vs = [], '', None, False

    def flush():
        nonlocal cur
        if cur and cur.complete:
            _regroup_alternatives(cur)
            out.append(cur)
        elif cur is not None and cur.rejected and dropped is not None:
            # A slot marker opened this match and lines followed it that no
            # rule could read — yet it has no players. That is a slot the
            # sheet prints and the site will not show, which is the single
            # most invisible failure this parser has: nothing errors, the day
            # is just one match short. Winston-Salem 2026-08-26 lost Court 3's
            # doubles quarter-final exactly this way. An empty slot with NO
            # unreadable lines is ordinary — sheets print blank numbered rows.
            dropped.append(cur)
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
            # "TBA" under a time that has already been printed QUALIFIES that
            # slot; it does not open another. Cincinnati's combined sheet
            # (2026-08-19, Court 10) prints "Not Before 3:00 PM" and then "TBA"
            # on the line below, in the band where the neighbouring columns
            # print ATP/WTA — and reading the second line as a new slot threw
            # away a printed 3:00 PM, which is the one kind of time allowed to
            # veto a live-score match. A slot that would open with the current
            # one still empty is furniture in the same header band; Monterrey's
            # standalone "TBC" (2026-08-25) comes after a full slot and opens.
            if TBX_RE.match(text) and cur is not None and not (cur.side_a or cur.side_b):
                continue
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
        if _is_continuation(text):
            if side:
                side[-1] = f'{side[-1]} {text}'
            continue
        if alt and cur is not None:
            cur.tbd = True
            # WITH ITS SIDE, exactly as _regroup_alternatives records it. This
            # inline-"or" path set the flag alone, and a tbd with no side reads
            # downstream as "nothing unresolved here": the ingest stored both
            # alternatives as two players on one side of a SINGLES entry, and
            # the schedule drew Medvedev against a doubles team called
            # "DAMM / SHELBAYH".
            side_key = 'b' if after_vs else 'a'
            cur.tbd_side = ''.join(sorted(set((cur.tbd_side or '') + side_key)))
        if cur is not None and SCORE_RE.match(text) and re.search(r'\d', text):
            cur.printed_score = text
            st = re.search(r'\b(RET|W/?O|DEF|ABD|CONC|TBF)\b', text, re.I)
            if st:
                cur.printed_status = st.group(1).upper()
            continue

        if _is_name(text):
            side_key = 'b' if after_vs else 'a'
            if '/' in text and side_key in (cur.tbd_side or ''):
                # On an UNRESOLVED side a "/" joins the two partners of ONE
                # candidate team, not two players of this match — the sheet is
                # offering a choice between two teams. Splitting it flattened
                # "[1] ARRIBAGE / GUINARD or CASH / ERLER" into four loose
                # names, and _side_size then counted one player a side and
                # called the doubles quarter-final a singles match.
                #
                # _regroup_alternatives already keeps a side's alternatives
                # whole, but only reaches slots whose "or" survived as a word.
                # The ATP glues it to the nationality — "(FRA)or" — and _clean
                # strips it, so this branch is the ONLY thing holding the team
                # together on an ATP sheet. Same rule, both spellings.
                side.append(re.sub(r'\s*/\s*', ' / ', text))
            else:
                side.extend(_split_players(text))
        elif (not NOISE_RE.search(text)
                and len(re.findall(r'[A-Za-z]{2,}', text)) >= 2):
            # Words we could not place. Only recorded — never acted on — so
            # that a slot ending up empty can report what it choked on.
            #
            # TWO word-shaped tokens at least, because a printed slot that is
            # genuinely empty still carries one: the corpus has bare event
            # codes over blank slots ("QS", "QD" — wta/2025_1111) and a bare
            # "WO" where a walkover replaced the losing side (wta/2026_1017).
            # Neither is a lost player, and an alarm that cries at those would
            # be switched off by the second day.
            cur.rejected.append(text)

    flush()
    return out
