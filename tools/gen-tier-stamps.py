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


def widen_number(line, target):
    """Set the number to `target` px wide, leaving the wordmark alone.

    A HORIZONTAL SCALE, not a bigger number: the cap heights are matched across
    both tours and a proportional scale would break that, leaving "500"
    towering over the "WTA" beside it. The WTA sets its tier numbers in a
    condensed face and the ATP in a wide italic, so at one cap height the ATP's
    digits are ~1.5x wider and the WTA's read as the smaller of the two even
    though they are the same height (owner, 2026-09-15). Stretching condensed
    digits by that much lands them at about a normal width, which is why this
    is worth doing at all rather than being visible damage.
    """
    at, gap = split_number(line)
    w, h = line.size
    num = line.crop((at + gap, 0, w, h))
    num = num.resize((target, h), Image.LANCZOS)
    out = Image.new('RGBA', (at + gap + target, h), (0, 0, 0, 0))
    out.alpha_composite(line.crop((0, 0, at + gap, h)), (0, 0))
    out.alpha_composite(num, (at + gap, 0))
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


def inline(name):
    """The wordmark with its number re-set to the right, at the wordmark's cap
    height and on its baseline."""
    src = Image.open(ART / name).convert('RGBA')
    mark, row = split_at_gap(src)
    mark = mark.crop(mark.getbbox())
    num = digits_only(row)

    mw, mh = mark.size
    caps = mark.crop((round(mw * (1 - LETTERS_ONLY)), 0, mw, mh)).getbbox()
    cap = caps[3] - caps[1]
    num = num.resize((max(1, round(num.size[0] * cap / num.size[1])), cap), Image.LANCZOS)

    gap = round(cap * GAP)
    line = Image.new('RGBA', (mw + gap + num.size[0], max(mh, caps[3])), (0, 0, 0, 0))
    line.alpha_composite(mark, (0, 0))
    line.alpha_composite(num, (mw + gap, caps[3] - cap))     # on the baseline
    return line.crop(line.getbbox()), cap


# ------------------------------------------------------------------- do it

# ATP first: its number width is what the WTA number is set to.
TIERS = ['250', '500', '1000']
lines, atp_num = {}, {}

for tier in TIERS:
    out_name = f'atp-{tier}-inline.png'
    line, cap = inline(STACKED[out_name])
    line = tight(line, cap)
    lines[out_name] = line
    atp_num[tier] = number_width(line)
    print(f'{STACKED[out_name]}: number inline, {line.size[0]}x{line.size[1]}, '
          f'number {atp_num[tier]}px wide')

for tier in TIERS:
    out_name = f'{tier}k-tag-plate.png'
    line, cap, ink, bg = strip(TAGS[out_name])
    line = tight(line, cap)
    was = number_width(line)
    line = widen_number(line, atp_num[tier])
    lines[out_name] = line
    print(f'{TAGS[out_name]}: {ink} on {bg} -> transparent, number {was} -> '
          f'{number_width(line)}px wide, {line.size[0]}x{line.size[1]}')

for out_name, line in lines.items():
    line.save(ART / out_name)

# The badge draws each stamp CAP tall and aspect x CAP wide, so it needs the
# aspect ratios. It cannot ask the runtime for them: Image.resolveAssetSource
# exists on iOS but not in react-native-web, where it red-boxed the visual
# harness. They are known here, exactly, so they are written out here — and
# tierStamps.test.mjs reads the PNG headers back to catch this file drifting
# away from the artwork it describes.
aspect = {'atp': {}, 'wta': {}}
for tier in TIERS:
    a = lines[f'atp-{tier}-inline.png']
    w = lines[f'{tier}k-tag-plate.png']
    aspect['atp'][tier] = round(a.size[0] / a.size[1], 4)
    aspect['wta'][tier] = round(w.size[0] / w.size[1], 4)

rows = ',\n'.join(
    f"  {tour}: {{ " + ', '.join(f'{t}: {aspect[tour][t]}' for t in TIERS) + ' }'
    for tour in ('atp', 'wta'))
(ART.parent.parent / 'tierStampAspect.js').write_text(
    '/* GENERATED by tools/gen-tier-stamps.py — do not edit.\n'
    ' * Width divided by height of each tier stamp, whose artwork is cropped to\n'
    ' * its lettering: TierBadge draws it CAP tall and aspect x CAP wide. */\n'
    'export default {\n' + rows + ',\n}\n')

print(f'\nwrote {len(lines)} stamps at cap {CAP}px, cropped to the ink:')
for n, l in lines.items():
    print(f'  {n:22} {l.size[0]}x{l.size[1]}  aspect {l.size[0] / l.size[1]:.2f}')
print('  + mobile/tierStampAspect.js')
