"""
Put both tours' tier stamps on one frame, at one text size.

They ship as two different kinds of object, and the dashboard — which draws
every stamp on a tour-coloured plate — is where that stopped being tolerable:

  WTA  lettering knocked out of an opaque rounded rectangle in the WTA's own
       tier colour (purple 250, teal 500, gold 1000). The plate would have
       framed a purple block.
  ATP  the wordmark with the number STACKED underneath it, where the WTA tag
       sets them side by side at one height.

So: strip the WTA tags to their lettering, re-set the ATP number inline, and
then put every result on ONE canvas at ONE cap height.

THAT LAST STEP IS THE POINT, and it took three tries to understand why. The
badge scales the artwork with `contain`, which fits by whichever side runs out
first — the width, for every one of these. So the rendered height of the
lettering is decided by the lettering's own aspect ratio and by nothing else:
padding cancels out of the arithmetic completely. An ATP line runs about 6.1
times its cap height where a WTA line runs about 4.4, so in a shared box the
ATP text came out a third shorter, and giving the ATP its own wider box fixed
the type at the cost of a badge a third wider than the WTA's beside it.

One canvas sized for the widest line, with every line scaled to the same cap
height and centred on it, gives both: same plate, same text size, in a single
box. The WTA lines simply sit with more air either side, which is what a badge
is allowed to do — and it also settles the 250 tag, whose caps were 11% taller
than its own 500 and 1000.

Everything here is measured out of the art — the flat colours, the band
between the stacked rows, where the letters end and the swoosh begins. Each of
those changes the day the artwork is redrawn, and a number typed in here would
then be a silently wrong answer rather than a crash. Originals stay beside the
output: they are this script's input.

    python3 gen-tier-stamps.py
"""
from collections import Counter
from pathlib import Path

from PIL import Image

ART = Path(__file__).parent.parent / 'mobile' / 'assets' / 'logos'

# ------------------------------------------------------------------- the ink

# Every stamp is flattened to ONE colour per tour. The 250s already were —
# they are flat silhouettes — and the ATP's 500 and 1000 ship as silver and
# gold gradients, the WTA's tags as white on a tier colour, so three tiers of
# one tour arrived in three different inks (owner, 2026-09-15).
#
# The ATP's is read out of its own 250 artwork rather than typed in. The WTA
# has no pink anywhere in its artwork, so that one comes from the palette: the
# site's --wta-text, which is the counterpart of the --atp-text the ATP's 250
# happens to be drawn in. Both are TOUR[*].text in theme.js, and
# tierStamps.test.mjs fails if these drift from it.
INK_SOURCE = 'categorystamps_250-dark.png'
WTA_INK = (255, 179, 198)       # #ffb3c6 — theme.js TOUR.F.text, the site's --wta-300

# THE SWOOSH'S SIDE BEARING. The ATP mark opens with a wedge that tapers to
# nothing, and for its first ~28px it covers under 8% of the line's height —
# a hairline at 15pt, and invisible. But ink is ink: it set the artwork's
# bounding box, so the badge's padding measured to the tip of a tail nobody can
# see and the mark appeared indented by about 13pt against the 6pt on its right
# (owner, 2026-09-15).
#
# So the wispy part is treated as a SIDE BEARING and trimmed, which is what a
# type designer does with an overshoot: the box is set on the substance of the
# glyph, and what tapers past it is allowed to hang into the margin — here, by
# not being in the box at all. At this threshold the cut lands where the wedge
# is 1.5pt tall on screen, so the swoosh still reads as a swoosh.
BEARING = 0.10


def flat_colour(name):
    """The one colour a flat silhouette is drawn in."""
    im = Image.open(ART / name).convert('RGBA')
    w, h = im.size
    px = im.load()
    c = Counter(px[x, y][:3] for y in range(0, h, 2) for x in range(0, w, 2)
                if px[x, y][3] == 255)
    if not c:
        raise SystemExit(f'{name}: nothing opaque to read a colour from')
    return c.most_common(1)[0][0]


# ---------------------------------------------------------------- the canvas

# The cap height every stamp is set at. Close to the WTA tags' own 106-119px so
# nothing is meaningfully resampled, and ~2x what the badge needs at 3x.
CAP = 110


def tight(line, cap):
    """One line of lettering at CAP, cropped to the ink and nothing else.

    NO PADDING BAKED IN. It used to be centred on a shared canvas sized for the
    widest line, which is what put ~26pt of air either side of a WTA line
    against ~6pt above and below it (owner, 2026-09-15). Padding inside the
    artwork also cannot be equal on all four sides and constant across six
    stamps of different widths — it is one number in the badge's style, so that
    is where it lives now. What the artwork owes the badge is the lettering,
    at a known height, and its own aspect ratio.
    """
    k = CAP / cap
    out = line.resize((max(1, round(line.size[0] * k)),
                       max(1, round(line.size[1] * k))), Image.LANCZOS)
    return out.crop(out.getbbox())


def split_number(line):
    """Where the number starts: after the widest blank column band, which is
    the space between the wordmark and the number in every one of these."""
    w, h = line.size
    a = line.split()[3]
    ink = [any(a.getpixel((x, y)) > 12 for y in range(h)) for x in range(w)]
    runs, x = [], 0
    while x < w:
        if not ink[x]:
            start = x
            while x < w and not ink[x]:
                x += 1
            if x < w:                       # a trailing blank is not a gap
                runs.append((start, x - start))
        else:
            x += 1
    if not runs:
        raise SystemExit('no space between wordmark and number')
    at, width = max(runs, key=lambda r: r[1])
    return at, width


def number_width(line):
    at, gap = split_number(line)
    return line.size[0] - at - gap


def recolour(art, ink):
    """The same glyphs in another ink: keep the coverage, replace the colour.

    The ATP sets its 500 in a silver gradient and its 1000 in gold, and the WTA
    stamp's lettering is one flat off-white — so what is borrowed from the ATP
    is the SHAPE of the numerals, never their colour. Each tour keeps its own
    ink; the digits stop being two different typefaces.
    """
    out = Image.new('RGBA', art.size, (*ink, 0))
    out.putalpha(art.split()[3])
    return out


def pad_to(art, size):
    """The same artwork on a canvas of exactly `size`, centred.

    For ROUNDING ONLY. Both tours' lines are composed from the same pieces and
    come out the same width, but each is cropped to its ink at the end, and a
    LANCZOS resize can leave the wordmark's last column fully transparent — so
    the WTA's 1000 landed a single pixel narrower than the ATP's. A pixel of
    transparency either side is invisible and keeps the pair's aspect ratios
    identical, which the badge relies on; anything larger than rounding is a
    real break and stays a hard failure at the call site.
    """
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    out.alpha_composite(art, ((size[0] - art.size[0]) // 2,
                              (size[1] - art.size[1]) // 2))
    return out


def bottom_line(mark, num, gap):
    """A wordmark and a number side by side, sharing a baseline.

    Both pieces are exactly cap-tall — the number is scaled to the cap and the
    wordmark's box ends at its own baseline, the swoosh included — so sharing a
    baseline is the same as sharing a top edge. Asserted rather than assumed:
    if a redrawn mark ever dips below its letters, this is where it shows up.
    """
    if mark.size[1] != num.size[1]:
        raise SystemExit(f'wordmark {mark.size[1]}px and number {num.size[1]}px '
                         'are not the same height — the baseline is not the box')
    out = Image.new('RGBA', (mark.size[0] + gap + num.size[0], mark.size[1]), (0, 0, 0, 0))
    out.alpha_composite(mark, (0, 0))
    out.alpha_composite(num, (mark.size[0] + gap, 0))
    return out.crop(out.getbbox())


# ------------------------------------------------------- WTA: lettering only

TAGS = {
    '250k-tag-plate.png': '250k-tag.png',
    '500k-tag-plate.png': '500k-tag.png',
    '1000k-tag-plate.png': '1000k-tag.png',
}


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def ink_and_fill(px, w, h):
    """The two colours the art is made of: the lettering and the plate behind
    it. The lettering is the lighter of the two in all of them."""
    c = Counter(px[x, y] for y in range(0, h, 2) for x in range(0, w, 2))
    opaque = [col[:3] for col, _ in c.most_common(8) if col[3] == 255]
    if len(opaque) < 2:
        raise SystemExit('expected two flat colours — is this still a solid tag?')
    pair = sorted(opaque[:2], key=lum)
    return pair[1], pair[0]


def strip(name):
    """A tag's lettering, with the plate colour discarded. Every pixel in the
    art sits on the line from the fill to the ink, because the only shape in it
    is antialiased lettering — so how far along that line a pixel lies IS its
    coverage."""
    src = Image.open(ART / name).convert('RGBA')
    w, h = src.size
    px = src.load()
    ink, bg = ink_and_fill(px, w, h)
    span = [i - b for i, b in zip(ink, bg)]
    denom = sum(v * v for v in span) or 1

    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            t = sum(v * (c - o) for v, c, o in zip(span, (r, g, b), bg)) / denom
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            dst[x, y] = (*ink, round(a * t))
    line = out.crop(out.getbbox())
    # No descenders in "WTA 500": the lettering's box IS its cap height.
    return line, line.size[1], ink, bg


# ---------------------------------------------------------- ATP: number inline

STACKED = {
    'atp-250-inline.png': 'categorystamps_250-dark.png',
    'atp-500-inline.png': 'categorystamps_500.png',
    'atp-1000-inline.png': 'categorystamps_1000.png',
}

# The gap between wordmark and number, as a fraction of the cap height.
GAP = 0.20
# The right slice of the wordmark that is letters only. The swoosh sweeps in
# from the left, so the mark's whole box is not the letters' height.
LETTERS_ONLY = 0.45
# The blank column band that separates a word from the number, as a fraction of
# the row's height. A word space is far wider than the space between two
# digits: on the Masters stamp the gap before "1000" is 18px of a 117px row
# (15%) while the widest gap BETWEEN its digits is 4px (3%), so anything above
# this is a word boundary and anything below it is kerning.
WORD_GAP = 0.08


def split_at_gap(im):
    """The wordmark and the number, cut apart on the widest blank band."""
    w, h = im.size
    a = im.split()[3]
    rows = [any(a.getpixel((x, y)) > 12 for x in range(w)) for y in range(h)]
    top, bot = im.getbbox()[1], im.getbbox()[3]
    best, y = (0, None), top
    while y < bot:
        if not rows[y]:
            start = y
            while y < bot and not rows[y]:
                y += 1
            if y - start > best[0]:
                best = (y - start, (start, y))
        else:
            y += 1
    if not best[1]:
        raise SystemExit('no blank band — is this stamp still stacked?')
    a_, b_ = best[1]
    return im.crop((0, 0, w, a_)), im.crop((0, b_, w, h))


def digits_only(row):
    """Drop a word set beside the number ("MASTERS"), by the gap before it.

    NOT BY HEIGHT: "MASTERS" is set in caps three quarters of the digits'
    height, so no threshold separates them without also cutting a digit off the
    stamps that have no word at all.
    """
    row = row.crop(row.getbbox())
    w, h = row.size
    a = row.split()[3]
    ink = [any(a.getpixel((x, y)) > 12 for y in range(h)) for x in range(w)]
    runs, x = [], 0
    while x < w:
        if not ink[x]:
            start = x
            while x < w and not ink[x]:
                x += 1
            runs.append((start, x - start))
        else:
            x += 1
    if not runs:
        return row                      # digits touching: "250" has no gap at all
    at, width = max(runs, key=lambda r: r[1])
    if width < h * WORD_GAP:
        return row                      # only kerning: nothing to drop
    return row.crop((at + width, 0, w, h))


def trim_bearing(mark):
    """Drop the leading columns whose ink covers less than BEARING of the
    height — see the note on BEARING. Nothing is trimmed from a mark that
    starts on substance, which is every one but the ATP's."""
    w, h = mark.size
    a = mark.split()[3]
    solid = [x for x in range(w)
             if sum(1 for y in range(h) if a.getpixel((x, y)) > 12) >= h * BEARING]
    return mark.crop((solid[0], 0, w, h)) if solid else mark


def parts(name):
    """The ATP wordmark, its number at the wordmark's cap height, and that cap.

    These are the parts BOTH tours' stamps are built from: the ATP ships the
    only numerals either stamp uses now, and its wordmark's box is the box the
    WTA's is fitted to.
    """
    src = Image.open(ART / name).convert('RGBA')
    mark, row = split_at_gap(src)
    mark = trim_bearing(mark.crop(mark.getbbox()))
    num = digits_only(row)

    mw, mh = mark.size
    caps = mark.crop((round(mw * (1 - LETTERS_ONLY)), 0, mw, mh)).getbbox()
    cap = caps[3] - caps[1]
    num = num.resize((max(1, round(num.size[0] * cap / num.size[1])), cap), Image.LANCZOS)
    return mark, num, cap


# ------------------------------------------------------------------- do it

TIERS = ['250', '500', '1000']
lines = {}

ATP_INK = flat_colour(INK_SOURCE)
print(f'ink: ATP {ATP_INK} (read from {INK_SOURCE}), WTA {WTA_INK} (theme)\n')

for tier in TIERS:
    atp_file, wta_file = f'atp-{tier}-inline.png', f'{tier}k-tag-plate.png'
    mark, num, cap = parts(STACKED[atp_file])
    gap = round(cap * GAP)
    lines[atp_file] = tight(
        bottom_line(recolour(mark, ATP_INK), recolour(num, ATP_INK), gap), cap)

    # THE WTA WORDMARK, IN THE ATP WORDMARK'S EXACT BOX, beside the ATP's own
    # numerals in the WTA's ink. Everything the two stamps do not share is now
    # just the shape of three letters: same numerals, same wordmark box, and
    # therefore the same line, the same plate and the same margins. Stretching
    # the WTA's condensed numerals to the ATP's width was the previous attempt
    # at this and it did not survive contact with the phone (owner,
    # 2026-09-15) — borrowing the glyphs outright is the version that works.
    wta_line, wta_cap, ink, bg = strip(TAGS[wta_file])
    at, wta_gap = split_number(wta_line)
    wordmark = wta_line.crop((0, 0, at, wta_line.size[1]))
    wordmark = wordmark.crop(wordmark.getbbox()).resize(mark.size, Image.LANCZOS)
    lines[wta_file] = tight(
        bottom_line(recolour(wordmark, WTA_INK), recolour(num, WTA_INK), gap), cap)

    slip = tuple(a - b for a, b in zip(lines[atp_file].size, lines[wta_file].size))
    if max(abs(v) for v in slip) > 2:
        raise SystemExit(f'{tier}: the two tours ended up different sizes '
                         f'({lines[atp_file].size} vs {lines[wta_file].size}) — '
                         'they are built from the same pieces, so this is not rounding')
    if any(slip):
        lines[wta_file] = pad_to(lines[wta_file], lines[atp_file].size)

    print(f'{tier}: both tours {lines[atp_file].size[0]}x{lines[atp_file].size[1]}'
          f'{f" (WTA padded by {slip})" if any(slip) else ""}  '
          f'(wordmark fitted to {mark.size[0]}x{mark.size[1]}, '
          f'numerals {num.size[0]}x{num.size[1]}; tag lettering was {ink} on {bg})')

for out_name, line in lines.items():
    line.save(ART / out_name)

# The badge draws each stamp CAP tall and aspect x CAP wide, so it needs the
# aspect ratios. It cannot ask the runtime for them: Image.resolveAssetSource
# exists on iOS but not in react-native-web, where it red-boxed the visual
# harness. They are known here, exactly, so they are written out here — and
# tierStamps.test.mjs reads the PNG headers back to catch this file drifting
# away from the artwork it describes.
rows = ',\n'.join(
    f'  {tour}: {{ ' + ', '.join(
        f'{t}: {round(lines[f + t + s].size[0] / lines[f + t + s].size[1], 4)}'
        for t in TIERS) + ' }'
    for tour, f, s in (('atp', 'atp-', '-inline.png'), ('wta', '', 'k-tag-plate.png')))
(ART.parent.parent / 'tierStampAspect.js').write_text(
    '/* GENERATED by tools/gen-tier-stamps.py — do not edit.\n'
    ' * Width divided by height of each tier stamp, whose artwork is cropped to\n'
    ' * its lettering: TierBadge draws it CAP tall and aspect x CAP wide. Both\n'
    ' * tours are built to one line, so the pairs match exactly. */\n'
    'export default {\n' + rows + ',\n}\n\n'
    '/* The ink each tour\'s artwork is flattened to: TOUR[*].text in\n'
    ' * theme.js. Exported so a token change cannot silently leave the PNGs\n'
    ' * behind — tierStamps.test.mjs compares the two. */\n'
    'export const INK = { atp: %r, wta: %r }\n'
    % ('#%02x%02x%02x' % ATP_INK, '#%02x%02x%02x' % WTA_INK))

print(f'\nwrote {len(lines)} stamps at cap {CAP}px, cropped to the ink, '
      '+ mobile/tierStampAspect.js')
