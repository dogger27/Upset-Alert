"""
Make the two tours' tier stamps the same kind of object.

They ship in two different shapes, and the dashboard now draws both on a
tour-coloured plate, which is what made the difference impossible to ignore:

  WTA — lettering knocked out of an opaque rounded rectangle in the WTA's own
  tier colour (purple 250, teal 500, gold 1000). The plate would have framed a
  purple block. Pass one strips each tag to its lettering, alpha set to how
  much of the pixel the letters covered, so the colour behind it comes from
  theme.js instead of a PNG.

  ATP — the wordmark with the number STACKED underneath it, where the WTA tag
  sets them side by side at one height. Pass two takes the artwork apart at the
  gap between the two and re-sets it inline: the number scaled to the
  wordmark's cap height and sitting on its baseline, to the right, as
  "WTA 500" already reads (owner, 2026-09-15).

Both passes read their geometry out of the art — the flat colours, the gap
between the rows, where the letters end and the swoosh begins — rather than
from numbers typed in here. Every one of those is something that changes the
day the artwork is redrawn, and a hard-coded value would then be a silently
wrong answer rather than a crash.

Originals are kept beside the output: they are this script's input.

    python3 gen-tier-stamps.py
"""
from collections import Counter
from pathlib import Path

from PIL import Image

ART = Path(__file__).parent.parent / 'mobile' / 'assets' / 'logos'
# The TIER tags only. The ATP stamps are already drawn on transparency, and the
# slam crests are left exactly as their tournaments draw them — the WTA slam
# mark ships on a plate of its own and keeps it (owner, 2026-09-15).
TAGS = ['250k-tag.png', '500k-tag.png', '1000k-tag.png']


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def ink_and_fill(px, w, h):
    """The two colours the art is made of: the lettering and the plate behind
    it. Read from the art rather than typed in — every one of these files is a
    flat fill under flat letters, and a hard-coded triple is a silent wrong
    answer the day the artwork is redrawn. The lettering is the lighter of the
    two in all of them (white or off-white on a colour)."""
    c = Counter(px[x, y] for y in range(0, h, 2) for x in range(0, w, 2))
    opaque = [col[:3] for col, _ in c.most_common(8) if col[3] == 255]
    if len(opaque) < 2:
        raise SystemExit('expected two flat colours — is this still a solid tag?')
    pair = sorted(opaque[:2], key=lum)
    return pair[1], pair[0]


for name in TAGS:
    src = Image.open(ART / name).convert('RGBA')
    w, h = src.size
    px = src.load()
    ink, bg = ink_and_fill(px, w, h)

    # Every pixel in the art sits on the line from the fill to the ink, because
    # the only shape in it is antialiased lettering. How far along that line a
    # pixel lies IS its coverage.
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

    target = ART / name.replace('.png', '-plate.png')
    out.save(target)
    covered = sum(1 for y in range(h) for x in range(w) if dst[x, y][3] > 8)
    print(f'{name}: {ink} lettering on {bg} -> transparent, '
          f'{covered} lettering px, wrote {target.name}')


# ---------------------------------------------------------------- ATP, inline

# The stacked stamps. "-dark" on the 250 because the shipped 250 is flat navy,
# invisible on a dark card; the other two read either way (see logos.js).
STACKED = {
    'atp-250-inline.png': 'categorystamps_250-dark.png',
    'atp-500-inline.png': 'categorystamps_500.png',
    'atp-1000-inline.png': 'categorystamps_1000.png',
}

# The WTA tags' own proportions, so `contain` in a 76x32 box gives both tours'
# lettering the same visual weight: the letters fill ~90% of the frame's width
# and ~70% of its height, and the margin is what holds them to that size.
LETTER_W, LETTER_H = 0.90, 0.70
# The gap between wordmark and number, as a fraction of the cap height.
GAP = 0.20
# The right slice of the wordmark that is letters only. The swoosh sweeps in
# from the left and its lowest point is below the baseline, so the mark's whole
# box is not the height the digits should match.
LETTERS_ONLY = 0.45
# The blank column band that separates a word from the number, as a fraction of
# the row's height. A word space is far wider than the space between two
# digits: on the Masters stamp the gap before "1000" is 18px of a 117px cap
# height (15%) while the widest gap BETWEEN its digits is 4px (3%), so
# anything above this is a word boundary and anything below it is kerning.
WORD_GAP = 0.08
# 3x for a 76pt box needs ~230px; the sources are 761 wide and the output of
# two lossless steps is wider still, all of it bundle weight nobody sees.
MAX_W = 600


def ink_rows(im):
    w, h = im.size
    a = im.split()[3]
    return [any(a.getpixel((x, y)) > 12 for x in range(w)) for y in range(h)]


def split_at_gap(im):
    """The wordmark and the number, cut apart on the widest blank band between
    them."""
    rows = ink_rows(im)
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
    a, b = best[1]
    w, h = im.size
    return im.crop((0, 0, w, a)), im.crop((0, b, w, h))


def digits_only(row):
    """Drop a word set beside the number ("MASTERS"), by the gap between them.

    NOT BY HEIGHT, which was the first attempt: "MASTERS" is set in caps that
    reach three quarters of the digits' height, so no threshold separates them
    without also cutting a digit off the stamps that have no word at all. The
    space between the word and the number is unambiguous — see WORD_GAP.
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


for out_name, src_name in STACKED.items():
    src = Image.open(ART / src_name).convert('RGBA')
    mark, row = split_at_gap(src)
    mark = mark.crop(mark.getbbox())
    num = digits_only(row)

    mw, mh = mark.size
    caps = mark.crop((round(mw * (1 - LETTERS_ONLY)), 0, mw, mh)).getbbox()
    cap_h = caps[3] - caps[1]
    num = num.resize((max(1, round(num.size[0] * cap_h / num.size[1])), cap_h),
                     Image.LANCZOS)

    gap = round(cap_h * GAP)
    line = Image.new('RGBA', (mw + gap + num.size[0], max(mh, caps[3])), (0, 0, 0, 0))
    line.alpha_composite(mark, (0, 0))
    line.alpha_composite(num, (mw + gap, caps[3] - cap_h))   # on the baseline
    line = line.crop(line.getbbox())

    lw, lh = line.size
    frame = Image.new('RGBA', (round(lw / LETTER_W), round(lh / LETTER_H)), (0, 0, 0, 0))
    frame.alpha_composite(line, ((frame.size[0] - lw) // 2, (frame.size[1] - lh) // 2))
    if frame.size[0] > MAX_W:
        frame = frame.resize(
            (MAX_W, round(frame.size[1] * MAX_W / frame.size[0])), Image.LANCZOS)

    frame.save(ART / out_name)
    print(f'{src_name}: number inline at cap height {cap_h}px, '
          f'{frame.size[0]}x{frame.size[1]} (aspect {frame.size[0] / frame.size[1]:.2f}), '
          f'wrote {out_name}')
